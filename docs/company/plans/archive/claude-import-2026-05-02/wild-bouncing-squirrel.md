# Zero Character Content - Autopilot Run (2026-04-17)

## Context

The character content pipeline is actively running research (26/90 done, 3 active, 61 queued). However, content generation has barely started: only 15 carousels exist across just 5 characters (Darth Vader x5, Aquaman x3, Loki x3, Batman x2, Black Widow x2). 21 researched characters have zero carousels. Angle diversity is poor (8/15 are hidden_truths). No knowledge files exist yet. 8 carousels are in needs_work status.

## Plan: Full Autopilot Cycle

### Phase 1: Carousel Generation for Underserved Characters (~21 characters)
Generate 1 carousel each for the 21 researched characters with no content, using diverse angles/templates/hooks:

| Character | Angle | Template | Hook Style |
|-----------|-------|----------|------------|
| Thor | dark_facts | dark_origin | story_opener |
| Wolverine | behind_scenes | actor_behind_role | reveal |
| Deadpool | controversial_takes | hot_take | hot_take |
| Superman | character_evolution | timeline_story | comparison |
| Loki (skip - has 3) | - | - | - |
| Neo | fan_theories | fan_theory_deep_dive | question |
| John Wick | origin_story | real_life_inspiration | numbered_list |
| Tyler Durden | hidden_truths | secrets_revealed | reveal |
| Indiana Jones | behind_scenes | deleted_scenes | story_opener |
| Hannibal Lecter | dark_facts | dark_origin | superlative |
| Eren Yeager | character_evolution | timeline_story | story_opener |
| Ellie Williams | storyline_recap | storyline_recap | story_opener |
| Billy Butcher | controversial_takes | hot_take | hot_take |
| Hughie Campbell | hidden_truths | hidden_connection | comparison |
| Rue Bennett | dark_facts | timeline_tragedy | question |
| Jules Vaughn | behind_scenes | actor_behind_role | reveal |
| Faith MacCaulley | origin_story | dark_origin | numbered_list |
| Grace MacCaulley | hidden_truths | secrets_revealed | superlative |
| Lois | character_evolution | what_they_changed | question |
| Malcolm | behind_scenes | deleted_scenes | numbered_list |
| Luigi (voice) | behind_scenes | actor_behind_role | reveal |
| Rocky (voice) | origin_story | real_life_inspiration | story_opener |

**Angle distribution**: dark_facts x3, behind_scenes x4, controversial_takes x2, character_evolution x2, fan_theories x1, origin_story x3, hidden_truths x3, storyline_recap x1
**Hook distribution**: story_opener x4, reveal x4, hot_take x2, question x3, numbered_list x3, comparison x2, superlative x2

### Phase 2: Review New Carousels
- Trigger AI review on each generated carousel
- Check for generic/banned hooks and fix any flagged
- Approve carousels scoring >= 8.0, flag needs_work for < 8.0

### Phase 3: Fix needs_work Carousels (8 existing + any new)
- Regenerate with different angle/template for low-scoring carousels
- Especially the 4 duplicate Darth Vader hidden_truths/secrets_revealed carousels

### Phase 4: Establish Knowledge Files
Create initial knowledge files at `knowledge/`:
- `SCORECARD.md` - grade all 8 dimensions based on current state
- `IMPROVEMENT_PLAN.md` - prioritized backlog
- `EVOLUTION_LOG.md` - initial entry
- `CHARACTER_GRAPH.md` - connections for researched characters

### Phase 5: Multi-Character Content
Generate 2-3 ranking/versus carousels using the knowledge graph:
- Cross-universe: Batman vs John Wick (fighters)
- Marvel: Thor vs Wolverine (power ranking)
- Film: Tyler Durden vs Neo (fan_theories crossover)

## Key Files
- Router: `backend/app/routers/character_content.py`
- Service: `backend/app/services/character_content_service.py`
- Utils: `backend/app/services/character_content_utils.py`
- Models: `backend/app/models/character_content.py`

## Verification
- After generation: check carousel count increased from 15 to ~35+
- After review: check approved count increased from 7
- Spot-check 3 carousels for hook quality, fact accuracy, slide structure
- Verify no duplicate angle+character combos within 7-day window
- Check hook_style variety across the batch
