// Port of stages/interview_questions.py -- role-level interview
// questions generated from the ICP and calibration, distinct from
// screening.ts (validates one candidate's own record). Each run appends
// a new generation rather than overwriting the last one.
import * as storage from "../db/storage.js";
import * as llmClient from "../llmClient.js";
import {
  InterviewQuestion, RoleInterviewQuestions, InterviewQuestionGeneration, interviewQuestionHistoryFromRaw,
} from "../models.js";

const MIN_QUESTIONS = 10;

function normalize(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9 ]/g, "").trim();
}

function allQuestions(gen: { core_questions: InterviewQuestion[]; role_specific_questions: InterviewQuestion[]; red_flag_questions: InterviewQuestion[] }) {
  return [...gen.core_questions, ...gen.role_specific_questions, ...gen.red_flag_questions];
}

export async function run(roleId: string) {
  const icp = await storage.requireSection(roleId, "icp");
  const calibration = await storage.requireSection(roleId, "calibration");
  const state = await storage.loadRole(roleId);
  const history = interviewQuestionHistoryFromRaw(state.interview_questions);

  const priorQuestions = history.generations.flatMap((gen) => allQuestions(gen).map((q) => q.question));
  const priorQuestionsText = priorQuestions.length
    ? priorQuestions.map((q) => `- ${q}`).join("\n")
    : "(none yet — this is the first generation for this role)";

  const prompt = llmClient.renderPrompt("interview_questions.md", {
    icp_json: JSON.stringify(icp), calibration_json: JSON.stringify(calibration),
    prior_questions_text: priorQuestionsText,
  });
  let result = await llmClient.generate(prompt, RoleInterviewQuestions, { stage: "interview_questions" });

  const total = allQuestions(result).length;
  if (total < MIN_QUESTIONS) {
    const retryPrompt = prompt +
      `\n\nYour previous attempt returned only ${total} questions total across all three groups combined ` +
      `— this role needs at least ${MIN_QUESTIONS}. Cover more ground within each group and try again.`;
    const retried = await llmClient.generate(retryPrompt, RoleInterviewQuestions, { stage: "interview_questions" });
    if (allQuestions(retried).length > total) result = retried;
  }

  const priorNormalized = new Set(priorQuestions.map(normalize));
  const repeated = allQuestions(result)
    .filter((q) => priorNormalized.has(normalize(q.question)))
    .map((q) => q.question);

  const generation: InterviewQuestionGeneration = {
    generated_at: new Date().toISOString(),
    core_questions: result.core_questions,
    role_specific_questions: result.role_specific_questions,
    red_flag_questions: result.red_flag_questions,
    repeated_questions: repeated,
  };
  history.generations.push(generation);
  await storage.mergeSection(roleId, "interview_questions", history);
  return history;
}
