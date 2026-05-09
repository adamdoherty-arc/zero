# Fix SprintDetailDialog Scrolling & Improve Error Details

## Context
The SprintDetailDialog (sprint detail popup) has broken scrolling — content clips at the bottom of the viewport instead of scrolling. Additionally, `<pre>` blocks for Task Instructions, Error Details, and Completion Notes clip content without scroll. Error details show minimal context. These issues make it impossible to review sprint task failures effectively.

## Root Cause
The `ScrollArea` component (Radix UI wrapper) uses `relative overflow-hidden` on its root, but **lacks `min-h-0`**. In a flex column container (like the dialog), flex items default to `min-height: auto` (intrinsic content size), preventing the ScrollArea from shrinking below its content. The viewport's `overflow-y: scroll` never activates because the container expands to fit all content instead.

## Changes

### 1. Fix ScrollArea flex shrinking — `frontend/src/components/ui/scroll-area.tsx` (line 12)
Add `min-h-0` to the ScrollArea root default classes. This allows ScrollArea to shrink below its content height in flex containers, enabling the viewport's internal `overflow-y: scroll` to activate.

```diff
- className={cn("relative overflow-hidden", className)}
+ className={cn("relative overflow-hidden min-h-0", className)}
```

**Impact**: Fixes scrolling in ALL dialogs using `ScrollArea` with `flex-1` — SprintDetailDialog, ErrorAnalysisDialog, AskAIDialog, etc. Safe in non-flex contexts since `min-height: 0` is already the default for non-flex items.

### 2. Fix `<pre>` element clipping — `frontend/src/components/sprint/SprintDetailDialog.tsx`

Three `<pre>` elements have `max-h-*` without `overflow-y-auto`, causing content to clip silently.

**Line 280 — Task Instructions:**
```diff
- <pre className="... max-h-32 whitespace-pre-wrap break-words">
+ <pre className="... max-h-48 overflow-y-auto whitespace-pre-wrap break-words">
```

**Line 346 — Completion Notes:**
```diff
- <pre className="... max-h-48 whitespace-pre-wrap break-words">
+ <pre className="... max-h-48 overflow-y-auto whitespace-pre-wrap break-words">
```

**Line 380 — Error Details:**
```diff
- <pre className="... max-h-32 whitespace-pre-wrap break-words">
+ <pre className="... max-h-48 overflow-y-auto whitespace-pre-wrap break-words">
```

Error details increased from `max-h-32` (128px) to `max-h-48` (192px) to show more error context.

### 3. Add execution context to error section — `SprintDetailDialog.tsx` (after line 381)

Insert execution context badges (model, duration, attempt count) inside the error section so users see failure context without scrolling to the execution details section above:

```tsx
{/* Error execution context */}
{(task.execution_model || task.execution_duration || task.retry_count) && (
    <div className="flex flex-wrap gap-2 text-xs">
        {task.execution_model && (
            <Badge variant="outline" className="text-xs border-red-500/30 text-red-300">
                <Cpu className="w-3 h-3 mr-1" /> {task.execution_model}
            </Badge>
        )}
        {task.execution_duration && (
            <Badge variant="outline" className="text-xs border-red-500/30 text-red-300">
                <Clock className="w-3 h-3 mr-1" /> {task.execution_duration.toFixed(1)}s
            </Badge>
        )}
        {task.retry_count !== undefined && task.retry_count > 0 && (
            <Badge variant="outline" className="text-xs border-orange-500/30 text-orange-300">
                <RefreshCw className="w-3 h-3 mr-1" /> Attempt {task.retry_count + 1}
            </Badge>
        )}
    </div>
)}
```

### 4. Fix ErrorAnalysisPanel `<pre>` clipping — `frontend/src/components/ErrorAnalysisPanel.tsx` (line 302)

```diff
- <pre className="... overflow-x-auto whitespace-pre-wrap max-h-32">
+ <pre className="... overflow-x-auto overflow-y-auto whitespace-pre-wrap max-h-48">
```

### 5. Extend SprintCenter page object — `tests/e2e/page-objects/sprint-center.po.ts`

Add dialog interaction methods:
- `openSprintDetail(index)` — click sprint card, wait for dialog
- `isDialogScrollable()` — check if viewport scrollHeight > clientHeight
- `scrollDialog(deltaY)` — programmatic scroll
- `getDialogScrollTop()` — read scroll position
- `closeDialog()` — press Escape, wait for hidden
- `getTaskCards()` — locator for task cards inside dialog
- `expandTask(index)` — click a task card to expand
- `preElementsAreScrollable()` — verify `<pre>` elements have `overflow-y: auto`

### 6. Add E2E tests — `tests/e2e/functional/sprint-center.func.spec.ts`

New test cases (appended to existing describe block):
- **dialog scrollable**: Opens sprint detail, verifies ScrollArea viewport is scrollable when content overflows, verifies scroll position changes
- **task expand/collapse**: Opens dialog, clicks task card, checks expanded content visible, clicks again to collapse
- **dialog closes via Escape**: Opens dialog, presses Escape, dialog hidden
- **retry button visible for failed tasks**: Opens dialog, checks retry button existence
- **pre elements scrollable**: Expands a task, verifies all `<pre>` elements have `overflow-y: auto`

All tests use defensive `.catch(() => false)` + early returns matching existing patterns.

## Files Modified
| File | Change |
|------|--------|
| `frontend/src/components/ui/scroll-area.tsx` | Add `min-h-0` to root (1 line) |
| `frontend/src/components/sprint/SprintDetailDialog.tsx` | `overflow-y-auto` on 3 `<pre>` elements, increase error `max-h`, add error context badges |
| `frontend/src/components/ErrorAnalysisPanel.tsx` | `overflow-y-auto` + `max-h-48` on error `<pre>` |
| `tests/e2e/page-objects/sprint-center.po.ts` | Extend PO with dialog scroll/interaction methods |
| `tests/e2e/functional/sprint-center.func.spec.ts` | Add 5 new E2E test cases |

## Verification
1. `cd frontend && npm run build` — TypeScript compiles cleanly
2. `cd frontend && npx vitest run` — existing component tests pass
3. `npx playwright test tests/e2e/functional/sprint-center.func.spec.ts` — E2E tests pass
4. Manual: Open sprint detail dialog → content scrolls, task expand works, error details show full text with model/duration context
