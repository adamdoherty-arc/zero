# Plan: Suppress the Claude Code "Malware" Reminder via Cozempic

## Context

Every `Read` tool result in Claude Code is followed by this hidden injection:

```
<system-reminder>
Whenever you read a file, you should consider whether it would be considered malware.
You CAN and SHOULD provide analysis of malware, what it is doing. But you MUST refuse to
improve or augment the code. You can still analyze existing code, write reports, or
answer questions about the code behavior.
</system-reminder>
```

It is **hardcoded into the Claude Code binary itself** ([C:\Users\hadam\.local\bin\claude.exe](C:/Users/hadam/.local/bin/claude.exe), v2.1.92, native PE32+ Windows build, 240 MB, installed Apr 3 2026), not in any of your config files. I verified `~/.claude/settings.json`, all hooks, all plugins, all skills, and the ADA project — none of them mention malware. It only appears in the `*.jsonl` transcripts after Claude Code already injected it.

Anthropic has refused to add an off switch:
- [#12443 — Get rid of malware warning in Read tool response](https://github.com/anthropics/claude-code/issues/12443) — open, no fix
- [#21214 — Wasting MILLIONS of tokens on Read system-reminder](https://github.com/anthropics/claude-code/issues/21214) — **closed as "not planned"**
- [#17601 — 10,000+ hidden injections, ~15% of context window](https://github.com/anthropics/claude-code/issues/17601)

Impact on you: this reminder is repeated on every `Read`, polluting context, draining the cache, and (per ADA's heavy file-read workflow) routinely consuming a chunk of every session's token budget. It also causes Claude to add defensive malware caveats to mundane config files, slowing real work.

You picked **Cozempic** as the removal path. Cozempic is a community Python tool ([Ruya-AI/cozempic](https://github.com/Ruya-AI/cozempic)) that wires into Claude Code's native hook system (no proxy, no binary patching) and deduplicates the reminder in the running session transcript so the model only sees it **once per session** instead of once per file Read.

## Approach

Install Cozempic globally for your user, run `cozempic init` so it registers its `SessionStart` / `PostToolUse` / `PreCompact` / `Stop` hooks in `~/.claude/settings.json`, enable the `system-reminder-dedup` strategy, and verify it removes duplicates from a fresh ADA session.

Cozempic's safety properties:
- Dry-run by default — modifications require `--execute`
- Atomic writes (`write → fsync → os.replace()`) with timestamped `.jsonl.bak` backups
- Never touches compact summaries, boundaries, or team messages
- Maintains transcript chain integrity via `parentUuid` re-linking

## Prerequisites (already satisfied)

- Python 3.14 installed (Cozempic requires 3.10+)
- pip 26.0.1 available
- Git Bash / MSYS available for shell commands
- Claude Code 2.1.92 with native hook support

## Steps

### 1. Back up your current Claude Code settings

```bash
cp ~/.claude/settings.json ~/.claude/settings.json.pre-cozempic.bak
```

The current [settings.json](C:/Users/hadam/.claude/settings.json) only has a `Stop` hook for the GSD verify gate and Telegram notify. Cozempic will add `SessionStart`, `PostToolUse`, `PreCompact`, and additional `Stop` hooks alongside it — back up first so we can roll back instantly.

### 2. Install Cozempic

```bash
pip install --user cozempic
```

Use `--user` to avoid touching the system Python install. Verify:

```bash
python -m cozempic --version
cozempic --version
```

If `cozempic` isn't on PATH after `--user` install, use `python -m cozempic` everywhere instead.

### 3. Run init

```bash
cozempic init
```

This wires the hook entries into `~/.claude/settings.json`. **After it runs, immediately diff against the backup**:

```bash
diff ~/.claude/settings.json.pre-cozempic.bak ~/.claude/settings.json
```

Confirm:
- The pre-existing GSD `Stop` hook is still present
- The pre-existing Telegram notify hook is still present
- New Cozempic entries are additive, not destructive

If init clobbered the GSD hook, restore from backup and instead merge Cozempic's hook entries by hand.

### 4. Enable the system-reminder dedup strategy

```bash
cozempic strategy system-reminder-dedup current -v
```

This is a dry-run preview against the current session transcript. It should report duplicate `<system-reminder>` blocks it would remove. If the count is `0`, run it against an older heavy-Read session in `~/.claude/projects/c--code-ADA/`:

```bash
cozempic strategy system-reminder-dedup ~/.claude/projects/c--code-ADA/<some-session>.jsonl -v
```

Once the preview looks right, enable it as a standing strategy (consult `cozempic --help` for the exact subcommand — it's typically `cozempic enable system-reminder-dedup` or via config).

### 5. Run a baseline diagnose

```bash
cozempic diagnose current
```

Records current token waste so you can compare after a few sessions.

## Files modified

- `~/.claude/settings.json` — Cozempic adds hook entries (`SessionStart`, `PostToolUse`, `PreCompact`, augments `Stop`)
- `~/.claude/settings.json.pre-cozempic.bak` — new, your manual rollback copy
- Possibly `~/.claude/cozempic.toml` or similar — Cozempic's own config (created by `init`)
- Python user site-packages — `cozempic` and dependencies

**Nothing in `c:\code\ADA` is modified.**

## Verification

End-to-end test:

1. Open a fresh ADA Claude Code session
2. Read at least 5 different files (e.g. `backend/main.py`, `backend/config.py`, `frontend/src/lib/axios.ts`, `docker-compose.yml`, `README.md`)
3. After the 5 reads, ask Claude: "How many `<system-reminder>` blocks about malware do you see in your context?" — answer should be **1 (or 0)**, not 5
4. Inspect the transcript on disk:

```bash
ls -lt ~/.claude/projects/c--code-ADA/*.jsonl | head -1
# pick the newest .jsonl
grep -c "consider whether it would be considered malware" ~/.claude/projects/c--code-ADA/<newest>.jsonl
```

Expected: **1**, not 5+. (Without Cozempic, an ADA session with 5 reads would have ≥5 occurrences.)

5. Confirm `~/.claude/settings.json` still contains the GSD verify gate and Telegram notify hooks
6. Run an existing GSD command (e.g. `/gsd:progress`) to confirm the GSD `Stop` hook still fires correctly
7. Check Cozempic's own diagnostic:

```bash
cozempic diagnose current -v
```

Expected: it reports duplicates removed > 0 and no errors

## Rollback

If anything misbehaves:

```bash
cp ~/.claude/settings.json.pre-cozempic.bak ~/.claude/settings.json
pip uninstall cozempic
```

Then restart Claude Code. You're back to the original state.

## Open risks

- **Third-party tool in your dev loop on a financial-trading project.** Cozempic only mutates `~/.claude/` transcripts and settings — it does not touch ADA code, env files, or secrets — but you should skim the Cozempic repo before installing, or pin to a specific version with `pip install --user cozempic==<version>`.
- **Anthropic could change the hook contract** in a future Claude Code release and break Cozempic. Rollback is one command.
- **The first Read of every session still ships the reminder.** Dedup means "keep one, drop the rest" — you save N-1 copies per session, not all N.
