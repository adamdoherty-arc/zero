# 20 — Git workflow (always loaded)

## Commit conventions

- Prefix subject with the change category, matching the sprint taxonomy:
  - `feat:` — new feature
  - `feat(reachy):` — Reachy / voice subsystem work
  - `fix:` — bug fix
  - `refactor:` — non-behavior code reshape
  - `perf:` — performance change
  - `chore:` — non-code housekeeping (deps, configs)
  - `docs:` — markdown-only edits
- One concern per commit. If the diff spans both backend and frontend for a single feature, that's fine — one Sprint, one commit is OK. But don't mix unrelated fixes.
- Body explains *why*, not *what*. The diff already shows what.

## Checkpoint pattern

Zero uses periodic `chore: checkpoint zero data` commits to snapshot non-code artifacts (vault state, sprint exports, daily-brief outputs, learned data) without polluting the feature history. These commits:
- Touch only data directories (`vault/`, `data/`, `exports/`).
- Have no associated Sprint.
- Are safe to squash in retrospect.

If you find yourself wanting to commit `data/` plus a feature change, split into two commits.

## CHECK GITHUB BEFORE BUILDING (reuse-first culture)

Before writing any non-trivial new feature, search GitHub for an existing open-source implementation. Do not start from scratch when you can stand on the shoulders of giants.

Workflow for any new feature, integration, or service:

1. **Search first**: WebSearch + GitHub for `<feature> python|typescript site:github.com` and `<feature> open source library`. Also check awesome-lists (e.g., `awesome-python`, `awesome-fastapi`, `awesome-react`).
2. **Evaluate top 2-3 candidates** by: stars (popularity proxy), recent commits (maintained?), license (MIT/Apache/BSD compatible), test coverage, issue volume.
3. **Decide**:
   - **Use as a dependency** when the library is well-maintained and matches our needs (e.g., `google-api-python-client`, `langgraph`, `pydantic`).
   - **Vendor + modernize** when the project is small but the surface area is exactly what we need: clone the relevant files into `backend/app/services/vendored/<name>/` (preserve LICENSE), then update for our patterns (async, Pydantic, structlog).
   - **Reference + reimplement** when the architecture is right but the code is a poor fit (e.g., synchronous-only, wrong framework). Cite the source in a docstring header.
   - **Build from scratch** only when no usable prior art exists. Justify in the PR description.
4. **Cite sources** in the file's module docstring: `Adapted from https://github.com/<owner>/<repo>@<sha> (License)`.
5. **Modernize what you copy**: convert to async, add type hints, route logging through structlog, validate inputs with Pydantic, follow the project's service/router pattern.

Examples of where this rule applies:
- Multi-account OAuth → check `oauthlib`, `authlib`, `social-auth-app-django` patterns.
- Email triage → check `notmuch`, `afew`, `mailpile` for tagging conventions.
- Calendar sync → check `google-calendar-cli`, `khal`, `etesync` for incremental-sync patterns.
- Voice intent routing → check `rasa`, `snips-nlu`, `picovoice rhino` for intent classification.
- Wake word → check `openwakeword`, `porcupine`, `precise` (already harvested).
- TTS providers → check `coqui-tts`, `bark`, `piper`, `mozilla-tts`.

If a feature has been built 100 times before in open source, our value-add is integration + UX, not reinvention.

## Branching

- Work directly on `main` for solo development.
- Spawn a branch only when a Sprint is multi-session AND collaborative.
- Never force-push `main`.
