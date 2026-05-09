# Fix-54: Make Dependency Upgrades Self-Sufficient (No LLM Fallback)

## Context

Legion's Deps sprints succeed 100% for Zero PA (38 test files) but 0-17% for ADA (442 test files) and Legion. The failure chain:

1. Script executor upgrades package via `pip install` → runs full `pytest` → tests fail (pre-existing failures or timeout on large suite)
2. Script executor sets `should_fallback_to_llm=True` → task sent to LLM coder
3. LLM coder (`execute_llm_task`) is text-in/text-out with **no file system access** — it produces text like "here's how to upgrade pip" that is never applied to disk
4. Swarm cycles through critique → test → diagnose → retry × 6 attempts ≈ 30 min → stuck task recovery kills it

**Root cause**: The LLM fallback path is fundamentally useless for dep upgrades. The LLM cannot run `pip install` or edit files. Every second spent in the LLM path is wasted.

## Changes

### File 1: `backend/app/services/script_executor.py`

**Change A — Replace full pytest with import verification (lines 216-249)**

Delete the entire test-running block (lines 216-249) and replace with import verification:
- For each successfully upgraded pip package, run `python -c "import {import_name}"` (15s timeout)
- If all imports pass → `success=True` (task complete, no LLM needed)
- If any import fails → `success=False, should_fallback_to_llm=False` (fail cleanly)
- For npm packages, skip import check (npm install already validates)

**Change B — Add `_pip_to_import_name()` helper (after `_upgrade_npm`, ~line 358)**

Static method to convert pip package names to Python import names. Handles ~15 common renames (protobuf→google.protobuf, pillow→PIL, pyyaml→yaml, etc.) with a default fallback of lowercase + hyphens→underscores.

**Change C — Remove LLM fallback from ALL dep upgrade failure paths**

- Line 163: `should_fallback_to_llm=True` → `False` (no dep files found)
- Line 177: `should_fallback_to_llm=True` → `False` (batch parse empty)
- Line 213: `should_fallback_to_llm=True` → `False` (all pip installs failed)

The LLM cannot run pip, cannot create dep files, cannot parse package lists. Failing cleanly is better than a 30-minute death loop.

### File 2: `backend/tests/services/test_script_executor.py`

Update existing tests that assert `should_fallback_to_llm is True`:
- `test_no_package_manager_falls_back` (line 72): assert `False`
- `test_pip_install_fails_skips_tests` (line 155): assert `False`
- `test_pip_upgrade_tests_fail_falls_back` (line 161): Rewrite as `test_pip_upgrade_import_failure` — mock pip success + import failure → `success=False, should_fallback_to_llm=False`
- `test_pip_upgrade_success` (line 76): Update mock side_effect — now pip install + import check (not pytest)
- `test_transitive_dep_success` (line 97): Same mock update
- `test_pyproject_toml_pin_updated` (line 118): Same mock update
- `test_batch_upgrade_parses_prompt` (line 180): Update mock — now N pip installs + N imports (not N pip installs + 1 pytest)
- `test_routes_to_matching_executor` (line 320): assert `should_fallback_to_llm is False`

Add new tests:
- `test_pip_to_import_name_known_renames` — verify protobuf, pillow, pyyaml mappings
- `test_pip_to_import_name_default` — verify hyphen-to-underscore default
- `test_pip_upgrade_import_success` — pip ok + import ok → success=True
- `test_npm_upgrade_skips_import_check` — npm path doesn't run python import

## Verification

1. Run updated tests: `cd backend && python -m pytest tests/services/test_script_executor.py -v`
2. Rebuild backend: `docker-compose build legion-backend && docker-compose up -d legion-backend`
3. Check logs for next Deps sprint execution — should see "imports verified" not "tests failed — falling back to LLM"
4. Check Prometheus: `legion_script_executor_total{result="success"}` should increment, `result="fallback_to_llm"` should NOT increment for dep upgrades
