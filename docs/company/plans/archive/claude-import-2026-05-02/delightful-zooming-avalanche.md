# TikTok-Style Carousel Preview + Inline Edit

## Context

The Character Content **Review Queue** currently shows carousels as a 2-3 column grid of slides with hook/caption/music listed inline. Reviewers cannot see what the post will actually look like on TikTok, and cannot edit any slide, caption, hook, or music directly from the review screen. This breaks the "approve a finished product" intent: approvals become guesses about how the content will render.

Goal: Make the review screen show each carousel as a realistic TikTok phone mockup (9:16 frame, swipeable slides, text overlay, spinning music disc, caption + hashtags) and flip into an inline edit mode so reviewers can correct text, regenerate images, swap music, and tweak caption/hashtags before approving. Music collection already exists (50 seeded tracks in `music_library_service.py`); we add a `preview_url` field now so audio playback can be enabled later without another migration.

## Approach

Build one new component, `TikTokPhonePreview`, that renders carousels as a phone-frame mockup in both read mode (default) and edit mode (toggled). Add a `MusicPickerModal` for browsing the existing library. Refactor `ReviewQueueTab` to two columns: preview on the left, AI review + action bar on the right. Add `preview_url` column to `music_tracks` for future audio.

## File Changes

### Backend (small, additive)

1. **`backend/app/migrations/versions/025_music_preview_url.py`** (new)
   - Alembic migration, `revision="025"`, `down_revision="024"`.
   - `op.add_column("music_tracks", sa.Column("preview_url", sa.Text, nullable=True))`.
   - Copy header shape from `024_character_autopilot.py`.

2. **`backend/app/db/models.py`** (edit `MusicTrackModel` ~line 1832)
   - Add `preview_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)`.

3. **`backend/app/models/character_content.py`** (edit `MusicTrack` L397, `MusicTrackCreate` L416)
   - Add `preview_url: Optional[str] = None`.

4. **`backend/app/services/music_library_service.py`** (edit serializer)
   - Include `preview_url` when mapping ORM to Pydantic. Do not seed values.

No router changes required; `response_model=MusicTrack` passes the new field through automatically.

### Frontend

5. **`frontend/src/hooks/useCharacterContentApi.ts`** (edit `MusicTrack` type)
   - Add `preview_url?: string | null`.

6. **`frontend/src/components/character-content/TikTokPhonePreview.tsx`** (new, core work)

   Props:
   ```ts
   interface TikTokPhonePreviewProps {
     carousel: CharacterCarousel
     editMode: boolean
     onChange?: (patch: Partial<CharacterCarousel>) => void
     onReimageSlide?: (slideIdx: number, newQuery?: string) => void
     onOpenMusicPicker?: () => void
     className?: string
   }
   ```

   Structure (TailwindCSS, dark theme):
   - Phone frame: `w-[320px] aspect-[9/16] rounded-[38px] border-[12px] border-gray-950 bg-black relative overflow-hidden shadow-2xl`.
   - Dynamic-island: `absolute top-2 left-1/2 -translate-x-1/2 w-28 h-7 bg-gray-950 rounded-full z-20`.
   - Horizontal slide track with `translateX(-activeSlide * 100%)`. Each slide fills viewport. Image as `absolute inset-0 object-cover` with top-to-bottom gradient for legibility.
   - Text overlays: hook on slide 1, per-slide text centered. Bold white, `drop-shadow-lg`. In edit mode swap `<span>` -> `<Textarea>` with `bg-black/50`.
   - Dots indicator top, active dot wider. If slides > 6, show `N/M` numeric.
   - Right rail (decorative): `lucide-react` `Heart`, `MessageCircle`, `Share2`, `Bookmark` with static plausible counts (dim in edit mode).
   - Bottom overlay: `@character_name`, caption (2-line clamp with "more"), hashtag chips inline.
   - Music row: spinning disc (`animate-[spin_4s_linear_infinite]` paused when not playing), marquee track name `name - artist`, play/pause button. If `preview_url` present, wire to `<audio ref={audioRef} loop />`. Else hide play button and show tooltip "Preview unavailable".
   - Swipe: hand-rolled pointer events (pointerdown/move/up, deltaX > 50 commits). No new npm package.

7. **`frontend/src/components/character-content/MusicPickerModal.tsx`** (new)

   Props: `{ open, onOpenChange, carouselId, currentTrackId?, onAssigned? }`.
   - shadcn `<Dialog>`, search `<Input>`, mood badges (epic/dark/emotional/mysterious/dramatic/hype/chill), trending toggle.
   - Uses existing `useMusicTracks(mood)` and `useTrendingMusic()`.
   - Row per track with `Assign` button calling `useAssignMusic.mutate({ id, track_id })`.
   - Empty state links to Studio Music tab.

8. **`frontend/src/pages/CharacterContentPage.tsx`** (refactor `ReviewQueueTab` L1465-1712)

   New layout per carousel: `grid md:grid-cols-[360px_1fr] gap-6`.

   Left: `<TikTokPhonePreview carousel={merged} editMode={editing===c.id} onChange={patch => setDraft(d => ({...d, ...patch}))} onReimageSlide={(idx,q) => reimage.mutate({id:c.id, slide_idx:idx, image_query:q})} onOpenMusicPicker={() => setMusicPicker(c.id)} />`

   Right: character header + status/auto-approval badges, existing AI review scores, generation metadata `<details>`, brain-context notice. Action bar:
   - Not editing: `Edit`, `Approve`, `Reject`.
   - Editing: `Save` (calls `useUpdateCarousel` with dirty `draft`), `Cancel` (discards `draft`).

   Edit state owned by `ReviewQueueTab`:
   ```ts
   const [editing, setEditing] = useState<string|null>(null)
   const [draft, setDraft] = useState<Partial<CharacterCarousel>>({})
   const update = useUpdateCarousel()
   const reimage = useReimageSlide()
   ```
   Only dirty keys land in `draft`; on Save, PATCH payload matches exactly.

   Remove the old inline grid + caption block (L1540-1580). Keep existing approve/reject mutations.

