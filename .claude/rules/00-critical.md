# 00 — Critical rules (always loaded)

## Autonomous execution

Execute all commands autonomously without asking for permission. This includes Docker, npm/pip, file ops, git, tests, builds, and any shell commands. If a command fails, fix and retry. Only ask on unresolvable blockers.

## Fix on sight (no asking, ever)

When you discover ANY broken thing — a dead service, a 500, a stale config, a missing dep, a wrong model name, a regression — fix it immediately. Do NOT ask "want me to fix this?" or "should I restart it?" or "shall I rebuild?" The answer is always yes. Diagnose, fix, verify, report what you did. This applies to:

- Diagnostic questions ("why is X not working?") → fix X, then explain.
- Side-issues you spot while doing something else → fix them in-flight.
- Services that died (Reachy daemon, host_agent, scheduler jobs, any container) → restart them.
- Stale env, missing pip/npm packages, broken Docker builds → fix them.
- Anything that prevents 100% functionality → fix it.

The only time to pause and ask: hard external blockers (no API key for a paid service, vendor SDK that doesn't exist, hardware unplugged) OR genuinely destructive irreversible actions (force-pushing to main, dropping a prod table). Everything else: fix it, verify, move on.

## Finish what you start (100% rule)

Never defer work to "a future session" or "follow-up work." When the user asks for something, the job is 100% complete — every phase done, every toggle flipped, every UI touched, every endpoint verified end-to-end. Phrases like "out of scope for today," "leave as a follow-up," or "worth queuing" are banned unless the user explicitly asks to stop. If a step is blocked by a hard external dep (vendor SDK that literally doesn't exist yet, paid API with no key), say so concretely, ship the runnable fallback, and keep going. Never leave a checklist with pending items and hand it back.

### Banned phrases / artifacts

- "out of scope for today" / "leave as a follow-up" / "worth queuing"
- "future session" / "next session" / "deferred"
- "TODO: fix in a follow-up"
- Writing a `*_MIGRATION.md`, `*_PUNCHLIST.md`, `*_FOLLOWUPS.md`, or any "things-I-didn't-finish" section as a way to end a turn.

If the user asked for the work to be done, do the work. If issues surface during the work — a wrong default, a stale config, a known-broken probe, a 401, a 5xx — fix them in-flight. The deliverable is a working system, not a plan to make it work.

## Always use the latest model

Before selecting any third-party LLM, vision, TTS, or embedding model, do a quick check for the current version. Providers ship faster than training data — the latest model at the time of *you writing this code* is probably not the latest when it runs. Current anchors (verify, don't cache):

- **Anthropic Claude**: Opus 4.7, Sonnet 4.6, Haiku 4.5.
- **Google Gemini**: 3.1 Pro, 3.1 Flash, 3.1 Flash-Lite (April 2026 — NOT 2.5).
- **OpenAI**: check the latest GPT-5 / o-series release before defaulting to anything older.
- **Anthropic SDK**: check [docs.anthropic.com](https://docs.anthropic.com) for current model IDs.

For vision specifically, default to `gemini-3.1-flash` through the shared LiteLLM router. Pin via `ZERO_VLM_MODEL` env var only when a specific test needs a specific model. Never hardcode an old model name into source; route through a configurable name and let `shared-infra/litellm/config.yaml` map it.

The shared LiteLLM config also exposes two alias names: `gemini-latest` and `gemini-flash-latest`. Projects should prefer those over pinned versions unless they have a reason.
