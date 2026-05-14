---
name: zero-frontend
type: rules
triggers: [react, frontend, vite, tailwind, tsx, shadcn, typescript, zustand, react query]
agent: any
---

Zero's frontend conventions:

- React 19 + Vite + TypeScript strict (no `any`).
- Function components + hooks only, no class components.
- Tailwind utility-first; dark theme (`bg-gray-900`, indigo accent).
- shadcn/ui in `src/components/ui/`. Reuse before adding new.
- React Query key factory for cache; Zustand for global state.
- Realtime voice state is shared via `useSharedRealtimeVoice()` —
  always pull from context, never instantiate a new `useRealtimeVoice`
  in a child component.
- Run `npx tsc --noEmit -p tsconfig.json` before pushing.
