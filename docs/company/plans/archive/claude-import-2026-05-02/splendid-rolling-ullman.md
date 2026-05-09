# Ideas Tab - Content Theme Organization

## Context
The character content system generates carousels and facts but has no way to browse content by theme or plan what to create next. The 17 `ContentAngle` values (hidden_truths, character_evolution, actor_secrets, etc.) already serve as thematic categories - every carousel has an `angle` field. The Ideas tab surfaces these as the organizing layer, groups existing content under each theme, and lets AI generate specific content pitches.

## Design

### What is an "Idea"?
An idea is a **specific content pitch** within a theme/angle. For example:
- **Theme (angle):** `character_evolution`
- **Idea:** "5 actors who played Batman and how each one changed the character forever"
- **Idea:** "How Spider-Man went from nerdy teen to cosmic-level Avenger"

Existing carousels already belong to a theme via their `angle` field. The Ideas tab shows all themes, their existing content, and suggested new pitches.

### Pre-filled Ideas (seeded automatically)
Based on existing ContentAngle categories, seed these per character:

| Theme | Angle | Description |
|-------|-------|-------------|
| Trivia & Hidden Details | `hidden_truths` | Little-known facts most fans have never heard |
| Secret Powers | `power_secrets` | Hidden abilities and power details the audience doesn't know |
| Origin Story | `origin_story` | The untold story of how this character began |
| Character Evolution | `character_evolution` | How this character transformed across eras, actors, or storylines |
| Actor Secrets | `actor_secrets` | Behind-the-scenes actor stories, casting changes, multiple portrayals |
| Dark Facts | `dark_facts` | Disturbing or unsettling revelations |
| Fan Theories | `fan_theories` | The wildest fan theories and which ones might be true |
| Behind the Scenes | `behind_scenes` | Production secrets and BTS stories |
| Easter Eggs | `easter_eggs` | Hidden references and details you missed |
| What If | `what_if` | Alternate timelines and hypothetical scenarios |
| Controversial Takes | `controversial_takes` | Hot takes that will spark debate |
| Crossover Connections | `crossover_connections` | Links to other characters and universes |
| Vs Battle | `vs_comparison` | Head-to-head matchups and comparisons |
| Underrated Moments | `underrated_moments` | Overlooked scenes and character moments |
| Timeline Deep Dive | `timeline_deep_dive` | Chronological journey through key events |
| Storyline Recap | `storyline_recap` | Story condensation and arc summaries |
| Power Ranking | `power_ranking` | Comparative power level analysis |

Each seeded idea gets a character-specific description generated from research_data context.

### Data Model

**New JSONB column on `CharacterModel`:** `content_ideas` (list, default=[])

```python
class ContentIdea(BaseModel):
    id: str                          # "idea-{short_uuid}"
    title: str                       # specific pitch title
    description: str                 # 1-2 sentence pitch
    angle: str                       # maps to ContentAngle
    source: str = "seeded"           # "seeded" | "ai" | "manual"
    status: str = "fresh"            # "fresh" | "in_progress" | "used" | "dismissed"
    carousel_ids: List[str] = []     # carousels created from this idea
    priority: int = 0                # AI-ranked, higher = better
    created_at: Optional[datetime]
```

### Backend Changes

**Files to modify:**

1. **`backend/app/db/models.py`** (~line 1609) - Add `content_ideas` JSONB column to CharacterModel
2. **`backend/app/migrations/versions/030_content_ideas.py`** - New migration
3. **`backend/app/models/character_content.py`** - Add `ContentIdea`, `GenerateIdeasRequest`, `UpdateIdeaRequest` models; add `content_ideas` to `Character` model
4. **`backend/app/services/character_content_utils.py`** - Update `character_to_pydantic()` to map new field
5. **`backend/app/services/character_content_service.py`** - Add idea service methods
6. **`backend/app/routers/character_content.py`** - Add 4 endpoints

**Endpoints (registered before `/{character_id}` parameterized routes):**

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/{character_id}/ideas` | List ideas (auto-seeds if empty) |
| `POST` | `/{character_id}/ideas/generate` | AI-generate new specific pitches |
| `PATCH` | `/{character_id}/ideas/{idea_id}` | Update status, link carousel |
| `DELETE` | `/{character_id}/ideas/{idea_id}` | Dismiss/remove an idea |

**Seed logic (no LLM, instant):**
1. For each ContentAngle, create one idea with a character-specific title
2. Count existing carousels per angle, mark ideas with content as `status: "used"` and populate `carousel_ids`
3. Use character's `research_data` (bio, powers, filmography) to make titles specific (e.g., "How {name}'s powers evolved from {first_appearance} to now")

**AI Generate logic:**
- Prompt includes: character name, universe, existing facts summary, existing carousel angles, research highlights
- Asks for N specific content pitches with: title, description, suggested angle, priority
- Uses `get_unified_llm_client().chat(prompt, task_type="character_idea_generation")`
- Appends results to `content_ideas` JSONB

### Frontend Changes

**Files to modify:**

1. **`frontend/src/hooks/useCharacterContentApi.ts`** - Add `ContentIdea` type, query key, hooks: `useCharacterIdeas()`, `useGenerateIdeas()`, `useUpdateIdea()`, `useDeleteIdea()`
2. **`frontend/src/pages/CharacterDetailPage.tsx`** - Add 'ideas' to tab union, add Ideas tab (positioned after Overview), render IdeasSection component

**UI Design (inline in CharacterDetailPage, not a separate component file):**

- **Header:** "Content Ideas ({count})" with Lightbulb icon + "AI Generate" button (Sparkles icon)
- **Filter bar:** All | Fresh | In Progress | Used | Dismissed
- **Idea cards** in a grid (2-3 columns):
  - Title (bold)
  - Description (gray text)
  - Angle badge (colored, reusing CATEGORY_COLORS pattern)
  - Source pill: "Seeded" / "AI" / "Manual" 
  - Status indicator
  - Linked carousels count
  - **"Create Content" button** - calls existing carousel generation with the idea's angle, then patches idea status
  - **Dismiss button** (X) - marks as dismissed
- **Group by angle** with collapsible sections showing theme headers

### Generate-from-idea Flow
1. User clicks "Create Content" on an idea
2. Frontend calls `POST /{character_id}/carousel` with `{ angle: idea.angle }`
3. On success, calls `PATCH /{character_id}/ideas/{idea_id}` with `{ status: "used", carousel_ids: [..., newId] }`
4. Both query caches invalidate

### Implementation Sequence
1. Migration 030 - add `content_ideas` column
2. Pydantic models in `character_content.py`
3. DB model update in `models.py`
4. Update `character_to_pydantic()` in utils
5. Service methods in `character_content_service.py`
6. Router endpoints in `character_content.py`
7. Frontend hooks in `useCharacterContentApi.ts`
8. Ideas tab UI in `CharacterDetailPage.tsx`
9. Docker rebuild backend, restart frontend

### Verification
1. Navigate to a character detail page
2. Click "Ideas" tab - should show seeded ideas with existing carousel counts
3. Click "AI Generate" - should add new specific pitches
4. Click "Create Content" on a fresh idea - should generate carousel and update idea status
5. Filter by status - should work
6. Dismiss an idea - should hide it from default view
