---
description: "[Alias of /supervise] Run one Zero Supervisor lifecycle. Project pre-bound to zero. Pass focus as $ARGUMENTS."
argument-hint: [optional focus, e.g. "Meeting Steward consent edge cases + Stage-2 cyanheads MCP wiring"]
---

This command is now a thin **alias** of the unified `/supervise` skill
(`~/.claude/commands/supervise.md`), with the project pre-bound to **zero**.
The full 6-phase protocol lives once in the unified command; Zero's specifics
(ports, vault constitution, approval ladder, robot-off-safe rule, 8 cognition
loops, Kimi temp=1, event envelope) are fetched live from Legion's
`supervisor_profiles` registry.

Execute the unified Supervisor protocol with:
- **project slug** = `zero`
- **focus** = $ARGUMENTS

Begin bootstrap now:
1. `curl -s http://localhost:8005/api/supervisor/profile/zero` → store the profile.
   (The registry always lives in Legion on :8005, even though you supervise Zero.)
2. POST run start to the Zero surface at the profile's `base_url`
   (`/api/zero/run/start`); emit every event with the profile's
   `event_contract.envelope_fields` (robot_state, dnd, partition,
   approval_record_id, vault_audit_id, salience, delegation_target,
   legion_sprint_id).
3. Run EVERY `preflight_checks` entry (vault_constitution, approval_ladder,
   hardware_safe) before any write.
4. Follow every phase exactly as in `~/.claude/commands/supervise.md`. The
   profile's `constraints` are HARD rules — vault constitution non-negotiable,
   approval ladder (write_external=interrupt, financial=route to ADA),
   robot-off-safe (function with Reachy daemon OFF), never touch 'work'
   partition, Kimi temperature=1. A violation is an immediate STOP. Read
   `~/.claude/commands/supervise.md` for the full phase definitions if needed.
