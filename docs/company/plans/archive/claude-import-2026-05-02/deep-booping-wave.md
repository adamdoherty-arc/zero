# Fix: Character Content Page Infinite Spinner

## Context

The Character Content page is stuck on an infinite loading spinner. Backend logs show **401 Unauthorized** on all `/api/characters/` requests. The auth mechanism is shared across all routers (`ZERO_GATEWAY_TOKEN` Bearer token), so this likely affects every API-dependent page, not just Character Content.

The frontend has no auth guard - pages render without checking auth state. When API calls fail with 401, React Query retries 3 times then shows an error, but during retries the user sees an infinite spinner.

There's also a secondary filter bug: "All Universes" sends `?universe=all` which matches no characters.

## Fixes

### 1. Verify and fix auth token (root cause)

Check if `ZERO_GATEWAY_TOKEN` is set correctly in the running container and that it matches what's in the browser's localStorage. If the container was recently rebuilt, the token may have changed.

- Run: `docker exec zero-api printenv ZERO_GATEWAY_TOKEN` to verify the env var is set
- If not set or empty, check `.env` file and `docker-compose.sprint.yml` env config

### 2. Fix "All Universes" filter bug

**File**: `frontend/src/pages/CharacterContentPage.tsx`

Line 190-192: When `universeFilter` is `"all"`, it passes `{ universe: "all" }` to the hook, which filters for a non-existent universe.

**Fix**: Treat `"all"` as no filter:
```tsx
// Before (line 191-192):
const { data: characters, isLoading, isError, error, refetch } = useCharacters(
  universeFilter ? { universe: universeFilter } : undefined
)

// After:
const { data: characters, isLoading, isError, error, refetch } = useCharacters(
  universeFilter && universeFilter !== 'all' ? { universe: universeFilter } : undefined
)
```

### 3. Add global 401 handler to redirect to login

**File**: `frontend/src/hooks/useCharacterContentApi.ts` (and ideally a shared fetch utility)

The `fetchApi` function (line 277-291) throws on 401 but React Query retries it. Add a check: if 401, clear the stale token and redirect to `/login`.

Better approach - add to the global React Query config in `frontend/src/main.tsx`:
```tsx
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        // Don't retry auth failures
        if (error instanceof Error && error.message.includes('401')) return false
        return failureCount < 3
      },
    },
  },
})
```

This prevents the infinite-spinner-during-retries problem for auth errors.

## Files to modify

1. `frontend/src/pages/CharacterContentPage.tsx` - fix "all" universe filter (line 191-192)
2. `frontend/src/main.tsx` - add retry filter for 401 errors (line 7-14)
3. Verify `.env` has `ZERO_GATEWAY_TOKEN` set and container receives it

## Verification

1. Check `docker exec zero-api printenv ZERO_GATEWAY_TOKEN` returns a value
2. Verify browser localStorage has matching token (`localStorage.getItem('zero_api_token')`)
3. Navigate to Character Content page - should show characters or "No characters yet" (not spinner)
4. Select "All Universes" filter - should show all characters, not empty
5. Check another page (e.g., Dashboard) to confirm API calls work
