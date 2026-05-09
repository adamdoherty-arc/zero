# Add an "Eightfold MCP" council member

## Context

Today, every council member in DTC is a Digital Twin (DT) — a real person backed by the DT MCP `ask` tool. The user wants a new kind of member, "Eightfold MCP", that can be added to any council. It's not a person — it's an agent that consults the **Eightfold internal MCP server** (`https://stage-mcp.eightfold.ai/mcp/`) and brings back platform-grounded answers (config values, DB query results, i18n strings, feature gates).

Why this matters: today the council reasons over people's perspectives. Adding an Eightfold MCP member lets the council pull in **factual platform state** (what is this gate set to? what does this DB row look like? what are the i18n overrides?) — turning the council into a hybrid of opinion + ground truth. The user already has a token.

The available Eightfold MCP tools (per the doc the user pasted): `config`, `db_explorer`, `helixa`, `get_strings`, `get_i18n_override_config`. All read-only.

User design decisions (locked in):
- **Tool execution**: fan out — call every available MCP tool in parallel and merge results. (Parameter inference still required since each tool needs concrete args; we'll derive params with Gemini in one shot.)
- **UI**: pin "Eightfold MCP" at the top of the PeoplePicker's All People list when the token is configured. No separate toggle — adding it to the council is the switch.
- **Default endpoint**: `https://stage-mcp.eightfold.ai/mcp/`, overridable via env var.

## Approach

Add a synthetic council member backed by a new `provider="eightfold-mcp"` discriminator on the `Twin` type. When an execution dispatches this twin, instead of calling the DT MCP `ask` tool, route to a new Eightfold MCP client that:

1. Lists tools via JSON-RPC `tools/list` (cached per process).
2. Uses Gemini once to generate a **tool-call plan** — for every tool, either `{ args }` to execute or `{ skip: true, reason }` (when the question is unrelated). Structured output via `generateObject`.
3. Fires every planned tool call **in parallel** via JSON-RPC `tools/call` (Bearer auth). Errors per-tool are caught and included as evidence with `error: ...`.
4. Synthesizes the merged tool outputs into a standard `TwinResponse` shape (`position`, `rationale[]`, `assumptions[]`, `confidence_score`, `key_evidence[]`) using Gemini.

The synthetic twin is added to the front of `listTwins()` when `EIGHTFOLD_MCP_TOKEN` is set on the server. Since `listTwins()` is called server-side from API routes (and from the council page server-rendered fetch), the token never reaches the browser.

The execution route (`POST /api/execute/[sessionId]`) already filters by `has_bot !== false` and queries each member in parallel — no changes needed there. Routing happens inside `queryTwin()` based on `twin.provider`.

## Files

### New

- **[src/lib/api/eightfold-mcp-client.ts](src/lib/api/eightfold-mcp-client.ts)** — main client. Exports:
  - `EIGHTFOLD_MCP_TWIN: Twin` — the synthetic council member (id `eightfold-mcp`, provider `eightfold-mcp`, accent `amber`, weight `0.85`, initials `8F`).
  - `isEightfoldMcpEnabled(): boolean` — server-side check that `EIGHTFOLD_MCP_TOKEN` exists.
  - `queryTwinViaEightfoldMcp(twin, question, opts): Promise<TwinResponse>` — the implementation.
  - Internal: `listEightfoldTools()` (cached), `planToolCalls()` (Gemini structured output), `callEightfoldTool(name, args)` (JSON-RPC).

- **[src/lib/orchestration/__tests__/eightfold-mcp-client.test.ts](src/lib/orchestration/__tests__/eightfold-mcp-client.test.ts)** — Vitest tests:
  - `normalizeEightfoldResponse()` produces a valid `TwinResponse` from a fixture of merged tool outputs.
  - Per-tool error envelopes are surfaced as `key_evidence` entries with the error text, not thrown.
  - Skipped tools (plan said skip) don't appear in evidence.

### Modified

- **[src/types/twin.ts](src/types/twin.ts)** — add optional `provider?: "dt" | "eightfold-mcp"` (defaults to `"dt"` semantically when absent). One-line addition.

- **[src/lib/api/digital-twin-client.ts](src/lib/api/digital-twin-client.ts)**:
  - In `queryTwin()` (line 282), after the mock-mode branch, route to `queryTwinViaEightfoldMcp` when `twin.provider === "eightfold-mcp"`. Return its result instead of `queryTwinViaMCP`.
  - In `listTwins()` (line 25), after fetching the base list, prepend `EIGHTFOLD_MCP_TWIN` if `isEightfoldMcpEnabled()`. Skip in mock mode.

- **[.env.example](.env.example)** — add at the bottom:
  ```
  # ── Eightfold MCP (optional council member) ──
  # When set, "Eightfold MCP" appears as a council member that can read platform configs,
  # run SELECT queries, and look up i18n strings via Eightfold's internal MCP server.
  EIGHTFOLD_MCP_ENDPOINT=https://stage-mcp.eightfold.ai/mcp/
  EIGHTFOLD_MCP_TOKEN=
  ```

- **[src/components/council/PeoplePicker.tsx](src/components/council/PeoplePicker.tsx)** (line 134) — when ranking `filteredPeople`, sort `provider === "eightfold-mcp"` to the top with a small "Tool" badge next to the role text. ~10 line change in the existing `PersonRow` and the All People sort.

### Reuse (no changes)

- Synthesizer (`src/lib/orchestration/synthesizer.ts`) — works as-is. It treats every `TwinResponse` uniformly; the Eightfold member votes and gets weighted like everyone else.
- Execution route (`src/app/api/execute/[sessionId]/route.ts`) — `has_bot: true` on the synthetic twin keeps it queryable; status events stream the same way.
- Gemini client — already configured via `@ai-sdk/google` and `GOOGLE_GENERATIVE_AI_API_KEY` (used by [src/lib/orchestration/synthesizer.ts](src/lib/orchestration/synthesizer.ts) and [src/lib/orchestration/council-recommender.ts](src/lib/orchestration/council-recommender.ts)).
- DT MCP SSE parsing pattern (line 144 in `digital-twin-client.ts`) — the Eightfold MCP server uses the same SSE-wrapped JSON-RPC envelope, so the parsing helper can be lifted/shared.

## Key contract

```ts
// src/lib/api/eightfold-mcp-client.ts
export const EIGHTFOLD_MCP_TWIN: Twin = {
  id: "eightfold-mcp",
  enc_id: "eightfold-mcp",
  provider: "eightfold-mcp",
  name: "Eightfold MCP",
  role: "Platform Knowledge Agent",
  expertise: ["config", "db", "i18n", "feature gates", "platform"],
  avatar_initials: "8F",
  accent_color: "amber",
  weight: 0.85,
  description: "Consults Eightfold platform internals (configs, DB, i18n, gates) live via MCP.",
  has_bot: true,
};

export async function queryTwinViaEightfoldMcp(
  twin: Twin,
  question: string,
  options?: { onStatus?: (text: string) => void; thinkMode?: boolean }
): Promise<TwinResponse>;
```

Status updates emitted to the SSE stream during a query:
- `"Listing Eightfold tools…"` (first call only; cached after)
- `"Planning tool calls…"` (Gemini parameter inference)
- `"Querying Eightfold platform…"` (parallel fan-out)
- `"Synthesizing platform answer…"` (final Gemini summarization)

## Verification

1. Set `EIGHTFOLD_MCP_TOKEN=<the user's token>` in `.env.local` and `NEXT_PUBLIC_MOCK_MODE=false`. Confirm `GOOGLE_GENERATIVE_AI_API_KEY` and `DT_MCP_TOKEN` are set.
2. `npm run dev` and open http://localhost:3000.
3. Start a new council session. Click "+ Add" — confirm "Eightfold MCP" is pinned at the top of the All People list with the "Tool" badge.
4. Add it plus two real twins. Ask a platform question, e.g. *"What's in the career_hub_exchange_gate for volkscience.com?"*
5. On the execution page, confirm the Eightfold MCP card streams status updates and finishes with a position grounded in real config data (not a hallucinated guess).
6. Ask an unrelated question (e.g. *"Should we hire a third backend engineer?"*). Confirm the Eightfold member returns gracefully with a low-confidence answer noting that no platform data was directly relevant — and doesn't crash the council.
7. Run unit tests: `npm test src/lib/orchestration/__tests__/eightfold-mcp-client.test.ts`.
8. Toggle `EIGHTFOLD_MCP_TOKEN` empty, restart, confirm the synthetic member disappears from the picker.
