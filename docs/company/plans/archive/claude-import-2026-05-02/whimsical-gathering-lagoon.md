# Plan: Add Strategy Hub to Sidebar Navigation

## Context
The Overkill Bounce Scanner was just built and lives as a tab in the Strategy Scanner Hub page (`/strategy-hub`). However, `/strategy-hub` has **no entry in the sidebar navigation**, making it unreachable from the left nav.

## Change

**File**: [Sidebar.tsx](frontend/src/components/Sidebar.tsx)

1. **Add import**: Add `Crosshair` to the lucide-react imports (line 1-11)
2. **Add nav item**: Insert after the "Premiums" entry (line 39):
   ```tsx
   { to: '/strategy-hub', icon: Crosshair, label: 'Strategy Hub', highlight: true },
   ```

That's it - single file, two-line change.

## Verification
1. Vite hot-reload should pick it up automatically
2. Confirm "Strategy Hub" with Crosshair icon appears in sidebar after "Premiums"
3. Click it - navigates to `/strategy-hub`
4. Confirm the "Overkill" tab is accessible there
