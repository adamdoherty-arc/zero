# Carousel Visual Rendering Rules

These rules are evaluated by `/character-content-review --carousel-visual-qa` against
a single carousel (or all carousels for a character). Each rule produces findings
with a severity and a fix command (typically a `POST /api/characters/carousels/{id}/enhance`
or `POST .../council-vote` payload) that can be copied into a terminal or run via
the editor page at `/characters/<id>/carousels/<cid>/edit`.

---

## R1. Hook / Slide-1 Duplication

**What it catches**: The editor was showing the hook twice on slide 1 because
`hook_text` and `slides[0].text` drifted to the same copy. Creates a visually
"duplicated" or "ghosted" look independent of any shadow bug.

**Check**:
```
normalize(hook_text) == normalize(slides[0].text)
```
where `normalize(s)` is `re.sub(r'[^a-z0-9 ]+', '', s.lower().strip())` with
whitespace collapsed to single spaces.

**Severity**: `high`

**Fix command**:
```
POST /api/characters/carousels/{id}/enhance
{
  "target": "slide",
  "slide_num": 1,
  "instruction": "Rewrite the slide 1 body so it does not repeat the hook. The hook already sets the premise; this body should deliver the first surprising fact.",
  "n_variants": 3
}
```

---

## R2. Broken Compound Term Wrap

**What it catches**: Phrases like "The MCU", "Black Widow", "Iron Man",
"Doctor Strange", "Avengers: Endgame" getting split across two lines.

**Check**: Read `generation_metadata.render_warnings` for entries with
`type="compound_wrap_broken"`. These are attached by
`carousel_renderer_service._wrap_text` when an NBSP-preserved compound still
ends up split (font too large, column too narrow).

**Severity**: `medium`

**Fix command**:
```
POST /api/characters/carousels/{id}/enhance
{
  "target": "slide",
  "slide_num": <slide_num>,
  "instruction": "Rewrite this slide so the term `<compound>` stays on a single line. Keep the same meaning; you may shorten surrounding filler words. Do NOT use line breaks inside the term.",
  "n_variants": 2
}
```

If repeated on the same term across 3+ slides, also mutate the character
profile's `no_break_terms` list so future generations inherit it.

---

## R3. Character Coverage

**What it catches**: Black Widow mentioned 3 times on one slide and never on
another. Symptom of lazy prompt adherence; the character name should be
referenced on most slides without being spammy.

**Check**:
- Count first-name and full-name mentions in `hook_text`, each `slides[i].text`,
  and `caption` (case-insensitive, word-boundary).
- Let `n = slide_count`, `m = sum(mentions)`.
- Flag OVER-SATURATED if `m > 1.5 * n` (more than 1.5 mentions per slide on
  average across hook + slides + caption).
- Flag UNDER-MENTIONED if `n > 2` and any `slides[i > 0]` has zero mentions
  AND the caption doesn't name the character either.
- Honor a per-character allowlist for hyphenated or multi-token names
  (e.g. `Spider-Man`, `She-Hulk`, `X-Men`) - count the full form as one mention.

**Severity**: `medium` for over-saturated, `low` for under-mentioned
(except on 2-character breakdowns where both must be named on every slide).

**Fix command (over-saturated)**:
```
POST /api/characters/carousels/{id}/enhance
{
  "target": "all",
  "instruction": "Reduce repetition of the name `<name>`. Refer to the character by pronoun, role, or epithet on most slides. Name them directly on slide 1, slide <mid>, and the final slide only.",
  "n_variants": 2
}
```

**Fix command (under-mentioned)**:
```
POST /api/characters/carousels/{id}/enhance
{
  "target": "slide",
  "slide_num": <missing_slide>,
  "instruction": "Re-anchor this slide on `<name>`. The reader should always know whose story they are reading.",
  "n_variants": 2
}
```

---

## R4. Text Contrast

**What it catches**: "All-white" slides like the Aquaman example, where the
background image is bright enough that white text becomes unreadable.

**Check**: Read `generation_metadata.render_warnings` for entries with
`type="contrast_low"` + `contrast_ratio` field. Any slide with
`contrast_ratio < 4.5` (WCAG AA for body text) is flagged.

