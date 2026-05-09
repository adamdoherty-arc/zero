# Plan: Reachy App Catalog + Local Pull

## Context

Zero already talks to the Reachy Mini Lite daemon at `host.docker.internal:8000` via [backend/app/services/reachy_service.py](c:\code\zero\backend\app\services\reachy_service.py) and uses the `reachy-mini-emotions` dataset for canned emotional moves. But we don't have a picture of the broader Reachy app ecosystem — what apps exist, what they do, what's reusable for Zero's voice loop / meetings / persona work.

Goal: **Discover, catalog, and pull locally** every app, tool, SDK, and move-library across Pollen Robotics' GitHub and the Hugging Face Reachy Mini app store, so Zero has a local reference library of "what tools we have at our disposal" — for inspiration, for lifting code (emotion mappings, dance choreographies, wake-word detectors, conversation prompts), and for possibly installing select apps onto the physical Reachy Mini via its desktop-app store.

## Discovery Summary (read-only results, already gathered)

| Source | Count | Notes |
|---|---|---|
| HF Spaces tagged `reachy_mini_python_app` | **180** | Canonical "installable app" tag — this is the whole app store |
| HF app-list.json (officially curated) | **8** | Shipped with the Reachy Mini Desktop App |
| Pollen Robotics official HF Spaces | **16** | Includes assembly guides, skins, flagship apps |
| Pollen Robotics HF datasets (Reachy Mini) | **3** high-value | `reachy-mini-emotions-library` (2062 dl), `reachy-mini-dances-library` (996 dl), `reachy2_emotions_library` (46 dl) |
| Pollen Robotics GitHub repos (reachy-related) | **37** | SDK, desktop-app, kinematics (Rust+C++), motor-controller, OS image, toolbox, experiments, dances library, teleop (Unity), Blender rigs, Reachy 2 stack |
| Community Spaces with ≥5 likes | **~40** | Real third-party apps worth pulling |

### The 8 officially curated apps (app-list.json)

1. `cdeplanne/wake_me_up` — alarm clock
2. `pollen-robotics/reachy_mini_conversation_app` — flagship voice assistant (OpenAI Realtime / Gemini Live)
3. `pollen-robotics/reachy_mini_radio` — internet radio with dancing
4. `pollen-robotics/red_light_green_light` — Squid-Game style motion game
5. `dlouapre/coding_lab` — learn-to-code with Reachy
6. `RemiFabre/marionette` — manual puppeteering UI
7. `Boopster/reachy_mini_metronome` — metronome + head bob
8. `pollen-robotics/reachy_mini_testbench` — hardware diagnostic

### Top community apps by likes (≥5)