9. **`frontend/src/pages/CharacterContentPage.tsx`** (optional, `CarouselPreview` L1246-1423)
   - Replace inner grid with `<TikTokPhonePreview carousel={carousel} editMode={false} />` for visual consistency across Content Studio and Review Queue. Keep surrounding AI review + metadata.

10. **`frontend/tailwind.config.*`** (conditional)
    - If `marquee` + `spin-slow` keyframes missing, add:
      ```js
      keyframes: {
        marquee: {'0%':{transform:'translateX(0%)'},'100%':{transform:'translateX(-100%)'}}
      },
      animation: { marquee: 'marquee 8s linear infinite' }
      ```
    - Restart `zero-ui` if config changed.

### Tests

11. **`frontend/src/tests/character-content.test.tsx`** (edit)
    - Render `TikTokPhonePreview` with mock carousel, verify slide count + hook renders.
    - Toggle `editMode`, simulate textarea change, assert `onChange` receives matching patch.
    - Simulate pointer drag, assert activeSlide advances.

12. **`backend/tests/test_character_content.py`** (edit)
    - Assert `GET /music` response includes `preview_url` key (default null).

## Reused Utilities

- `useUpdateCarousel`, `useAssignMusic`, `useReimageSlide`, `useMusicTracks`, `useTrendingMusic`, `useReviewQueue`, `useSmartReviewQueue` in [frontend/src/hooks/useCharacterContentApi.ts](frontend/src/hooks/useCharacterContentApi.ts).
- shadcn components already in `frontend/src/components/ui/` (Dialog, Input, Textarea, Badge, Button).
- `lucide-react` icons already imported on the page.
- Alembic migration template from [backend/app/migrations/versions/024_character_autopilot.py](backend/app/migrations/versions/024_character_autopilot.py).

## Edge Cases

1. Zero slides - placeholder "No slides yet" + disable swipe.
2. Missing `image_url` - gradient fallback with character initial.
3. Long caption - 2-line clamp + "more" toggle (read), full textarea (edit).
4. Long hashtags - cap visible at 6, show `+N`.
5. No `music_track` - "No sound" row, "Pick music" enabled only in edit mode.
6. No `preview_url` - hide play button, tooltip on disc.
7. Empty music library - modal empty state links to Studio.
8. Reimage in flight - spinner over slide, disable further slide actions.
9. Save failure - toast error, keep `draft` and `editing` state intact.
10. Status change race during edit - show "Carousel moved to {status}. Discard or refresh?".
11. Accessibility: `aria-pressed` on edit toggle, labels on textareas, phone decorations `aria-hidden`.

## Verification

### Manual (primary)
1. Review Queue renders phone frame with first slide image full-bleed, hook overlay, right-rail icons, caption + hashtags, spinning music disc.
2. Click/drag to swipe slides 1 -> 2 -> 3 with dots updating.
3. Click `Edit`: textareas appear on slide text, hook, caption. Hashtag chips become editable. "Change music" button visible.
4. Change hook only. Click `Save`. Verify network panel shows PATCH with only `hook_text`. Queue refetches, new hook renders.
5. Open music picker, filter by "dark", assign track. Verify POST `/music`, disc updates.
6. Regenerate slide 2 image. Verify POST `/slides/1/reimage`, image refreshes.
7. Click `Cancel` on a fresh edit, verify draft discarded and original shown.
8. Approve and Reject flows unchanged on a non-edited carousel.
9. Test with carousels missing images, music, and with very long captions/hashtags.

### Automated
- Frontend: `docker exec zero-ui npm test -- character-content` covers new render and edit-dispatch tests.
- Backend: `docker exec zero-api pytest tests/test_character_content.py -k music` covers `preview_url` surface.

### Deployment
- Backend changes require rebuild:
  ```
  docker compose -f docker-compose.sprint.yml build --no-cache zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api
  ```
  Then run `docker exec zero-api alembic upgrade head`.
- Frontend `src/` is volume-mounted; no rebuild needed unless `tailwind.config` touched (then `docker compose restart zero-ui`).
- Verify health: `docker ps --format "table {{.Names}}\t{{.Status}}" | grep zero` shows `zero-api` and `zero-ui` healthy.

### Legion
Per CLAUDE.md: create Legion sprint "TikTok Preview UI" on project_id=8 with tasks (1) migration+Pydantic, (2) TikTokPhonePreview, (3) edit mode, (4) MusicPickerModal, (5) ReviewQueueTab refactor, (6) optional Studio refactor, (7) tests.

## Sequencing

1. Backend: migration + model + Pydantic + serializer. Rebuild zero-api, run alembic.
2. `TikTokPhonePreview` in read-only mode. Drop into `CarouselPreview` first to validate visuals before touching Review Queue.
3. Edit-mode internals (dirty buffer, textareas, regenerate overlays).
4. `MusicPickerModal` wired to hooks.
5. Refactor `ReviewQueueTab` to two-column layout with Edit/Save/Cancel action bar.
6. Tests. Legion task closeout.

## Out of Scope

- Actual audio file uploads or sourcing (just the schema field). A later task can add a small audio upload endpoint or scrape previews from free libraries.
- Drag-to-reorder slides (API supports ordered slides, but UI gesture is deferred).
- Rich-text caption editor (markdown/formatting). Plain textarea for now.
- A/B caption variants generator (separate feature).