Also flag if `_compute_overlay_strength` returned `> 0.65` (image is very
bright) but no dark-side gradient / label pill was applied - indicates the
renderer saw the problem but the text variant didn't escalate.

**Severity**: `high` (unreadable text is the single worst visual defect).

**Fix command**: This is a renderer-side fix, not a copy-side fix. Re-render
the slide with forced dark overlay:
```
POST /api/characters/carousels/{id}/render-slide
{
  "slide_num": <slide_num>,
  "overlay_strength": 0.65,
  "force_label_pills": true
}
```

If repeated, report the issue against `carousel_renderer_service._compute_overlay_strength`
for tuning.

---

## R5. Banned Hook Patterns on Existing Rows

**What it catches**: Old carousels that shipped before the banned-pattern
guard was added. The phrase "The Hammer Lie" (and other `<SingleWord> Lie`
/ `What Most Don't Know` / `X Things You Never Knew` style generic
clickbait openers) is still sitting in the DB.

**Check**: Run `character_content_service._is_generic_hook` (with its
normalized regex) against `hook_text` AND `slides[0].text`. Both must pass.

**Severity**: `high` for unpublished rows (fix before publish),
`medium` for published rows (schedule backfill but do not overwrite live content).

**Fix command** (bulk):
```
POST /api/characters/carousels/backfill-banned-hooks
{"limit": 500, "dry_run": false}
```

**Fix command** (single, more specific rewrite):
```
POST /api/characters/carousels/{id}/enhance
{
  "target": "hook",
  "instruction": "Replace the generic clickbait hook with a specific, fact-driven hook that names `<character>` and previews a concrete surprise. Avoid templates like 'The X Lie', 'What Most Don't Know', 'X things you didn't know'.",
  "n_variants": 3
}
```

---

## R6. Text Density

**What it catches**: Slides that are nearly empty ("She was powerful.") or
walls of text that overflow the TikTok safe area.

**Check** (per slide, excluding hook):
- `words = len(re.findall(r"\b\w+\b", slide.text))`
- Flag THIN if `words < 3`.
- Flag OVERFLOW if `words > 40`.

**Severity**: `low` for THIN, `medium` for OVERFLOW (overflow clips on
mobile).

**Fix command (thin)**:
```
POST /api/characters/carousels/{id}/enhance
{
  "target": "slide",
  "slide_num": <n>,
  "instruction": "Expand this slide to 15-25 words. Add one specific detail, number, or quote. Keep the bold focal phrase.",
  "n_variants": 2
}
```

**Fix command (overflow)**:
```
POST /api/characters/carousels/{id}/enhance
{
  "target": "slide",
  "slide_num": <n>,
  "instruction": "Tighten this slide to 15-25 words. Keep the strongest verb and the most specific fact; cut filler.",
  "n_variants": 2
}
```

---

## Execution Order

When `--carousel-visual-qa` runs, evaluate rules in this order and stop
early within a carousel only on `R4 high` (contrast). For every other rule,
collect ALL findings and emit them together so a single council vote round
can resolve multiple issues.

1. R4 Contrast (deal-breaker)
2. R5 Banned patterns (publishability blocker)
3. R1 Hook / slide-1 duplication (first-impression blocker)
4. R3 Character coverage (over-saturated, then under-mentioned)
5. R2 Compound wrap
6. R6 Text density

---

## Output Format

```
Carousel ccr-<id12> — <character_name> — grade: <A-F>
  R1 Duplication:       PASS | FAIL (<why>)
  R2 Compound wrap:     PASS | FAIL (<n> broken compounds: [...])
  R3 Coverage:          PASS | OVER | UNDER (<stats>)
  R4 Contrast:          PASS | FAIL (<slide_num>: <ratio>)
  R5 Banned hooks:      PASS | FAIL (matches: [...])
  R6 Text density:      PASS | THIN (slides: [...]) | OVERFLOW (slides: [...])

  Suggested fixes (in order):
  1. POST /api/characters/carousels/<id>/enhance { ... }
  2. POST /api/characters/carousels/<id>/council-vote { ... }
  ...
```

Findings with severity `high` count against the Content Generation dimension
at -5 points each. `medium` is -3, `low` is -1. Cap the total penalty per
carousel at -20 so one broken carousel can't sink the whole grade.