| Likes | App | What it does |
|---|---|---|
| 332 | `itsMarco-G/reachy_phone_home` | phone-home check-in |
| 164 | `ravediamond/baby-reachy-mini-companion` | baby monitor / companion (Gradio) |
| 101 | `panny247/hello_world` | hello-world reference app |
| 67 | `d10g/f1commentator` | F1 race live commentator |
| 31 | `yozkut/judgy_reachy_no_phone` | phone-detection scolder |
| 30 | `jimenezcarrero/cookAIware` | cooking assistant |
| 24 | `8bitkick/reachy_mini_3d_web_viz` | 3D web visualiser of robot state |
| 23 | `tomrikert/clawbody` | claw-machine-style body control |
| 22 | `mattdotvaughn/reachy_mini_language_tutor` | language tutor |
| 21 | `TwinPeaksTownie/reachy-dance-duo` | two-robot dance duo |
| 18 | `djhui5710/reachy_mini_home_assistant` | Home Assistant bridge |
| 16 | `RemiFabre/marionette` | (also in curated list) |
| 15 | `trtd56/rock_paper_scissors` | rock-paper-scissors |
| 14 | `RemiFabre/emotions` | extended emotion set |
| 12 | `pollen-robotics/hand_tracker_v2` | MediaPipe hand tracking |
| 11 | `8bitkick/reachy_mini_reactions` | reaction expressions |
| 11 | `Boopster/reachy_mini_metronome` | (curated) |
| 11 | `pollen-robotics/reachy_mini_testbench` | (curated) |
| 10 | `gsalmon/dance_dance_reachy` | DDR-style dance |
| 10 | `chelleboyer/reachy_mini_karen_whisperer` | customer-service role-play |
| 10 | `Boopster/reachy_mini_minder` | reminder/todo app |
| 9 | `RemiFabre/Theremini` | Theremin-style gesture music |
| 9 | `robertkeus/reachys-brain` | brain/memory app |
| 9 | `RemiFabre/chess_emotions_app` | chess with emotion reactions |
| 9 | `jyvet/reachy-persona-experience` | persona/character engine |
| 8 | `AccidentalCoder80/Haven_ReachyMini_Contest_Final` | contest entry |
| 8 | `Domotick/reachy_mirror` | mirror/echo app |
| 8 | `CoWonder-ai/reachy-mini-apps` | app launcher |
| 7 | `Boopster/reachy_mini_ukulele_tuner` | ukulele tuner |
| 7 | `chelleboyer/reachy_mini_remix` | mashup/remix |
| 7 | `RemiFabre/fire_nation_attacked` | Avatar-the-last-airbender game |
| 7 | `pollen-robotics/reachy_mini_remote_control_app` | manual control UI |
| 7 | `pollen-robotics/reachy_mini_clock` | clock display |
| 6 | `Boopster/reachy_mini_danceml` | ML-generated dances |
| 6 | `RemiFabre/SimpleDances` | simple dance primitives |
| 6 | `apirrone/reachy_mini_phone_teleop` | phone-as-teleop-controller |
| 6 | `apirrone/reachy_mini_simon` | Simon-says game |
| 6 | `gamellama/reachy-mini-gemini` | Gemini Live voice |
| 6 | `chitrark/reachy_mini_bookreader` | book reader (docker) |
| 6 | `RemiFabre/feeling_machine` | emotion machine |
| 5 | `Halfzipp/reachy_mini_megan` | Megan persona |

### Pollen Robotics Reachy Mini GitHub repos (SDK/tools layer)

**Core SDK + daemon**
- `pollen-robotics/reachy_mini` — main Python SDK (1080 ★)
- `pollen-robotics/reachy-mini-desktop-app` — Tauri daemon + app store UI (69 ★)
- `pollen-robotics/reachy-mini-motor-controller` — Rust low-level motor driver (63 ★)
- `pollen-robotics/reachy_mini_rust_kinematics` — Rust kinematics (3 ★)
- `pollen-robotics/reachy_mini_cpp_kinematics` — C++ kinematics POC (1 ★)
- `pollen-robotics/reachy-mini-os` — Raspberry Pi OS image (13 ★)
- `pollen-robotics/reachyminios-gen` — OS image generator

**Dev tools / libraries**
- `pollen-robotics/reachy_mini_toolbox` — behavior-building helpers (10 ★)
- `pollen-robotics/reachy_mini_dances_library` — dance choreography library (14 ★)
- `pollen-robotics/reachy_mini_experiments` — POCs and experiments (8 ★)
- `pollen-robotics/reachy_mini_app_example` — app template (4 ★)
- `pollen-robotics/reachy_mini_stl_convexify` — STL convexification (10 ★)
- `pollen-robotics/reachy_mini_testing` — testing utilities
- `pollen-robotics/reachy_mini_conv_CI_POC` — conversation-app CI POC

**Reachy 2 (full-size humanoid — reference only, different robot)**
- `reachy2_core`, `reachy2-sdk`, `reachy2-sdk-api`, `reachy2_qpik`, `reachy2_symbolic_ik`, `reachy2-blender`, `reachy2-tutorials`, `reachy2_mujoco*`, `Reachy2Teleoperation`, `Reachy2-UnityDigitalTwin`, `reachy2-docs`, `reachy2_sdk_server`, `reachy_2023`

### High-value datasets (recorded moves, not raw training data)

- `pollen-robotics/reachy-mini-emotions-library` — the one we already reference in [reachy_service.py](c:\code\zero\backend\app\services\reachy_service.py)
- `pollen-robotics/reachy-mini-dances-library`
- `pollen-robotics/reachy2_emotions_library` (Reachy 2 variant, reference)

## Pull Strategy — Tiered

