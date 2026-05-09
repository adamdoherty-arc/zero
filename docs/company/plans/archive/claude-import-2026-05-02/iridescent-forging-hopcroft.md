# Plan: Remove Em Dashes and Fix AI-Sounding English

## Context
The em dash character (`---`) is overused across memory and config files, a telltale sign of AI-generated text. The user wants all instances replaced with proper English punctuation (periods, commas, semicolons, parentheses, or hyphens as appropriate). No new em dashes should be introduced going forward.

## Scope
4 files, 18 total em dash instances to fix:

### 1. `CLAUDE.md` (1 instance)
- **Line 39**: `volume-mounted --- code changes are live` -> rewrite with period or semicolon

### 2. `MEMORY.md` (14 instances)
- **Line 4**: `audit --- 20 features` -> use colon or period
- **Line 5**: `(D)** --- dragged down` -> use period or comma
- **Line 25**: `config` --- all 4 new` -> use period
- **Line 27**: `.md` --- full 7-phase` -> use colon or dash
- **Line 30**: `DailyMeetings` --- standalone` -> use colon or dash
- **Line 41**: `<pid>` --- uvicorn reload` -> use period
- **Line 60**: `needed --- uses local` -> use period or semicolon
- **Line 85**: `json` --- delete + restart` -> use period
- **Line 88**: `zero-api`) --- 33 routers` -> use hyphen or colon
- **Line 89**: `zero-ui`) --- 30 pages` -> use hyphen or colon
- **Line 90**: `host-only) --- meeting recording` -> use hyphen or colon
- **Line 119**: `context manager --- use` -> use period or semicolon
- **Line 122**: `ALL volumes --- use` -> use period or semicolon

### 3. `session-2026-03-08.md` (1 instance)
- **Line 34**: `json` --- must delete` -> use period

### 4. `module-map.md` (3 instances)
- **Line 3**: `routers/) --- 33 routers` -> use hyphen or colon
- **Line 36**: `pages/) --- 30 pages` -> use hyphen or colon
- **Line 43**: `hooks/) --- 22 hooks` -> use hyphen or colon

## Replacement Strategy
Each instance will be replaced with the most natural English punctuation for its context:
- **Joining two independent clauses**: use a period or semicolon
- **Adding a count/detail after a heading**: use a colon or hyphen
- **Appending clarifying info**: use a comma or parentheses

## Verification
After edits, grep all 4 files for the em dash Unicode character (U+2014) to confirm zero remaining instances.

## Future Prevention
Add a note to MEMORY.md reminding against em dash usage in all files.
