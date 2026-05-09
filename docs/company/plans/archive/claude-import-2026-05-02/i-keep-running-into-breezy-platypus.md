# Stop Permission Prompts for .md Files and Skills - Multi-Project Configuration

## Context

The user is experiencing constant permission prompts when trying to edit .md files and update skills across multiple projects (Legion, ADA, Zero), even after saying "yes" and bypassing permissions. This happens because:

1. **Permission Hierarchy**: Project-level `.claude/settings.json` files override user-level permissions
2. **Restrictive Project Settings**: Projects have very restrictive settings that only allow specific skill paths
3. **Granular Permissions**: User has 95+ explicit skill permissions but lacks broader wildcard patterns
4. **Multi-Project Issue**: Each project (Legion, ADA, Zero) has its own restrictive settings

## Root Cause Analysis

From investigation of the permission configuration:

- **User-level settings** (`/c/Users/hadam/.claude/settings.json`): Has 95+ explicit skill permissions but missing broad patterns
- **Project-level settings**: 
  - ADA (`/c/code/ada/.claude/settings.json`): Very restrictive, only allows `Edit(/.claude/skills/advisor-audit/**)`
  - Legion (`/c/code/Legion/.claude/settings.json`): Minimal, only allows `Edit(/.claude/skills/legion-sprint-auditor/**)`
  - Zero (`/c/code/zero/.claude/settings.json`): More permissive but still limited
- **Permission hierarchy**: Project settings override user settings, which is why "bypass permissions" doesn't work

## Solution: Comprehensive Multi-Level Permission Configuration

Configure permissions at both global and project levels to ensure broad access across all projects and use cases.

### Target Files

**1. Global User-Level Settings:**
- **Location**: `/c/Users/hadam/.claude/settings.json`
- **Purpose**: Override all project restrictions globally

**2. Project-Level Settings:**
- **ADA**: `/c/code/ada/.claude/settings.json`
- **Legion**: `/c/code/Legion/.claude/settings.json` 
- **Zero**: `/c/code/zero/.claude/settings.json`
- **Purpose**: Ensure each project allows broad permissions

### Permission Patterns to Add

**For .md file editing everywhere:**
```json
"Edit(/**/*.md)",
"Write(/**/*.md)",
"Read(/**/*.md)"
```

**For skill updates in all projects:**
```json
"Edit(/.claude/skills/**)",
"Write(/.claude/skills/**)",
"Read(/.claude/skills/**)",
"Edit(//c/code/**/.claude/skills/**)",
"Write(//c/code/**/.claude/skills/**)"
```

**For broader .claude directory access:**
```json
"Edit(/.claude/**)",
"Write(/.claude/**)",
"Read(/.claude/**)"
```

**For memory and configuration files:**
```json
"Edit(/.claude/memory/**)",
"Write(/.claude/memory/**)",
"Read(/.claude/memory/**)",
"Edit(/.claude/settings.json)",
"Write(/.claude/settings.json)",
"Edit(/.claude/settings.local.json)",
"Write(/.claude/settings.local.json)"
```

## Implementation Steps

1. **Update Global User Settings** - Add broad patterns to override all project restrictions
2. **Update ADA Project Settings** - Replace restrictive rules with broad permissions
3. **Update Legion Project Settings** - Replace restrictive rules with broad permissions  
4. **Update Zero Project Settings** - Enhance existing permissions with broader patterns
5. **Test across all projects** - Verify .md and skill editing works without prompts

## Expected Outcome

- **No permission prompts** for .md file edits anywhere across all projects
- **No permission prompts** for skill updates in Legion, ADA, Zero, or any other project
- **Broad patterns at global level** will override restrictive project-level settings
- **Project-level permissions** will also allow broad access as a fallback
- **User maintains** all existing explicit permissions (95+ skill permissions preserved)

## Verification Plan

**Global Level Testing:**
1. Edit an .md file in ADA project - should not prompt
2. Edit an .md file in Legion project - should not prompt
3. Edit an .md file in Zero project - should not prompt
4. Update a skill file in any project - should not prompt

**Project-Specific Testing:**
1. **ADA**: Edit advisor-audit skill AND any other skill - both should work
2. **Legion**: Edit legion-sprint-auditor skill AND any other skill - both should work  
3. **Zero**: Verify existing broad permissions still work + new patterns work
4. **Cross-project**: Edit memory files, settings files across all projects

**Fallback Testing:**
1. Test with global settings temporarily disabled - project settings should still allow access
2. Verify existing 95+ explicit permissions still work as before

## Files to Modify

**1. Global Configuration:**
- `/c/Users/hadam/.claude/settings.json` - Add comprehensive broad permission patterns

**2. Project Configurations:**
- `/c/code/ada/.claude/settings.json` - Replace restrictive with broad patterns
- `/c/code/Legion/.claude/settings.json` - Replace minimal with broad patterns
- `/c/code/zero/.claude/settings.json` - Enhance existing with additional patterns

## Technical Details

**Permission Rule Syntax:**
- `Edit(/**/*.md)` - wildcard for all .md files anywhere
- `Edit(/.claude/skills/**)` - wildcard for all skill files
- `Edit(//c/code/**/.claude/skills/**)` - absolute Windows paths with double slash
- `Edit(/.claude/**)` - complete .claude directory access

**Configuration Strategy:**
1. **Global Override**: User-level settings with maximum broad patterns
2. **Project Fallback**: Each project gets its own broad patterns  
3. **Defensive Redundancy**: Multiple pattern variations to ensure coverage
4. **Preservation**: All existing permissions maintained during merge

**Permission Hierarchy Benefits:**
- Global patterns override project restrictions
- Project patterns provide fallback if global fails
- Both levels ensure no permission prompts across all scenarios