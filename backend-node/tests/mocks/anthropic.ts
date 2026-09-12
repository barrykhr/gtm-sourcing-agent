// A fake @anthropic-ai/sdk client good enough to drive both call sites
// that talk to the real SDK: llmClient.generate() (messages.parse, used
// by every AI stage) and orchestrator.ts's tool-use loop
// (beta.messages.toolRunner, used by Copilot chat).
//
// Per orchestrator.ts's own testing note: there is no way to check
// *tool-selection quality* without real inference, so this never
// pretends to choose which tool to call — each test scripts exactly
// what the "model" says, and the fake runner calls the REAL tool
// implementations (the same TOOL_IMPLS closures the real SDK would
// call), so tool execution, confirmation-gating, and history
// persistence are exercised against real code, not a stub.

export interface ScriptedTurn {
  content: Array<
    | { type: "text"; text: string }
    | { type: "tool_use"; id: string; name: string; input: any }
  >;
}

export const anthropicMock: {
  /** Consumed by llmClient.generate() -- must satisfy whatever Zod
   * schema the calling stage validates against. */
  nextParsedOutput: any;
  /** Consumed by orchestrator.ts's runToolLoop() -- one scripted
   * assistant turn per array entry; a turn containing a tool_use block
   * causes the real tool to run and the loop to continue to the next
   * scripted turn. */
  chatScript: ScriptedTurn[];
} = {
  nextParsedOutput: undefined,
  chatScript: [],
};

function makeFakeToolRunner(tools: Array<{ name: string; run: (input: any) => Promise<any> }>, script: ScriptedTurn[]) {
  const toolsByName = new Map(tools.map((t) => [t.name, t]));
  let index = -1;
  let lastContent: ScriptedTurn["content"] | null = null;
  let finished = false;

  return {
    [Symbol.asyncIterator]() {
      return this;
    },
    async next() {
      if (finished) return { done: true as const, value: undefined };
      index++;
      if (index >= script.length) {
        finished = true;
        return { done: true as const, value: undefined };
      }
      lastContent = script[index]!.content;
      return { done: false as const, value: { content: lastContent } };
    },
    async generateToolResponse() {
      const toolUses = (lastContent ?? []).filter((b): b is Extract<typeof b, { type: "tool_use" }> => b.type === "tool_use");
      if (!toolUses.length) {
        finished = true;
        return null;
      }
      const resultBlocks = [];
      for (const tu of toolUses) {
        const tool = toolsByName.get(tu.name);
        const result = tool ? await tool.run(tu.input) : `error: no tool registered named '${tu.name}'`;
        resultBlocks.push({
          type: "tool_result",
          tool_use_id: tu.id,
          content: typeof result === "string" ? result : JSON.stringify(result),
        });
      }
      return { role: "user", content: resultBlocks };
    },
  };
}

export class FakeAnthropic {
  messages = {
    parse: async (_params: any) => {
      if (anthropicMock.nextParsedOutput === undefined) {
        throw new Error(
          "anthropicMock.nextParsedOutput was not set before a stage called llmClient.generate() -- set it in the test first."
        );
      }
      return { parsed_output: anthropicMock.nextParsedOutput, stop_reason: "end_turn" };
    },
  };

  beta = {
    messages: {
      toolRunner: (params: { tools: Array<{ name: string; run: (input: any) => Promise<any> }> }) =>
        makeFakeToolRunner(params.tools, anthropicMock.chatScript),
    },
  };

  static AuthenticationError = class extends Error {};
  static PermissionDeniedError = class extends Error {};
  static NotFoundError = class extends Error {};
  static RateLimitError = class extends Error {};
  static BadRequestError = class extends Error {};
  static APIConnectionError = class extends Error {};
  static APIError = class extends Error {};
}
