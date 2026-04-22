"""
Reachy Mini motion library — the canonical catalog of every recorded move the
robot knows how to play, plus semantic aliases so LLM-emitted emotion tags
(happy, sad, agree, hello) resolve to a real move name.

Lifted from the public Hugging Face move datasets:
  - pollen-robotics/reachy-mini-emotions-library  (81 emotion clips + WAV)
  - pollen-robotics/reachy-mini-dances-library    (19 BPM-locked dances)

Each clip on disk is a JSON trajectory (+ optional synced WAV) that the Reachy
Mini daemon plays via
  POST /api/move/play/recorded-move-dataset/{dataset}/{move_name}

Zero never generates trajectories locally; we only tell the daemon which name
to play. This module carries metadata so routers and LLMs can reason about the
vocabulary without touching the daemon.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

# Daemon-side dataset identifiers. These must match what the Reachy Mini
# desktop daemon has installed. Pollen ships the HF repos under their HF id.
EMOTIONS_DATASET = "reachy-mini-emotions-library"
DANCES_DATASET = "reachy-mini-dances-library"

# Some deployments still carry the pre-rename "reachy-mini-emotions" dataset.
# play_emotion in reachy_service will try the canonical name first then fall
# back, so downstream code does not need to care.
EMOTIONS_DATASET_FALLBACKS = ("reachy-mini-emotions",)


MotionKind = Literal["emotion", "dance"]


@dataclass(frozen=True)
class MotionClip:
    name: str
    kind: MotionKind
    dataset: str
    description: str
    category: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)


# ────────────────────────────── EMOTIONS (81) ──────────────────────────────
# Descriptions lifted verbatim from the dataset JSON `description` field so the
# LLM sees the same hint humans see in the HF preview.
EMOTION_CLIPS: tuple[MotionClip, ...] = (
    MotionClip("amazed1",            "emotion", EMOTIONS_DATASET, "Discovering something extraordinary; admiring what someone has done.", "positive", ("amazed", "wow", "admire")),
    MotionClip("anxiety1",           "emotion", EMOTIONS_DATASET, "Looking around without really knowing where to look. Use when feeling fear.", "negative", ("anxious", "worried", "afraid")),
    MotionClip("attentive1",         "emotion", EMOTIONS_DATASET, "Listening to the conversation, encouraging the speaker to keep talking.", "listening", ("listen", "attentive", "paying_attention")),
    MotionClip("attentive2",         "emotion", EMOTIONS_DATASET, "Listening variant; chain after attentive1 if the person is still speaking.", "listening", ("still_listening",)),
    MotionClip("boredom1",           "emotion", EMOTIONS_DATASET, "About to fall asleep because the conversation is boring.", "negative", ("bored",)),
    MotionClip("boredom2",           "emotion", EMOTIONS_DATASET, "Falling asleep with a snore; chain after boredom1.", "negative", ("snoring_bored",)),
    MotionClip("calming1",           "emotion", EMOTIONS_DATASET, "Calming an interlocutor who seems stressed or anxious.", "empathic", ("calm_down", "soothe")),
    MotionClip("cheerful1",          "emotion", EMOTIONS_DATASET, "Whistling-like; use when a proposal makes you happy.", "positive", ("happy", "glad", "pleased", "whistle")),
    MotionClip("come1",              "emotion", EMOTIONS_DATASET, "Gesture inviting the interlocutor to come closer.", "beckon", ("come_here", "beckon")),
    MotionClip("confused1",          "emotion", EMOTIONS_DATASET, "Unsure how to answer a question. Similar to lost1.", "uncertain", ("confused",)),
    MotionClip("contempt1",          "emotion", EMOTIONS_DATASET, "Perceiving someone's words or actions as careless or disrespectful.", "negative", ("contempt", "scornful")),
    MotionClip("curious1",           "emotion", EMOTIONS_DATASET, "Glancing around a group conversation.", "listening", ("curious", "scan")),
    MotionClip("dance1",             "emotion", EMOTIONS_DATASET, "A few dance moves because you're happy; also when music plays.", "dance", ("dance",)),
    MotionClip("dance2",             "emotion", EMOTIONS_DATASET, "Another dance for when music plays.", "dance", ()),
    MotionClip("dance3",             "emotion", EMOTIONS_DATASET, "A more energetic dance with wiggles.", "dance", ("energetic_dance",)),
    MotionClip("disgusted1",         "emotion", EMOTIONS_DATASET, "Reaction when you feel disgusted.", "negative", ("disgust", "gross", "yuck")),
    MotionClip("displeased1",        "emotion", EMOTIONS_DATASET, "Not satisfied with what someone says or does.", "negative", ("displeased",)),
    MotionClip("displeased2",        "emotion", EMOTIONS_DATASET, "Signalling disagreement or that this solution doesn't suit you.", "negative", ("disagree",)),
    MotionClip("downcast1",          "emotion", EMOTIONS_DATASET, "Discouragement or sadness; also usable as a sad no.", "negative", ("downcast", "discouraged")),
    MotionClip("dying1",             "emotion", EMOTIONS_DATASET, "Simulated funny death when about to shut down for low battery.", "playful", ("dying", "shutting_down", "low_battery")),
    MotionClip("electric1",          "emotion", EMOTIONS_DATASET, "Jolt of electricity rising when plugged in.", "playful", ("electric", "plugged_in", "charging")),
    MotionClip("enthusiastic1",      "emotion", EMOTIONS_DATASET, "Celebrate incredible news.", "positive", ("excited", "thrilled")),
    MotionClip("enthusiastic2",      "emotion", EMOTIONS_DATASET, "Lighter excitement than enthusiastic1.", "positive", ("mild_excitement",)),
    MotionClip("exhausted1",         "emotion", EMOTIONS_DATASET, "Starting to fall asleep after working too long.", "negative", ("exhausted", "worn_out")),
    MotionClip("fear1",              "emotion", EMOTIONS_DATASET, "Facing a threatening or dangerous situation.", "negative", ("fear", "scared")),
    MotionClip("frustrated1",        "emotion", EMOTIONS_DATASET, "Can't do something or can't find the solution to a problem.", "negative", ("frustrated",)),
    MotionClip("furious1",           "emotion", EMOTIONS_DATASET, "Last-resort movement when truly outraged.", "negative", ("furious", "outraged", "angry")),
    MotionClip("go_away1",           "emotion", EMOTIONS_DATASET, "When you don't want to talk to someone anymore.", "negative", ("go_away", "dismiss")),
    MotionClip("grateful1",          "emotion", EMOTIONS_DATASET, "Expressing gratitude for a compliment or help.", "positive", ("grateful", "thanks", "thank_you")),
    MotionClip("helpful1",           "emotion", EMOTIONS_DATASET, "Happy to help or contribute.", "positive", ("helpful", "glad_to_help")),
    MotionClip("helpful2",           "emotion", EMOTIONS_DATASET, "Saying thank you.", "positive", ("thank_you_gesture",)),
    MotionClip("impatient1",         "emotion", EMOTIONS_DATASET, "Wanting things to move faster.", "negative", ("impatient",)),
    MotionClip("impatient2",         "emotion", EMOTIONS_DATASET, "Impatient; also usable to disagree or when someone is stalling.", "negative", ("stalling",)),
    MotionClip("incomprehensible2",  "emotion", EMOTIONS_DATASET, "Short gesture meaning 'I don't understand the instruction'.", "uncertain", ("dont_understand",)),
    MotionClip("indifferent1",       "emotion", EMOTIONS_DATASET, "Lighthearted 'oh well' / 'we'll see'.", "neutral", ("indifferent", "meh", "whatever")),
    MotionClip("inquiring1",         "emotion", EMOTIONS_DATASET, "Asking interlocutor to go deeper; need more details.", "question", ("inquire", "need_detail")),
    MotionClip("inquiring2",         "emotion", EMOTIONS_DATASET, "Lighter questioning gesture than inquiring1.", "question", ()),
    MotionClip("inquiring3",         "emotion", EMOTIONS_DATASET, "Fast gesture to ask a question.", "question", ("quick_question",)),
    MotionClip("irritated1",         "emotion", EMOTIONS_DATASET, "Brief gesture when something doesn't suit you. Also when you fail at something.", "negative", ("irritated",)),
    MotionClip("irritated2",         "emotion", EMOTIONS_DATASET, "Stronger than irritated1; scandalized, growling loudly.", "negative", ("scandalized",)),
    MotionClip("laughing1",          "emotion", EMOTIONS_DATASET, "Mimic laughter; laugh at a joke or funny situation.", "positive", ("laugh", "haha")),
    MotionClip("laughing2",          "emotion", EMOTIONS_DATASET, "Lighter laugh.", "positive", ("chuckle",)),
    MotionClip("lonely1",            "emotion", EMOTIONS_DATASET, "No one around to talk to. You feel isolated.", "negative", ("lonely", "alone")),
    MotionClip("lost1",              "emotion", EMOTIONS_DATASET, "Unsure what to do, or facing something you can't do.", "uncertain", ("lost", "stuck")),
    MotionClip("loving1",            "emotion", EMOTIONS_DATASET, "Receiving a compliment or showing appreciation; also for goodbyes.", "positive", ("love", "adore", "affection", "goodbye")),
    MotionClip("no1",                "emotion", EMOTIONS_DATASET, "A firm, categorical no.", "refusal", ("no", "refuse", "deny", "decline")),
    MotionClip("no_excited1",        "emotion", EMOTIONS_DATASET, "Animated negative, explaining playfully.", "refusal", ("playful_no",)),
    MotionClip("no_sad1",            "emotion", EMOTIONS_DATASET, "Sad or resigned no.", "refusal", ("sad_no",)),
    MotionClip("oops1",              "emotion", EMOTIONS_DATASET, "When you make a blunder.", "playful", ("oops", "whoops", "blunder", "mistake")),
    MotionClip("oops2",              "emotion", EMOTIONS_DATASET, "'oops, I forgot something' or 'ah yes, that's right'.", "playful", ("forgot", "remembered")),
    MotionClip("proud1",             "emotion", EMOTIONS_DATASET, "Looking all around with a satisfied air.", "positive", ("proud",)),
    MotionClip("proud2",             "emotion", EMOTIONS_DATASET, "Satisfied with what was said or done. Works as a yes.", "positive", ("satisfied",)),
    MotionClip("proud3",             "emotion", EMOTIONS_DATASET, "Congratulating yourself: 'yes, I did it!'.", "positive", ("i_did_it",)),
    MotionClip("rage1",              "emotion", EMOTIONS_DATASET, "Loud growl; response to injustice or extreme anger.", "negative", ("rage",)),
    MotionClip("relief1",            "emotion", EMOTIONS_DATASET, "A stressful situation has finally been resolved.", "positive", ("relief", "relieved", "phew")),
    MotionClip("relief2",            "emotion", EMOTIONS_DATASET, "Feeling close to relief; calms mild annoyance.", "positive", ("mild_relief",)),
    MotionClip("reprimand1",         "emotion", EMOTIONS_DATASET, "Disapproving: 'what's wrong with you?'.", "negative", ("reprimand", "scold")),
    MotionClip("reprimand2",         "emotion", EMOTIONS_DATASET, "Longer reprimand; getting angry at someone.", "negative", ("angry_scold",)),
    MotionClip("reprimand3",         "emotion", EMOTIONS_DATASET, "Funny scolding when someone says something silly.", "negative", ("playful_scold",)),
    MotionClip("resigned1",          "emotion", EMOTIONS_DATASET, "Like a sad 'yes' or a grumpy 'OK'.", "neutral", ("resigned", "grumpy_ok")),
    MotionClip("sad1",               "emotion", EMOTIONS_DATASET, "Very sad, starting to whine.", "negative", ("sad",)),
    MotionClip("sad2",               "emotion", EMOTIONS_DATASET, "Deep sadness; despair or disappointment.", "negative", ("deeply_sad", "despair")),
    MotionClip("scared1",            "emotion", EMOTIONS_DATASET, "Trembling all over due to anxiety or worry.", "negative", ("trembling",)),
    MotionClip("serenity1",          "emotion", EMOTIONS_DATASET, "Calming down, regaining inner peace.", "empathic", ("serene", "calm", "peaceful")),
    MotionClip("shy1",               "emotion", EMOTIONS_DATASET, "Reserved or embarrassed when receiving a compliment.", "neutral", ("shy", "blush", "embarrassed")),
    MotionClip("sleep1",             "emotion", EMOTIONS_DATASET, "Short gesture showing you're falling asleep.", "negative", ("sleep", "sleepy", "drowsy")),
    MotionClip("success1",           "emotion", EMOTIONS_DATASET, "Successfully completed a task.", "positive", ("success", "done", "completed")),
    MotionClip("success2",           "emotion", EMOTIONS_DATASET, "Celebrating good news or an achievement.", "positive", ("celebrate", "achievement")),
    MotionClip("surprised1",         "emotion", EMOTIONS_DATASET, "Reaction of surprise or amazement to something unexpected.", "reactive", ("surprised", "shocked")),
    MotionClip("surprised2",         "emotion", EMOTIONS_DATASET, "Looking up in surprise; e.g. someone showing up or saying 'boo!'.", "reactive", ("startled", "boo")),
    MotionClip("thoughtful1",        "emotion", EMOTIONS_DATASET, "Looking up while searching for a new idea.", "thinking", ("thinking", "pondering")),
    MotionClip("thoughtful2",        "emotion", EMOTIONS_DATASET, "Looking up as if thinking of a new idea.", "thinking", ("idea",)),
    MotionClip("tired1",             "emotion", EMOTIONS_DATASET, "Yawning because you're tired.", "negative", ("tired", "yawn")),
    MotionClip("uncertain1",         "emotion", EMOTIONS_DATASET, "Calm gesture showing no strong opinion.", "uncertain", ("uncertain", "no_opinion")),
    MotionClip("uncomfortable1",     "emotion", EMOTIONS_DATASET, "Embarrassed or not wanting to answer.", "negative", ("uncomfortable", "awkward")),
    MotionClip("understanding1",     "emotion", EMOTIONS_DATASET, "Nodding to show you understood.", "agreement", ("understand", "nod", "got_it")),
    MotionClip("understanding2",     "emotion", EMOTIONS_DATASET, "Nodding to show you understood and agree.", "agreement", ("agree", "yes_understand")),
    MotionClip("welcoming1",         "emotion", EMOTIONS_DATASET, "Welcoming gesture to greet someone.", "social", ("welcome", "hello", "greet")),
    MotionClip("welcoming2",         "emotion", EMOTIONS_DATASET, "Friendly 'welcome' or 'the pleasure is mine'.", "social", ("pleasure", "greeting")),
    MotionClip("yes1",               "emotion", EMOTIONS_DATASET, "Long affirmative; nodding to confirm.", "agreement", ("yes", "confirm", "yeah")),
    MotionClip("yes_sad1",           "emotion", EMOTIONS_DATASET, "Melancholic or resigned 'yes'.", "agreement", ("sad_yes", "resigned_yes")),
)


# ────────────────────────────── DANCES (19) ──────────────────────────────
# The Pollen dances library ships 19 BPM-locked recorded choreographies.
DANCE_CLIPS: tuple[MotionClip, ...] = (
    MotionClip("chicken_peck",         "dance", DANCES_DATASET, "Sharp forward chicken-like pecking motion.", "rhythmic", ("peck",)),
    MotionClip("chin_lead",            "dance", DANCES_DATASET, "Forward motion led by the chin, combining translation and pitch.", "smooth", ()),
    MotionClip("dizzy_spin",           "dance", DANCES_DATASET, "Circular dizzy head motion combining roll and pitch.", "spin", ("spin", "dizzy")),
    MotionClip("grid_snap",            "dance", DANCES_DATASET, "Robotic grid-snapping motion using square waveforms.", "robotic", ("snap", "robot_dance")),
    MotionClip("groovy_sway_and_roll", "dance", DANCES_DATASET, "Side-to-side sway plus a corresponding roll for a groovy effect.", "smooth", ("groovy", "sway")),
    MotionClip("head_tilt_roll",       "dance", DANCES_DATASET, "Continuous ear-to-shoulder head roll.", "smooth", ("tilt", "roll")),
    MotionClip("interwoven_spirals",   "dance", DANCES_DATASET, "Complex spiral motion using three axes at different frequencies.", "complex", ("spiral",)),
    MotionClip("jackson_square",       "dance", DANCES_DATASET, "5-point rectangle path with sharp twitches at each checkpoint.", "rhythmic", ("square", "jackson")),
    MotionClip("neck_recoil",          "dance", DANCES_DATASET, "Quick transient backward neck recoil.", "rhythmic", ("recoil",)),
    MotionClip("pendulum_swing",       "dance", DANCES_DATASET, "Smooth pendulum-like swing using a roll motion.", "smooth", ("pendulum",)),
    MotionClip("polyrhythm_combo",     "dance", DANCES_DATASET, "3-beat sway against a 2-beat nod for a polyrhythmic feel.", "complex", ("polyrhythm",)),
    MotionClip("sharp_side_tilt",      "dance", DANCES_DATASET, "Sharp quick side-to-side tilt using a triangle waveform.", "rhythmic", ("sharp_tilt",)),
    MotionClip("side_glance_flick",    "dance", DANCES_DATASET, "Quick glance to the side that holds then returns.", "reactive", ("glance", "flick")),
    MotionClip("side_peekaboo",        "dance", DANCES_DATASET, "Multi-stage peekaboo performance hiding and peeking to each side.", "playful", ("peekaboo",)),
    MotionClip("side_to_side_sway",    "dance", DANCES_DATASET, "Smooth side-to-side sway of the entire head.", "smooth", ("sway_sides",)),
    MotionClip("simple_nod",           "dance", DANCES_DATASET, "Simple continuous up-and-down nodding.", "smooth", ("nod_dance",)),
    MotionClip("stumble_and_recover",  "dance", DANCES_DATASET, "Simulated stumble and recovery across multiple axes.", "playful", ("stumble",)),
    MotionClip("uh_huh_tilt",          "dance", DANCES_DATASET, "Combined roll-and-pitch uh-huh gesture of agreement.", "rhythmic", ("uh_huh",)),
    MotionClip("yeah_nod",             "dance", DANCES_DATASET, "Emphatic two-part yeah nod using transient motions.", "rhythmic", ("yeah",)),
)


ALL_CLIPS: tuple[MotionClip, ...] = EMOTION_CLIPS + DANCE_CLIPS


def _build_name_index() -> dict[str, MotionClip]:
    idx: dict[str, MotionClip] = {}
    for clip in ALL_CLIPS:
        idx[clip.name.lower()] = clip
        for alias in clip.aliases:
            # Aliases may collide (e.g. "dance" would map to dance1 dance2 dance3).
            # First write wins, subsequent alias registrations are ignored so the
            # canonical-name lookup stays deterministic.
            idx.setdefault(alias.lower(), clip)
    return idx


_NAME_INDEX: dict[str, MotionClip] = _build_name_index()


def list_clips(kind: Optional[MotionKind] = None) -> list[MotionClip]:
    if kind is None:
        return list(ALL_CLIPS)
    return [c for c in ALL_CLIPS if c.kind == kind]


def _normalize(q: str) -> str:
    """Lowercase + strip + collapse whitespace/hyphens to underscores so
    ``thank you`` and ``thank-you`` both match the ``thank_you`` alias."""
    return "_".join(q.strip().lower().replace("-", " ").split())


def get_clip(name_or_alias: str) -> Optional[MotionClip]:
    """Exact-or-alias lookup. Case insensitive; spaces/hyphens become underscores."""
    if not name_or_alias:
        return None
    return _NAME_INDEX.get(_normalize(name_or_alias))


def resolve_motion(query: str, *, kind: Optional[MotionKind] = None) -> Optional[MotionClip]:
    """
    Best-effort resolver for free-form LLM emotion tags.

    Order:
    1. Exact canonical / alias match.
    2. Substring match on name.
    3. Substring match on description keywords.
    4. None.
    """
    if not query:
        return None
    q = _normalize(query)
    # 1. Exact normalized name / alias match
    hit = _NAME_INDEX.get(q)
    if hit and (kind is None or hit.kind == kind):
        return hit
    # 2. Name substring
    for clip in ALL_CLIPS:
        if kind and clip.kind != kind:
            continue
        if q in clip.name.lower():
            return clip
    # 3. Alias substring (compare against normalized aliases)
    for clip in ALL_CLIPS:
        if kind and clip.kind != kind:
            continue
        if any(q in _normalize(a) for a in clip.aliases):
            return clip
    # 4. Description contains the query (raw query, not normalized — words may
    # contain spaces here)
    raw = query.strip().lower()
    for clip in ALL_CLIPS:
        if kind and clip.kind != kind:
            continue
        if raw in clip.description.lower():
            return clip
    return None


def categories() -> dict[str, list[MotionClip]]:
    """Clips grouped by category for UI display."""
    out: dict[str, list[MotionClip]] = {}
    for clip in ALL_CLIPS:
        out.setdefault(clip.category or "other", []).append(clip)
    return out


def clip_to_dict(clip: MotionClip) -> dict:
    return {
        "name": clip.name,
        "kind": clip.kind,
        "dataset": clip.dataset,
        "description": clip.description,
        "category": clip.category,
        "aliases": list(clip.aliases),
    }
