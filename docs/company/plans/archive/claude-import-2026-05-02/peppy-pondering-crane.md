# Fix Missing Slash Commands: zero-brain & character-content

## Context
After restarting Claude Code, only `/zero-deep-review` appears as a slash command. The `zero-brain` and `character-content` skills are missing from the slash command list because they're stored as standalone `.md` files (`.claude/skills/zero-brain.md`, `.claude/skills/character-content.md`) instead of the proper skill directory format that Claude Code requires.

The working skill (`zero-deep-review`) uses the correct structure: `.claude/skills/zero-deep-review/SKILL.md`.

## Plan

### Step 1: Convert `zero-brain` to proper skill format
1. Create directory `.claude/skills/zero-brain/`
2. Move content from `.claude/skills/zero-brain.md` → `.claude/skills/zero-brain/SKILL.md`
3. Ensure the header starts with `# /zero-brain` (slash prefix required for slash command recognition)
4. Delete the old `.claude/skills/zero-brain.md` file

### Step 2: Convert `character-content` to proper skill format
1. Create directory `.claude/skills/character-content/`
2. Move content from `.claude/skills/character-content.md` → `.claude/skills/character-content/SKILL.md`
3. Ensure the header starts with `# /character-content` (slash prefix required)
4. Delete the old `.claude/skills/character-content.md` file

### Step 3: Verify
- Restart Claude Code or check that `/zero-brain` and `/character-content` now appear in the slash command list alongside `/zero-deep-review`

## Files to modify
- `.claude/skills/zero-brain.md` → `.claude/skills/zero-brain/SKILL.md`
- `.claude/skills/character-content.md` → `.claude/skills/character-content/SKILL.md`
