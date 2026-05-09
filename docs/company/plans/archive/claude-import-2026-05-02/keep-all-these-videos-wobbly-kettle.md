# Plan: Reference Video Ingest + Replication Engine Upgrade

## Context

You shared 16 TikTok URLs and want them (a) saved as reference videos, (b) analyzed so we can replicate the style, and (c) used as fuel for new content. You also asked whether we need more AI tools, and whether Claude Code should play a bigger role.

**Short answer on tooling**: Zero already has a strong text-based replication engine (reference video ingest via yt-dlp + Whisper + LLM style analysis, Content Brain v2 with a 7-agent swarm, prompt breeder, competitor scraper, trend intelligence). The two real gaps are **visual analysis** (we only read the transcript — we never look at the frames) and **direct reference-to-generation workflow** (videos get ingested but don't cleanly flow into the character content generator). Everything else is already there.

**Short answer on Claude Code**: Claude Code is a dev tool, not a runtime. What you probably mean is "should we call Claude (Sonnet/Haiku) as an LLM provider for content?" — yes, worth adding as a provider for scriptwriting where it beats Kimi/Ollama on voice and nuance. But that's an enhancement, not a blocker. Current system is good enough to replicate these videos today.

## Rewritten Prompt (the clean version of your ask)

> Ingest these 16 TikTok URLs into the reference video system. Run them through the existing analysis pipeline (download → transcribe → LLM style analysis). Review the style blueprints they produce and use them to seed new character content. Identify any gaps in our AI tooling that prevent faithful replication — especially visual/frame analysis — and close them using open-source or Google AI tools where needed. Goal: turn these 16 videos into a repeatable replication recipe for the content machine.

## What Exists Today (reusable, no work needed)

- **Ingest**: [backend/app/routers/character_reference_videos.py](backend/app/routers/character_reference_videos.py) — `POST /api/reference-videos/ingest-simple` accepts `{url}`, returns 202, processes async.
- **Download + metadata**: [backend/app/services/video_download_service.py](backend/app/services/video_download_service.py) — yt-dlp + ffmpeg, extracts title, author, caption, hashtags, views, likes, thumbnail.
- **Transcribe**: faster-whisper (local, int8).
- **LLM style analysis**: [backend/app/services/character_reference_video_service.py](backend/app/services/character_reference_video_service.py) — intent `inspiration` captures style, hook, pacing, visual_style, transitions, engagement.
- **Content generation**: [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py) — 7-agent swarm, 15+ angles, 14 story templates.
- **Storage**: Migration 022, SQLAlchemy models, files at `workspace/character_content/reference_videos/{id}/`.

## Recommended Approach (phased)

### Phase 1 — Ingest & Analyze (today, ~30 min, no new code)

1. POST each of the 16 URLs to `/api/reference-videos/ingest-simple` with `intent=inspiration` (a short script or one-off loop).
2. Wait for pipeline to complete (status → `ready`).
3. Review aggregated style analysis: common hooks, pacing, visual motifs, recurring transitions.
4. Save the aggregate summary as a **Style Blueprint** — new row(s) in a `reference_video_blueprints` table OR just a markdown doc in `workspace/character_content/blueprints/` referenced from the Brain.

**Deliverable**: "What makes these 16 videos tick" — 1-pager blueprint + 16 ready-to-browse reference videos in the UI.

### Phase 2 — Close the Visual Gap (this week, ~1 day)

Current analysis is transcript-only. For real style replication we need frame-level understanding. **Skipping Gemini** per user direction — use providers we already pay for.

**Approach**: ffmpeg-sample 6-12 keyframes per video (we already have ffmpeg wired in [video_download_service.py](backend/app/services/video_download_service.py)), then route `analyze_video_visual` to a **vision-capable provider we already have**:

- **Kimi vision** (`moonshot-v1-vision` via [kimi_provider.py](backend/app/infrastructure/llm_providers/kimi_provider.py)) — preferred, we already budget Kimi
- **MiniMax multimodal** (via [minimax_provider.py](backend/app/infrastructure/llm_providers/minimax_provider.py)) — fallback, cheaper
- **Ollama local vision** (qwen2-vl or llava pulled via `ollama pull`) — free fallback for budget-exceeded days

Ask the vision model for: shot list, color palette, text overlay patterns, motion style, on-screen elements, hook frame timing. Return structured JSON.

Files to modify:
- [backend/app/services/character_reference_video_service.py](backend/app/services/character_reference_video_service.py) — add `_extract_keyframes()` (ffmpeg) + `_analyze_visual()` step after transcription
- [backend/app/infrastructure/llm_providers/kimi_provider.py](backend/app/infrastructure/llm_providers/kimi_provider.py) — confirm vision model + image upload support
- [backend/app/infrastructure/llm_providers/llm_router.py](backend/app/infrastructure/llm_providers/llm_router.py) — register `analyze_video_visual` task type routed to Kimi vision → MiniMax → Ollama vision fallback chain
- Migration: add `visual_analysis JSONB` + `keyframes_dir` columns to the reference video row
- Frontend: show keyframe thumbnails + visual analysis next to transcript on the reference video detail view

**No new external dependency** — ffmpeg + existing providers. ~200 LoC.

### Phase 3 — Reference → Generation Loop (next, ~1 day)

Today, reference videos feed the character discovery flow but not the content generator directly. Add:
- A "Generate from Reference" button on the reference video detail page
- Backend route that seeds the swarm with the blueprint: hook style, pacing, visual motifs, transcript beats
- Output slots into the existing carousel pipeline

Files:
- [backend/app/routers/character_content.py](backend/app/routers/character_content.py) — add `POST /api/character-content/generate-from-reference/{video_id}`
- [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py) — new entry point `generate_from_reference_blueprint()`
- [frontend/src/pages/CharacterContentPage.tsx](frontend/src/pages/CharacterContentPage.tsx) — wire the button

### Phase 4 — Optional Tool Additions (defer unless Phase 1 reveals need)

Only pursue if Phase 1 blueprint review shows gaps the current toolchain can't cover:

| Tool | When to add | Cost |
|---|---|---|
| **Claude (Sonnet 4.6) as content provider** | If Kimi/Ollama hooks feel generic after Phase 1 | Already have Max plan + Agent SDK — just add provider wrapper |
| **Piper TTS** (open source) | If we want voiceover on carousels | Free, local, ~1 day integration |
| **Google Veo 3 / Kling / HunyuanVideo** | If we move beyond carousels to actual video | Expensive — defer until text/carousel engine is saturated |
| **ElevenLabs** | If Piper quality is insufficient | $5-22/mo, better voice |

**Recommendation**: Do Phase 1 + Phase 2 + Phase 3 first. Reassess Phase 4 with real blueprints in hand.

## URLs to Ingest

```
https://www.tiktok.com/t/ZP8gPJbtW/
https://www.tiktok.com/t/ZP8gPSNDy/
https://www.tiktok.com/t/ZP8gP6Y2R/
https://www.tiktok.com/t/ZP8gP2VoA/
https://www.tiktok.com/t/ZP8gPeCD6/
https://www.tiktok.com/t/ZP8gPjw5p/
https://www.tiktok.com/t/ZP8gmDCnT/
https://www.tiktok.com/t/ZP8gmXaqp/
https://www.tiktok.com/t/ZP8gmCasw/
https://www.tiktok.com/t/ZP8gmmjNG/
https://www.tiktok.com/t/ZP8gmy6PE/
https://www.tiktok.com/t/ZP8gm5MVm/
https://www.tiktok.com/t/ZP8gmmq7h/
https://www.tiktok.com/t/ZP8gmACHT/
https://www.tiktok.com/t/ZP8gmQvhj/
https://www.tiktok.com/t/ZP8gmusac/
```

## Legion Tracking

Per CLAUDE.md rules, create a Legion sprint "Reference Video Replication Engine" under project 8 with tasks for each phase.

## Verification

- **Phase 1**: All 16 videos show `status=ready` in the reference videos list; style blueprint markdown exists and is reviewed by user.
- **Phase 2**: Each reference video row has a populated `visual_analysis` column; frontend detail page renders it; at least 3 visual motifs show up across multiple videos (signal the analyzer works).
- **Phase 3**: "Generate from Reference" button produces a carousel whose hook/pacing demonstrably mirrors the source video (human QA on 3 examples).
- **Phase 4**: Only if triggered — validate provider works end-to-end with a single test task.

## Answers to Your Direct Questions

- **"Do we need Claude Code more?"** — No for runtime. Yes, consider adding **Claude (Sonnet 4.6) as an LLM provider** alongside Kimi/Ollama for scriptwriting tasks where voice quality matters. Max plan auth already works via Agent SDK.
- **"Do we need more AI tools?"** — No new providers. Phase 2 uses **Kimi vision / MiniMax / Ollama local vision** that are already wired. Gemini skipped per user direction. Everything else can wait until Phase 1 proves a gap.
