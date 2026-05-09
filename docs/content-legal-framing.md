# Character Content — Legal Framing (Advisory)

**Status:** Advisory guidance. Not enforced at the schema/pipeline gate. Referenced by the swarm's `commentary_framing` rubric field.

## Why this document exists

In 2025–2026 the copyright landscape for AI-generated IP character content turned sharply hostile:

- **Disney v. Midjourney (Jun 2025)** and **WBD v. Midjourney (Sep 2025)** litigate *output-side* infringement — the image itself, not just training data.
- **Disney December 2025 cease-and-desist to Google** triggered mass YouTube takedowns of Veo-generated Disney content.
- **Disney × OpenAI $1B Sora licensing deal (Dec 2025)** — licensed pipelines exist, unlicensed pipelines are now contrast.
- **YouTube "inauthentic content" policy (Jul 2025)** targets mass-produced templated content with full YPP removal, not just per-video demonetization.
- **Warhol v. Goldsmith (598 U.S. 508, 2023)** — stylistic transformation alone is not transformative; you need a *different purpose*.
- **Getty v. Stability (UK, Nov 2025)** — trademark liability survived even when copyright didn't, on reproduced watermarks.
- **USCO Jan 2025 (Zarya of the Dawn, Thaler)** — prompts alone do not give humans enough creative control for copyright registration. You need substantial human-authored layers or you own nothing.

## Six load-bearing rules

1. **Commentary / review framing is the survival path.** Voice-over analysis, lore explainers, comic-history deep dives, ranking lists, reaction/debate formats. Model: *Comics Explained*. The `hook_text` and `caption` should read as commentary *about* the character, not as the character itself speaking in-universe entertainment.
2. **Stylize away from official art.** Avoid photorealism for IP characters. Avoid exact costume reproduction. Avoid publisher logos, wordmarks, and title cards. Prefer watercolor, sketch, comic-ink, silhouette, cel-shaded, or illustrative treatments over photoreal.
3. **Add substantial human-authored layers.** Scripts written (or heavily edited) by a human. Editorial sequencing. Original analysis. This is also the only path to owning *any* copyright in the output.
4. **Never use actor likenesses.** No Downey Jr., Cavill, Holland, Pattinson, etc. Right-of-publicity + NO FAKES Act momentum makes actor deepfakes the legal crosshairs.
5. **Never use Marvel/DC/Disney soundtracks.** Instant Content ID strike. Use Epidemic Sound, Artlist, Uppbeat, or YouTube Audio Library.
6. **Disclose AI generation.** Toggle platform AI-disclosure flags. Add on-screen "AI-generated" text in the first 3 seconds of video. C2PA Content Credentials at generation time when technically feasible.

## Platform-specific risk

- **YouTube Shorts**: The July 2025 inauthentic-content policy is the biggest 24/7 existential risk — design template *variety* into the pipeline. Vary hook structure, visual template, narrator, pacing every 20–50 pieces. Never let the pipeline output 1000 identical-structure videos in a row.
- **TikTok**: Integrated auto-C2PA detection in Jan 2025; removed 2.3M videos under synthetic-media policy in Q1 2026. Disclosure required.
- **Instagram Reels**: Meta's AI-content labels are automatic on detection; label it yourself anyway.

## How this doc connects to the code

The swarm's `SwarmRubric.commentary_framing` field (pass/fail) is a soft gate — the `critic` role evaluates whether a drafted carousel reads as commentary/analysis vs. as in-universe entertainment. When it fails, the W3 retry loop routes back to the writer with a feedback note.

This is advisory — not a hard schema constraint — by explicit scoping decision. Upgrade to enforced gates (e.g. automatic rejection of generations labeled `photoreal` for IP characters, automatic `ai_disclosure` metadata injection) is a separate workstream.

## Non-goals for this doc

- Actor-likeness detection (future work; needs CV model).
- Automatic C2PA signing (future work; needs generator integration).
- Music-library enforcement (future work; `music_mood` is free-text today).
- Attorney review. **Talk to a lawyer before publishing to new platforms or at volume.**

## References

- Source report: *The 24/7 Marvel/DC content swarm blueprint*, Section I ("Legal and hardware risk reality").
- `backend/app/services/content_swarm_service.py` — `SwarmRubric` rubric fields.
- `docs/mobile-pwa.md` — platform disclosure patterns for the share target.
