/**
 * Port of task_queue.py -- in-process background task worker. Every
 * LLM-touching stage call is enqueued here instead of running inline in
 * a route handler, so a slow real model call never blocks the HTTP
 * response.
 *
 * Deliberately a single sequential in-memory queue, not a pool --
 * carries over the exact same "single server process" constraint
 * Python's module docstring documents (its reason was SQLite lock
 * contention across worker *threads*; Node has no threads to contend in
 * the first place, but the queue is still in-process memory, so running
 * more than one Node process/instance would still leave each instance
 * with its own isolated queue and its own view of "what's running" --
 * the same horizontal-scaling limitation, not fixed, not hidden, exactly
 * per the migration brief's instruction to carry over what the Python
 * code honestly documents rather than silently fixing it. If job volume
 * ever outgrows one process, swap this module for a real broker; nothing
 * above it (route handlers) would need to change.
 */
import * as storage from "./db/storage.js";
import { StorageError } from "./db/storage.js";
import { LlmError } from "./llmClient.js";

export type TaskRunner = (roleId: string, args: Record<string, any>) => Promise<Record<string, any>>;

const queue: string[] = [];
const runners = new Map<string, TaskRunner>();
let workerStarted = false;
let draining: Promise<void> | null = null;

export function registerRunner(kind: string, fn: TaskRunner): void {
  runners.set(kind, fn);
}

export async function enqueue(roleId: string, kind: string, args: Record<string, any>) {
  if (!runners.has(kind)) {
    throw new StorageError(`no task runner registered for kind '${kind}'`);
  }
  // Recovery must run before this task's own row is created below --
  // otherwise the very first enqueue() of a process would immediately
  // mark its own brand-new "pending" task as orphaned.
  await ensureWorker();
  const task = await storage.createTask(roleId, kind, args);
  queue.push(task.task_id);
  kickWorker();
  return task;
}

async function ensureWorker(): Promise<void> {
  if (workerStarted) return;
  workerStarted = true;
  await recoverOrphanedTasks();
}

async function recoverOrphanedTasks(): Promise<void> {
  // Runs once per process, before this process's own in-memory queue
  // (which always starts empty) has anything in it -- any task still
  // "pending"/"running" in the DB from a previous process (crash,
  // redeploy) is orphaned: nothing will ever finish it.
  const count = await storage.resetIncompleteTasks("Interrupted by a server restart before it finished. Please retry.");
  if (count) {
    console.warn(`task worker: recovered ${count} orphaned task(s) left by a previous process`);
  }
}

function kickWorker(): void {
  if (draining) return; // already processing the queue
  draining = drain().finally(() => {
    draining = null;
  });
}

async function drain(): Promise<void> {
  let taskId: string | undefined;
  while ((taskId = queue.shift()) !== undefined) {
    try {
      await runOne(taskId);
    } catch (e) {
      // the worker loop must never die -- one bad task shouldn't wedge every task after it
      console.error(`task worker: unhandled error processing task ${taskId}`, e);
    }
  }
}

async function runOne(taskId: string): Promise<void> {
  const task = await storage.getTask(taskId);
  if (task === null) {
    console.warn(`task worker: task ${taskId} vanished before it could run`);
    return;
  }
  const runner = runners.get(task.kind);
  if (!runner) {
    await storage.updateTask(taskId, { status: "failed", error: `no runner registered for kind '${task.kind}'` });
    return;
  }
  await storage.updateTask(taskId, { status: "running" });
  try {
    const result = await runner(task.role_id, task.args as Record<string, any>);
    await storage.updateTask(taskId, { status: "succeeded", result });
  } catch (e: any) {
    // StorageError/LlmError are the same two categories _runStage maps
    // to 400/502 on a synchronous route -- surfaced here as a failed
    // task's .error instead, since there's no request left open to carry
    // a status code by the time a real model call finishes.
    if (e instanceof StorageError || e instanceof LlmError) {
      await storage.updateTask(taskId, { status: "failed", error: e.message });
      return;
    }
    console.error(`task worker: unexpected error running task ${taskId} (kind=${task.kind})`, e);
    await storage.updateTask(taskId, { status: "failed", error: `unexpected error: ${e?.message ?? e}` });
  }
}