**Workspace**: `C:\code\reachy-apps\` (sibling to `zero/`, `DailyMeetings/`, `ADA/`). Each tier is a subdirectory. Everything is shallow-cloned (`--depth 1`) to keep disk use sane. Total estimated size: ~500 MB (apps are small HF Spaces).

```
C:\code\reachy-apps\
├── CATALOG.md                # master index — the deliverable
├── pull.sh                   # idempotent re-runnable puller
├── official/                 # Tier 1a: the 8 app-list.json apps
├── pollen/                   # Tier 1b: all 16 Pollen Robotics HF spaces + 14 GitHub repos
├── community/                # Tier 2: 40 community apps with ≥5 likes
├── sdk/                      # Tier 1c: core SDK + kinematics + motor-controller (GitHub)
└── datasets/                 # Tier 1d: emotions + dances move libraries
```

**Tier 3** (120 community spaces with 0-4 likes) is **cataloged in `CATALOG.md` but not cloned** — most are hello-worlds, forks, or unfinished. If a specific one becomes interesting later, clone it on demand.

### Pull commands (`pull.sh`)

```bash
#!/usr/bin/env bash
set -eu
ROOT="/c/code/reachy-apps"
mkdir -p "$ROOT"/{official,pollen,community,sdk,datasets}

# Helper: shallow-clone a HF Space unless already present
hf_clone() {  # $1=org/name  $2=dest_dir
  local name="$1" dest="$2"
  local target="$dest/$(basename "$name")"
  if [ -d "$target/.git" ]; then
    echo "skip (exists): $name"
  else
    git clone --depth 1 "https://huggingface.co/spaces/$name" "$target" || echo "FAIL: $name"
  fi
}

# Tier 1a — 8 officially curated apps
for app in \
  cdeplanne/wake_me_up \
  pollen-robotics/reachy_mini_conversation_app \
  pollen-robotics/reachy_mini_radio \
  pollen-robotics/red_light_green_light \
  dlouapre/coding_lab \
  RemiFabre/marionette \
  Boopster/reachy_mini_metronome \
  pollen-robotics/reachy_mini_testbench; do
  hf_clone "$app" "$ROOT/official"
done

# Tier 1b — remaining Pollen Robotics HF spaces (not already in official/)
for app in \
  pollen-robotics/Reachy_Mini \
  pollen-robotics/reachy-mini-skins \
  pollen-robotics/pollen-vision-demo \
  pollen-robotics/reachy_mini_bluetooth_tools \
  pollen-robotics/reachy_mini_greetings \
  pollen-robotics/Reachy_Mini_Assembly_Guide \
  pollen-robotics/Reachy_Mini_LITE_Assembly_Guide \
  pollen-robotics/Reachy_Mini_BETA_Assembly_Guide \
  pollen-robotics/reachy_mini_clock \
  pollen-robotics/hand_tracker_v2 \
  pollen-robotics/reachy_mini_remote_control_app \
  pollen-robotics/reachy-mini-chatbox; do
  hf_clone "$app" "$ROOT/pollen"
done

# Tier 1c — SDK + tools from GitHub
cd "$ROOT/sdk"
for repo in \
  pollen-robotics/reachy_mini \
  pollen-robotics/reachy-mini-desktop-app \
  pollen-robotics/reachy-mini-motor-controller \
  pollen-robotics/reachy_mini_rust_kinematics \
  pollen-robotics/reachy_mini_cpp_kinematics \
  pollen-robotics/reachy_mini_toolbox \
  pollen-robotics/reachy_mini_dances_library \
  pollen-robotics/reachy_mini_experiments \
  pollen-robotics/reachy_mini_app_example \
  pollen-robotics/reachy-mini-os \
  pollen-robotics/reachy_mini_stl_convexify \
  pollen-robotics/reachy_mini_testing \
  pollen-robotics/reachy_mini_conv_CI_POC \
  pollen-robotics/reachyminios-gen; do
  name=$(basename "$repo")
  [ -d "$name/.git" ] && echo "skip: $name" || gh repo clone "$repo" "$name" -- --depth 1 || echo "FAIL: $repo"
done

# Tier 1d — move-library datasets (hf_clone works on datasets too with /datasets/ prefix)
cd "$ROOT/datasets"
for ds in \
  pollen-robotics/reachy-mini-emotions-library \
  pollen-robotics/reachy-mini-dances-library \
  pollen-robotics/reachy2_emotions_library; do
  name=$(basename "$ds")
  [ -d "$name/.git" ] && echo "skip: $name" || git clone --depth 1 "https://huggingface.co/datasets/$ds" "$name" || echo "FAIL: $ds"
