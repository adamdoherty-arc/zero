---
paths: ["frontend/**"]
---

# Frontend-only patterns

These rules apply when editing files under `frontend/`.

## Functional components only

No class components. Hooks for state, effects, refs. If you see a class component in legacy code, refactor on touch.

```tsx
// Good
export function SprintCard({ sprint }: { sprint: Sprint }) {
  const { mutate } = useMoveSprint();
  return <div className="bg-gray-900 p-4 ...">{sprint.name}</div>;
}
```

## React Query — key factory pattern

Centralize query keys in a factory module so cache invalidation is mechanical:

```ts
export const sprintKeys = {
  all: ['sprints'] as const,
  detail: (id: number) => ['sprints', id] as const,
  list: (filters: Filters) => ['sprints', 'list', filters] as const,
};

// invalidate everything sprint-related
qc.invalidateQueries({ queryKey: sprintKeys.all });
```

Never inline a query key string in two places.

## Zustand for global state

Zustand stores hold global state: sprints, tasks, board, loading. Each store is a single file with typed actions. React Query handles server state; Zustand handles ephemeral UI state. Don't store fetched data in Zustand — that's React Query's job.

## TypeScript strict

`tsconfig.json` runs in strict mode. **No `any` types.** If a third-party library is untyped, write a `.d.ts` shim in `frontend/src/types/`.

## TailwindCSS — dark theme

Utility-first. Project palette is dark: `bg-gray-900` as base, indigo accent for primary actions. Don't introduce new accent colors without checking the design system.

```tsx
<button className="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded">
  Start sprint
</button>
```

## shadcn/ui component library

Reusable primitives live in `src/components/ui/`. Use them before reaching for a third-party library. If you need a new primitive, add it to `src/components/ui/` and document the variant API.

## API access

REST + PATCH (partial updates) + POST (state transitions). Sprint state changes go through:
- `POST /api/sprints` (create)
- `POST /api/sprints/{id}/tasks` (add task)
- `POST /api/sprints/tasks/{tid}/move` (state transition)
- `POST /api/sprints/{id}/complete` (with retrospective payload)

All Sprint writes proxy to Legion at `host.docker.internal:8005`, `project_id=7`.

## Mobile PWA

Mobile routes at `/m/*`. Layout in `frontend/src/layouts/MobileLayout.tsx`. Service worker in `frontend/src/sw.ts` (hand-authored `injectManifest`). Share Target at `/share` consumes Android share-sheet POSTs. Guide: `docs/mobile-pwa.md`.
