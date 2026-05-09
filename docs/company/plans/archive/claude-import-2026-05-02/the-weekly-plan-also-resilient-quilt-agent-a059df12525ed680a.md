# LLM Configuration Issues Fix Plan

## Issue Summary

The ADA trading platform has stale LLM configuration references and misleading documentation. While the actual routing table in `llm_router.py` correctly uses "kimi-k2.6" and "minimax-m2.7", several areas still reference the old "kimi-k2.5" model or have misleading comments about routing behavior.

### Key Problems Identified:
1. **Stale References**: "kimi-k2.5" appears in 7 files (tests, docs, audit history)
2. **Misleading Comments**: Comments in `llm_router.py` reference "Kimi K2.5" instead of "Kimi K2.6"
3. **Fallback Logic Confusion**: Comment suggests fallback to "Kimi K2.5" but actual fallback is "minimax-m2.7"
4. **Provider Detection Gap**: Missing Kimi model handling in provider detection logic

## Critical Files Analysis

### Backend Infrastructure Files

#### `c:\code\ADA\backend\infrastructure\llm_router.py`
- **Line 16**: Comment states "Kimi K2.5 Cloud API" - should be "Kimi K2.6 Cloud API"
- **Line 602**: Comment references "Kimi K2.5" - should be "Kimi K2.6"
- **Lines 634-635**: Fallback logic comment misleading (actual fallback is MiniMax M2.7)
- **Line 1104**: Provider detection missing Kimi model check (only checks MINIMAX_MODELS)
- **Line 1432-1433**: Stats suggest "minimax=planning" but planning actually uses "kimi-k2.6" first

#### `c:\code\ADA\backend\services\trade_advisor_service.py`
- **Line 1659**: Comment states "Attempt 1: MiniMax M2.7 (primary cloud)" but Kimi K2.6 is actually primary for planning

### Test Files

#### `c:\code\ADA\backend\tests\test_ada_brain_service.py`
- **Lines 90, 1064, 2476**: Model references "kimi-k2.5" in test data

#### `c:\code\ADA\backend\tests\test_trade_advisor_service.py`
- **Line 924**: Model reference "kimi-k2.5" in test data

#### `c:\code\ADA\backend\tests\test_trade_advisor.py`
- **Line 83**: Model reference "kimi-k2.5" in test data

### Documentation Files

#### `c:\code\ADA\docs\obsidian\3-LLM-System\Task Types & Models.md`
- **Line 76**: References "kimi-k2.5" instead of "kimi-k2.6"
- **Lines 210, 212**: Multiple references to "kimi-k2.5"

#### `c:\code\ADA\docs\obsidian\3-LLM-System\Kimi K2.5 Cloud.md`
- **Title and content**: Entire file references old K2.5 model
- **Lines 33, 34, 53, 59, 124, 176, 255, 256, 262**: Multiple "kimi-k2.5" references

#### `c:\code\ADA\docs\obsidian\3-LLM-System\Concurrency Control.md`
- **Line 220**: Reference to "kimi-k2.5"

#### `c:\code\ADA\.claude\skills\advisor-audit\knowledge\audit_history.json`
- **Line 558**: Audit history contains "kimi-k2.5" reference

## Implementation Plan

### Phase 1: Core Infrastructure Updates

#### 1.1 Update `llm_router.py` Comments
- [ ] **Line 16**: Change "Kimi K2.5 Cloud API" → "Kimi K2.6 Cloud API"
- [ ] **Line 602**: Change "Kimi K2.5" → "Kimi K2.6" in comment
- [ ] **Line 1432**: Update cloud provider stats to reflect actual routing: "kimi-k2.6=planning, minimax-m2.7=fallback"
- [ ] **Line 1433**: Update routing architecture description

#### 1.2 Fix Provider Detection Logic
- [ ] **Line 1104**: Add Kimi model check to provider detection:
  ```python
  provider = (
      AIProvider.KIMI if model_name in KIMI_MODELS or model_name in KIMI_MODELS.values()
      else AIProvider.MINIMAX if is_cloud or model_name in MINIMAX_MODELS or model_name in MINIMAX_MODELS.values()
      else AIProvider.OLLAMA
  )
  ```

#### 1.3 Update `trade_advisor_service.py` Comments
- [ ] **Line 1659**: Change comment to reflect Kimi K2.6 as primary for planning

### Phase 2: Test File Updates

#### 2.1 Update Test Data References
- [ ] `test_ada_brain_service.py` lines 90, 1064, 2476: "kimi-k2.5" → "kimi-k2.6"
- [ ] `test_trade_advisor_service.py` line 924: "kimi-k2.5" → "kimi-k2.6"
- [ ] `test_trade_advisor.py` line 83: "kimi-k2.5" → "kimi-k2.6"

### Phase 3: Documentation Updates

#### 3.1 Update Task Types & Models Documentation
- [ ] **File**: `docs\obsidian\3-LLM-System\Task Types & Models.md`
- [ ] Line 76: Update planning task primary model to "kimi-k2.6"
- [ ] Lines 210, 212: Update cloud model references

#### 3.2 Rename and Update Kimi Documentation
- [ ] **Rename**: `Kimi K2.5 Cloud.md` → `Kimi K2.6 Cloud.md`
- [ ] Update all internal references from K2.5 to K2.6
- [ ] Update pricing information if changed
- [ ] Update model specifications and capabilities

#### 3.3 Update Concurrency Control Documentation
- [ ] **File**: `docs\obsidian\3-LLM-System\Concurrency Control.md`
- [ ] Line 220: Update cloud provider reference to "kimi-k2.6"

### Phase 4: Audit and Configuration Files

#### 4.1 Update Audit History
- [ ] **File**: `.claude\skills\advisor-audit\knowledge\audit_history.json`
- [ ] Update LLM health reference to current model version

### Phase 5: Verification Steps

#### 5.1 Code Verification
- [ ] Search entire codebase for remaining "kimi-k2.5" references
- [ ] Verify routing table configuration matches intended behavior
- [ ] Test that PLANNING tasks route to Kimi K2.6 first, then MiniMax M2.7

#### 5.2 Integration Testing
- [ ] Run trade advisor tests with updated model references
- [ ] Verify ADA brain service tests pass with corrected model names
- [ ] Test actual routing behavior in development environment

#### 5.3 Documentation Review
- [ ] Ensure all LLM documentation consistently references current models
- [ ] Verify routing architecture diagrams match actual implementation
- [ ] Update any additional references found during review

## Risk Assessment

### Low Risk Changes
- Comment updates in source files
- Test data model name updates
- Documentation updates

### Medium Risk Changes  
- Provider detection logic updates (requires careful testing)
- Audit history updates (may affect monitoring)

### Verification Requirements
- All changes should maintain backward compatibility
- Test suite must pass with updated model references
- Actual routing behavior should remain unchanged (only documentation/comments updated)

## Success Criteria

1. **Zero "kimi-k2.5" references** remain in codebase
2. **Comments accurately reflect** actual routing behavior
3. **Provider detection correctly identifies** Kimi models
4. **Documentation consistently references** current model versions
5. **All tests pass** with updated model references
6. **Actual routing behavior unchanged** - only fixing documentation/comments

## Implementation Notes

- This is primarily a documentation and consistency fix
- The actual routing table in `ROUTING_TABLE` is already correct
- Focus is on bringing comments, tests, and documentation in sync with reality
- No changes to actual LLM routing logic should be needed