done

# Tier 2 — top-40 community apps (≥5 likes)
for app in \
  itsMarco-G/reachy_phone_home \
  ravediamond/baby-reachy-mini-companion \
  panny247/hello_world \
  d10g/f1commentator \
  yozkut/judgy_reachy_no_phone \
  jimenezcarrero/cookAIware \
  8bitkick/reachy_mini_3d_web_viz \
  tomrikert/clawbody \
  mattdotvaughn/reachy_mini_language_tutor \
  TwinPeaksTownie/reachy-dance-duo \
  djhui5710/reachy_mini_home_assistant \
  trtd56/rock_paper_scissors \
  RemiFabre/emotions \
  pollen-robotics/hand_tracker_v2 \
  8bitkick/reachy_mini_reactions \
  gsalmon/dance_dance_reachy \
  chelleboyer/reachy_mini_karen_whisperer \
  Boopster/reachy_mini_minder \
  RemiFabre/Theremini \
  robertkeus/reachys-brain \
  RemiFabre/chess_emotions_app \
  jyvet/reachy-persona-experience \
  AccidentalCoder80/Haven_ReachyMini_Contest_Final \
  Domotick/reachy_mirror \
  CoWonder-ai/reachy-mini-apps \
  Boopster/reachy_mini_ukulele_tuner \
  chelleboyer/reachy_mini_remix \
  RemiFabre/fire_nation_attacked \
  Boopster/reachy_mini_danceml \
  RemiFabre/SimpleDances \
  apirrone/reachy_mini_phone_teleop \
  apirrone/reachy_mini_simon \
  gamellama/reachy-mini-gemini \
  chitrark/reachy_mini_bookreader \
  RemiFabre/feeling_machine \
  Halfzipp/reachy_mini_megan; do
  hf_clone "$app" "$ROOT/community"
done

echo "DONE. Run ./catalog.py to regenerate CATALOG.md from on-disk state."
```

### CATALOG.md format (the actual deliverable)

Auto-generated from the HF API + on-disk state. Each entry:

```
### <app name>
- **Path**: relative/path/if/cloned
- **Source**: huggingface.co/spaces/<id> or github.com/<id>
- **Author**: <author>
- **Likes**: N   **SDK**: static/gradio/docker   **Last modified**: YYYY-MM-DD
- **Summary**: <first paragraph of README.md>
- **Uses**: models [...], datasets [...]
- **Zero integration ideas**: <1 line if obvious>
```

Sections:
1. **Tier 1a — Officially curated (8)**
2. **Tier 1b — Pollen Robotics other (12)**
3. **Tier 1c — SDK & infrastructure (14)**
4. **Tier 1d — Move libraries (3)**
5. **Tier 2 — High-signal community (~36)**
6. **Tier 3 — Catalog-only, not cloned (~120)** — table of id / likes / last-modified, no deep dive

A small Python script (`catalog.py`) walks the cloned directories, reads each `README.md`, and stitches the final document — keeps it re-runnable as we refresh.

## Files to create

| File | Purpose |
|---|---|
| `C:\code\reachy-apps\pull.sh` | the shell script above |
| `C:\code\reachy-apps\catalog.py` | CATALOG.md generator (reads READMEs + HF API) |
| `C:\code\reachy-apps\CATALOG.md` | the human-readable index |
| `C:\code\reachy-apps\.gitignore` | skip large/binary dataset artifacts |

Nothing in the Zero codebase changes — this is a new sibling workspace, same pattern as `C:\code\DailyMeetings\`.

## Verification

1. `ls C:\code\reachy-apps/official/ | wc -l` → 8
2. `ls C:\code\reachy-apps/pollen/ | wc -l` → 12
3. `ls C:\code\reachy-apps/sdk/ | wc -l` → 14
4. `ls C:\code\reachy-apps/community/ | wc -l` → ~36
5. `du -sh C:\code\reachy-apps/` → under 1 GB
6. Open `CATALOG.md` — confirm every Tier-1 entry has a path + summary populated
7. Spot-check: `cd official/reachy_mini_conversation_app && cat README.md` shows the flagship app's docs
8. Cross-reference: any of the ~40 cloned apps reference `reachy-mini-emotions-library` — confirms we can trace model/dataset edges Zero may want to reuse
