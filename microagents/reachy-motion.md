---
name: reachy-motion
type: knowledge
triggers: [reachy, antennas, motion, emotion, dance, wobble, head wobble, gesture]
agent: any
---

When the user asks Reachy to express something physically:

- Use `app.services.reachy_motion_library.get_motion_library()` to look up clips.
- 81 emotion clips + 19 dance clips, each with semantic aliases (e.g.
  "amazed" → `amazed1`, "happy" → `cheerful1`).
- Live-speech wobble is owned by `head_wobbler.py` + `sway.py`. Don't try
  to send raw `set_target` frames while a speech wobble is active.
- Motion commands route through `/api/reachy/{emotion,dance,motion/play}`
  on the FastAPI surface, or `tools.dispatch()` from the realtime path.

Hard safety rule: never move toward a child faster than walking speed.
The `buddy` persona's SOUL.md encodes this — honor it.
