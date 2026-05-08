"""Character brand kits — per-character visual style presets.

Each kit drives:
  - Palette (primary/secondary/optional third accent)
  - Font roles (hook/body/stat → font_style key consumed by renderer)
  - Image treatments to apply in the PIL renderer (duotone, grain, vignette, etc.)
  - Sticker style category (chaos, noir, heroic, horror, neon, minimal)
  - Hook-style bias for the prompt generator
  - Text effects to layer (outline, gradient_fill, rotation, redacted, neon_glow)
  - Default layout rotation

The service exposes:
  get_brand_kit(name, universe, franchise, tags) -> dict
  enrich_brand_kit(base_kit, carousel_id) -> dict   # per-carousel palette nudge

Lookup priority: normalized character name -> franchise -> universe default ->
top-level `_default_*` -> `_default_film`.
"""

from __future__ import annotations

import colorsys
import re
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Slug normalization
# ---------------------------------------------------------------------------


def normalize_slug(text: str) -> str:
    if not text:
        return ""
    t = text.lower().strip()
    t = re.sub(r"[^a-z0-9]+", "_", t)
    t = re.sub(r"_+", "_", t).strip("_")
    return t


# ---------------------------------------------------------------------------
# Brand kit registry
# ---------------------------------------------------------------------------

# Template field docs below are inline; every kit must provide at minimum:
#   vibe, palette, fonts{hook,body,stat}, image_treatments,
#   treatment_params, sticker_style, hook_bias, text_effects,
#   default_layout_rotation.

_KIT_BATMAN_NOIR: Dict[str, Any] = {
    "name": "Batman Noir",
    "vibe": "noir",
    "palette": {"primary": "#FFD54F", "secondary": "#1E3A8A", "accent_neon": "#0B1120"},
    "fonts": {"hook": "display-block", "body": "display-body", "stat": "display-stat"},
    "image_treatments": ["duotone", "vignette", "grain"],
    "treatment_params": {
        "duotone": {"shadow_hex": "#0B1120", "highlight_hex": "#FFD54F"},
        "vignette": {"intensity": 0.65},
        "grain": {"amount": 0.06},
    },
    "sticker_style": "noir",
    "hook_bias": ["reveal", "hot_take", "contrarian_correction"],
    "text_effects": ["outline"],
    "default_layout_rotation": ["center", "bottom_boxed", "corner_tl", "stat_hero", "full_overlay", "quote_card"],
}

_KIT_SUPERMAN_CLASSIC: Dict[str, Any] = {
    "name": "Superman Classic",
    "vibe": "heroic",
    "palette": {"primary": "#E53935", "secondary": "#1E40AF", "accent_neon": "#FFD54F"},
    "fonts": {"hook": "display-hook", "body": "display-body", "stat": "display-stat"},
    "image_treatments": ["cinematic", "grain"],
    "treatment_params": {"grain": {"amount": 0.04}},
    "sticker_style": "heroic",
    "hook_bias": ["superlative", "question", "numbered_list"],
    "text_effects": ["outline"],
    "default_layout_rotation": ["center", "top_boxed", "stat_hero", "bottom_boxed", "quote_card", "corner_br"],
}

_KIT_SPIDER_MAN_COMIC: Dict[str, Any] = {
    "name": "Spider-Man Comic",
    "vibe": "comic",
    "palette": {"primary": "#D32F2F", "secondary": "#1565C0", "accent_neon": "#FDD835"},
    "fonts": {"hook": "display-shout", "body": "display-body", "stat": "display-mono"},
    "image_treatments": ["halftone", "grain"],
    "treatment_params": {"grain": {"amount": 0.05}},
    "sticker_style": "heroic",
    "hook_bias": ["question", "story_opener", "reveal"],
    "text_effects": ["outline"],
    "default_layout_rotation": ["stat_hero", "center", "split_bottom", "diagonal", "full_overlay", "corner_tl"],
}

_KIT_IRON_MAN_TECH: Dict[str, Any] = {
    "name": "Iron Man Tech",
    "vibe": "tech",
    "palette": {"primary": "#FFB300", "secondary": "#B71C1C", "accent_neon": "#00E5FF"},
    "fonts": {"hook": "display-scifi", "body": "display-body", "stat": "display-mono"},
    "image_treatments": ["cinematic", "split_tone"],
    "treatment_params": {"split_tone": {"warm_hex": "#FFB300", "cool_hex": "#0D47A1"}},
    "sticker_style": "tech",
    "hook_bias": ["numbered_list", "hot_take", "superlative"],
    "text_effects": ["neon_glow"],
    "default_layout_rotation": ["center", "corner_br", "stat_hero", "diagonal", "full_overlay", "top_boxed"],
}

_KIT_THOR_NORDIC: Dict[str, Any] = {
    "name": "Thor Nordic",
    "vibe": "mythic",
    "palette": {"primary": "#E0E0E0", "secondary": "#1A237E", "accent_neon": "#FFC107"},
    "fonts": {"hook": "display-hook", "body": "display-body", "stat": "display-block"},
    "image_treatments": ["cinematic", "vignette"],
    "treatment_params": {"vignette": {"intensity": 0.55}},
    "sticker_style": "heroic",
    "hook_bias": ["story_opener", "superlative", "reveal"],
    "text_effects": ["outline"],
    "default_layout_rotation": ["stat_hero", "center", "bottom_boxed", "quote_card", "split_top", "corner_tl"],
}

_KIT_CAPTAIN_AMERICA_PATRIOT: Dict[str, Any] = {
    "name": "Captain America Patriot",
    "vibe": "heroic",
    "palette": {"primary": "#1565C0", "secondary": "#C62828", "accent_neon": "#FFFFFF"},
    "fonts": {"hook": "display-block", "body": "display-body", "stat": "display-stat"},
    "image_treatments": ["desaturate", "grain"],
    "treatment_params": {"desaturate": {"amount": 0.4}, "grain": {"amount": 0.05}},
    "sticker_style": "heroic",
    "hook_bias": ["numbered_list", "superlative", "question"],
    "text_effects": ["outline"],
    "default_layout_rotation": ["top_boxed", "center", "bottom_boxed", "stat_hero", "corner_br", "full_overlay"],
}

_KIT_HULK_RAGE: Dict[str, Any] = {
    "name": "Hulk Rage",
    "vibe": "chaos",
    "palette": {"primary": "#43A047", "secondary": "#3E2723", "accent_neon": "#FFEB3B"},
    "fonts": {"hook": "display-shout", "body": "display-body", "stat": "display-block"},
    "image_treatments": ["duotone", "grain"],
    "treatment_params": {
        "duotone": {"shadow_hex": "#1B5E20", "highlight_hex": "#CDDC39"},
        "grain": {"amount": 0.08},
    },
    "sticker_style": "chaos",
    "hook_bias": ["hot_take", "superlative", "story_opener"],
    "text_effects": ["outline", "rotation"],
    "default_layout_rotation": ["stat_hero", "full_overlay", "diagonal", "center", "split_bottom", "corner_tl"],
}

_KIT_WONDER_WOMAN_HEROIC: Dict[str, Any] = {
    "name": "Wonder Woman Heroic",
    "vibe": "heroic",
    "palette": {"primary": "#D84315", "secondary": "#FFD600", "accent_neon": "#1565C0"},
    "fonts": {"hook": "display-hook", "body": "display-body", "stat": "display-stat"},
    "image_treatments": ["cinematic"],
    "treatment_params": {},
    "sticker_style": "heroic",
    "hook_bias": ["question", "superlative", "reveal"],
    "text_effects": ["outline"],
    "default_layout_rotation": ["center", "stat_hero", "quote_card", "bottom_boxed", "diagonal", "corner_br"],
}

_KIT_JOKER_CHAOS: Dict[str, Any] = {
    "name": "Joker Chaos",
    "vibe": "chaos",
    "palette": {"primary": "#7B2CBF", "secondary": "#80ED99", "accent_neon": "#C77DFF"},
    "fonts": {"hook": "display-cyberpunk", "body": "display-hot", "stat": "display-mono"},
    "image_treatments": ["duotone", "grain", "radial_blur_bg"],
    "treatment_params": {
        "duotone": {"shadow_hex": "#240046", "highlight_hex": "#80ED99"},
        "grain": {"amount": 0.08},
    },
    "sticker_style": "chaos",
    "hook_bias": ["hot_take", "contrarian_correction", "story_opener"],
    "text_effects": ["rotation", "outline"],
    "default_layout_rotation": ["diagonal", "center", "full_overlay", "corner_tl", "split_bottom", "quote_card"],
}

_KIT_THANOS_COSMIC: Dict[str, Any] = {
    "name": "Thanos Cosmic",
    "vibe": "cosmic",
    "palette": {"primary": "#8E24AA", "secondary": "#FFC107", "accent_neon": "#00BCD4"},
    "fonts": {"hook": "display-scifi", "body": "display-body", "stat": "display-block"},
    "image_treatments": ["split_tone", "grain"],
    "treatment_params": {
        "split_tone": {"warm_hex": "#FFC107", "cool_hex": "#6A1B9A"},
        "grain": {"amount": 0.05},
    },
    "sticker_style": "cosmic",
    "hook_bias": ["superlative", "reveal", "hot_take"],
    "text_effects": ["neon_glow", "outline"],
    "default_layout_rotation": ["stat_hero", "center", "full_overlay", "quote_card", "corner_br", "bottom_boxed"],
}

_KIT_DARTH_VADER_NOIR: Dict[str, Any] = {
    "name": "Darth Vader Noir",
    "vibe": "noir",
    "palette": {"primary": "#D50000", "secondary": "#212121", "accent_neon": "#FFFFFF"},
    "fonts": {"hook": "display-block", "body": "display-body", "stat": "display-stat"},
    "image_treatments": ["duotone", "vignette", "grain"],
    "treatment_params": {
        "duotone": {"shadow_hex": "#000000", "highlight_hex": "#D50000"},
        "vignette": {"intensity": 0.7},
        "grain": {"amount": 0.05},
    },
    "sticker_style": "noir",
    "hook_bias": ["reveal", "hot_take", "superlative"],
    "text_effects": ["outline"],
    "default_layout_rotation": ["center", "corner_tl", "full_overlay", "bottom_boxed", "stat_hero", "quote_card"],
}

_KIT_VOLDEMORT_GOTHIC: Dict[str, Any] = {
    "name": "Voldemort Gothic",
    "vibe": "gothic",
    "palette": {"primary": "#4E342E", "secondary": "#388E3C", "accent_neon": "#B71C1C"},
    "fonts": {"hook": "display-gothic", "body": "display-body", "stat": "display-stat"},
    "image_treatments": ["duotone", "vignette", "grain"],
    "treatment_params": {
        "duotone": {"shadow_hex": "#1B5E20", "highlight_hex": "#4E342E"},
        "vignette": {"intensity": 0.72},
        "grain": {"amount": 0.07},
    },
    "sticker_style": "gothic",
    "hook_bias": ["reveal", "story_opener", "contrarian_correction"],
    "text_effects": ["outline"],
    "default_layout_rotation": ["center", "quote_card", "full_overlay", "corner_tl", "stat_hero", "bottom_boxed"],
}

_KIT_LOKI_TRICKSTER: Dict[str, Any] = {
    "name": "Loki Trickster",
    "vibe": "trickster",
    "palette": {"primary": "#43A047", "secondary": "#F9A825", "accent_neon": "#FFFFFF"},
    "fonts": {"hook": "display-hook", "body": "display-body", "stat": "display-mono"},
    "image_treatments": ["cinematic", "grain"],
    "treatment_params": {"grain": {"amount": 0.05}},
    "sticker_style": "chaos",
    "hook_bias": ["contrarian_correction", "reveal", "question"],
    "text_effects": ["rotation"],
    "default_layout_rotation": ["diagonal", "split_bottom", "center", "corner_br", "quote_card", "full_overlay"],
}

_KIT_MAGNETO_REGAL: Dict[str, Any] = {
    "name": "Magneto Regal",
    "vibe": "regal",
    "palette": {"primary": "#6A1B9A", "secondary": "#C0392B", "accent_neon": "#EEEEEE"},
    "fonts": {"hook": "display-block", "body": "display-body", "stat": "display-stat"},
    "image_treatments": ["duotone", "vignette"],
    "treatment_params": {"duotone": {"shadow_hex": "#311B92", "highlight_hex": "#EEEEEE"}},
    "sticker_style": "noir",
    "hook_bias": ["reveal", "contrarian_correction", "superlative"],
    "text_effects": ["outline"],
    "default_layout_rotation": ["center", "bottom_boxed", "corner_tl", "stat_hero", "full_overlay", "quote_card"],
}

_KIT_SAURON_DOOM: Dict[str, Any] = {
    "name": "Sauron Doom",
    "vibe": "doom",
    "palette": {"primary": "#BF360C", "secondary": "#212121", "accent_neon": "#FFB300"},
    "fonts": {"hook": "display-gothic", "body": "display-body", "stat": "display-block"},
    "image_treatments": ["duotone", "vignette", "grain"],
    "treatment_params": {
        "duotone": {"shadow_hex": "#000000", "highlight_hex": "#BF360C"},
        "vignette": {"intensity": 0.72},
    },
    "sticker_style": "gothic",
    "hook_bias": ["reveal", "story_opener", "superlative"],
    "text_effects": ["outline"],
    "default_layout_rotation": ["center", "full_overlay", "stat_hero", "bottom_boxed", "quote_card", "corner_tl"],
}

# --- Anti-heroes ---

_KIT_WOLVERINE_GRIT: Dict[str, Any] = {
    "name": "Wolverine Grit",
    "vibe": "grit",
    "palette": {"primary": "#FBC02D", "secondary": "#263238", "accent_neon": "#C62828"},
    "fonts": {"hook": "display-shout", "body": "display-body", "stat": "display-stat"},
    "image_treatments": ["desaturate", "grain"],
    "treatment_params": {"desaturate": {"amount": 0.35}, "grain": {"amount": 0.07}},
    "sticker_style": "grit",
    "hook_bias": ["hot_take", "story_opener", "reveal"],
    "text_effects": ["outline", "rotation"],
    "default_layout_rotation": ["diagonal", "split_bottom", "center", "corner_tl", "stat_hero", "full_overlay"],
}

_KIT_DEADPOOL_META: Dict[str, Any] = {
    "name": "Deadpool Meta",
    "vibe": "meta",
    "palette": {"primary": "#E53935", "secondary": "#212121", "accent_neon": "#FDD835"},
    "fonts": {"hook": "display-hot", "body": "display-body", "stat": "display-mono"},
    "image_treatments": ["halftone", "grain"],
    "treatment_params": {"grain": {"amount": 0.06}},
    "sticker_style": "chaos",
    "hook_bias": ["hot_take", "question", "contrarian_correction"],
    "text_effects": ["rotation", "outline"],
    "default_layout_rotation": ["split_top", "diagonal", "corner_br", "center", "full_overlay", "quote_card"],
}

_KIT_PUNISHER_NOIR: Dict[str, Any] = {
    "name": "Punisher Noir",
    "vibe": "noir",
    "palette": {"primary": "#FFFFFF", "secondary": "#212121", "accent_neon": "#D32F2F"},
    "fonts": {"hook": "display-block", "body": "display-body", "stat": "display-stat"},
    "image_treatments": ["duotone", "vignette", "grain"],
    "treatment_params": {
        "duotone": {"shadow_hex": "#000000", "highlight_hex": "#FFFFFF"},
        "vignette": {"intensity": 0.7},
    },
    "sticker_style": "noir",
    "hook_bias": ["reveal", "story_opener", "hot_take"],
    "text_effects": ["outline"],
    "default_layout_rotation": ["center", "bottom_boxed", "corner_tl", "stat_hero", "full_overlay", "quote_card"],
}

_KIT_VENOM_BLACK: Dict[str, Any] = {
    "name": "Venom Black",
    "vibe": "dark",
    "palette": {"primary": "#FFFFFF", "secondary": "#000000", "accent_neon": "#D32F2F"},
    "fonts": {"hook": "display-horror", "body": "display-body", "stat": "display-block"},
    "image_treatments": ["duotone", "grain"],
    "treatment_params": {
        "duotone": {"shadow_hex": "#000000", "highlight_hex": "#FFFFFF"},
        "grain": {"amount": 0.07},
    },
    "sticker_style": "horror",
    "hook_bias": ["hot_take", "reveal", "story_opener"],
    "text_effects": ["outline", "rotation"],
    "default_layout_rotation": ["center", "corner_tl", "full_overlay", "diagonal", "stat_hero", "quote_card"],
}

# --- Fantasy ---

_KIT_GANDALF_PARCHMENT: Dict[str, Any] = {
    "name": "Gandalf Parchment",
    "vibe": "fantasy",
    "palette": {"primary": "#8D6E63", "secondary": "#FFD54F", "accent_neon": "#1B5E20"},
    "fonts": {"hook": "display-serif", "body": "display-body", "stat": "display-slab"},
    "image_treatments": ["desaturate", "grain", "vignette"],
    "treatment_params": {"desaturate": {"amount": 0.3}, "grain": {"amount": 0.06}, "vignette": {"intensity": 0.5}},
    "sticker_style": "parchment",
    "hook_bias": ["story_opener", "reveal", "question"],
    "text_effects": ["outline"],
    "default_layout_rotation": ["quote_card", "center", "top_boxed", "stat_hero", "bottom_boxed", "full_overlay"],
}

_KIT_DAENERYS_FIRE: Dict[str, Any] = {
    "name": "Daenerys Fire",
    "vibe": "fire",
    "palette": {"primary": "#FF6F00", "secondary": "#B71C1C", "accent_neon": "#FFF176"},
    "fonts": {"hook": "display-serif", "body": "display-body", "stat": "display-block"},
    "image_treatments": ["split_tone", "grain"],
    "treatment_params": {"split_tone": {"warm_hex": "#FF6F00", "cool_hex": "#1A237E"}},
    "sticker_style": "heroic",
    "hook_bias": ["superlative", "story_opener", "reveal"],
    "text_effects": ["outline"],
    "default_layout_rotation": ["stat_hero", "center", "quote_card", "full_overlay", "bottom_boxed", "corner_tl"],
}

_KIT_ARYA_SHADOW: Dict[str, Any] = {
    "name": "Arya Shadow",
    "vibe": "shadow",
    "palette": {"primary": "#757575", "secondary": "#212121", "accent_neon": "#F9A825"},
    "fonts": {"hook": "display-serif", "body": "display-body", "stat": "display-stat"},
    "image_treatments": ["desaturate", "vignette", "grain"],
    "treatment_params": {"desaturate": {"amount": 0.5}, "vignette": {"intensity": 0.65}},
    "sticker_style": "noir",
    "hook_bias": ["reveal", "story_opener", "contrarian_correction"],
    "text_effects": ["outline"],
    "default_layout_rotation": ["corner_tl", "center", "bottom_boxed", "diagonal", "full_overlay", "quote_card"],
}

_KIT_FRODO_HUMBLE: Dict[str, Any] = {
    "name": "Frodo Humble",
    "vibe": "humble",
    "palette": {"primary": "#689F38", "secondary": "#6D4C41", "accent_neon": "#FFD54F"},
    "fonts": {"hook": "display-serif", "body": "display-body", "stat": "display-slab"},
    "image_treatments": ["cinematic", "grain"],
    "treatment_params": {"grain": {"amount": 0.05}},
    "sticker_style": "parchment",
    "hook_bias": ["story_opener", "question", "reveal"],
    "text_effects": ["outline"],
    "default_layout_rotation": ["quote_card", "center", "bottom_boxed", "top_boxed", "stat_hero", "split_top"],
}

# --- Sci-fi ---

_KIT_REY_JEDI: Dict[str, Any] = {
    "name": "Rey Jedi",
    "vibe": "jedi",
    "palette": {"primary": "#FFEB3B", "secondary": "#1565C0", "accent_neon": "#ECEFF1"},
    "fonts": {"hook": "display-scifi", "body": "display-body", "stat": "display-mono"},
    "image_treatments": ["cinematic"],
    "treatment_params": {},
    "sticker_style": "heroic",
    "hook_bias": ["superlative", "reveal", "story_opener"],
    "text_effects": ["neon_glow"],
    "default_layout_rotation": ["center", "stat_hero", "bottom_boxed", "quote_card", "corner_br", "full_overlay"],
}

_KIT_CHEWBACCA_WARMTH: Dict[str, Any] = {
    "name": "Chewbacca Warmth",
    "vibe": "warmth",
    "palette": {"primary": "#6D4C41", "secondary": "#F9A825", "accent_neon": "#795548"},
    "fonts": {"hook": "display-block", "body": "display-body", "stat": "display-stat"},
    "image_treatments": ["cinematic", "grain"],
    "treatment_params": {"grain": {"amount": 0.04}},
    "sticker_style": "heroic",
    "hook_bias": ["numbered_list", "question", "story_opener"],
    "text_effects": ["outline"],
    "default_layout_rotation": ["center", "top_boxed", "stat_hero", "bottom_boxed", "quote_card", "corner_br"],
}

_KIT_C3PO_GOLD: Dict[str, Any] = {
    "name": "C-3PO Gold",
    "vibe": "polished",
    "palette": {"primary": "#FFC107", "secondary": "#1A237E", "accent_neon": "#ECEFF1"},
    "fonts": {"hook": "display-scifi", "body": "display-body", "stat": "display-mono"},
    "image_treatments": ["cinematic"],
    "treatment_params": {},
    "sticker_style": "tech",
    "hook_bias": ["numbered_list", "question", "superlative"],
    "text_effects": ["outline", "neon_glow"],
    "default_layout_rotation": ["stat_hero", "center", "corner_br", "top_boxed", "bottom_boxed", "quote_card"],
}

_KIT_GROOT_NATURE: Dict[str, Any] = {
    "name": "Groot Nature",
    "vibe": "nature",
    "palette": {"primary": "#558B2F", "secondary": "#3E2723", "accent_neon": "#FDD835"},
    "fonts": {"hook": "display-hook", "body": "display-body", "stat": "display-block"},
    "image_treatments": ["cinematic", "grain"],
    "treatment_params": {"grain": {"amount": 0.05}},
    "sticker_style": "heroic",
    "hook_bias": ["question", "story_opener", "superlative"],
    "text_effects": ["outline"],
    "default_layout_rotation": ["center", "stat_hero", "top_boxed", "bottom_boxed", "corner_br", "quote_card"],
}

# --- Anime ---

_KIT_GOKU_SAIYAN: Dict[str, Any] = {
    "name": "Goku Saiyan",
    "vibe": "anime_power",
    "palette": {"primary": "#FFEB3B", "secondary": "#D84315", "accent_neon": "#1E88E5"},
    "fonts": {"hook": "display-shout", "body": "display-body", "stat": "display-block"},
    "image_treatments": ["halftone", "grain"],
    "treatment_params": {"grain": {"amount": 0.05}},
    "sticker_style": "anime",
    "hook_bias": ["superlative", "comparison", "reveal"],
    "text_effects": ["outline", "neon_glow"],
    "default_layout_rotation": ["stat_hero", "diagonal", "center", "full_overlay", "split_top", "corner_tl"],
}

_KIT_NARUTO_NINJA: Dict[str, Any] = {
    "name": "Naruto Ninja",
    "vibe": "anime",
    "palette": {"primary": "#FF9800", "secondary": "#212121", "accent_neon": "#1E88E5"},
    "fonts": {"hook": "display-shout", "body": "display-body", "stat": "display-mono"},
    "image_treatments": ["halftone"],
    "treatment_params": {},
    "sticker_style": "anime",
    "hook_bias": ["story_opener", "question", "comparison"],
    "text_effects": ["outline"],
    "default_layout_rotation": ["center", "split_bottom", "stat_hero", "diagonal", "corner_tl", "full_overlay"],
}

_KIT_LUFFY_PIRATE: Dict[str, Any] = {
    "name": "Luffy Pirate",
    "vibe": "anime",
    "palette": {"primary": "#D32F2F", "secondary": "#FDD835", "accent_neon": "#1E88E5"},
    "fonts": {"hook": "display-shout", "body": "display-body", "stat": "display-block"},
    "image_treatments": ["halftone", "grain"],
    "treatment_params": {"grain": {"amount": 0.05}},
    "sticker_style": "anime",
    "hook_bias": ["superlative", "story_opener", "hot_take"],
    "text_effects": ["outline", "rotation"],
    "default_layout_rotation": ["diagonal", "stat_hero", "center", "full_overlay", "split_bottom", "corner_br"],
}

_KIT_EREN_TITAN: Dict[str, Any] = {
    "name": "Eren Titan",
    "vibe": "anime_dark",
    "palette": {"primary": "#C0392B", "secondary": "#3E2723", "accent_neon": "#FFFFFF"},
    "fonts": {"hook": "display-gothic", "body": "display-body", "stat": "display-block"},
    "image_treatments": ["duotone", "grain", "vignette"],
    "treatment_params": {
        "duotone": {"shadow_hex": "#3E2723", "highlight_hex": "#C0392B"},
        "grain": {"amount": 0.07},
        "vignette": {"intensity": 0.6},
    },
    "sticker_style": "horror",
    "hook_bias": ["reveal", "story_opener", "contrarian_correction"],
    "text_effects": ["outline"],
    "default_layout_rotation": ["center", "full_overlay", "stat_hero", "corner_tl", "bottom_boxed", "quote_card"],
}

# --- Horror ---

_KIT_PENNYWISE_TERROR: Dict[str, Any] = {
    "name": "Pennywise Terror",
    "vibe": "horror",
    "palette": {"primary": "#EC407A", "secondary": "#EFEBE9", "accent_neon": "#D32F2F"},
    "fonts": {"hook": "display-horror", "body": "display-body", "stat": "display-mono"},
    "image_treatments": ["grain", "vignette", "desaturate"],
    "treatment_params": {
        "grain": {"amount": 0.1},
        "vignette": {"intensity": 0.72},
        "desaturate": {"amount": 0.25},
    },
    "sticker_style": "horror",
    "hook_bias": ["reveal", "hot_take", "question"],
    "text_effects": ["outline", "rotation"],
    "default_layout_rotation": ["center", "diagonal", "corner_tl", "full_overlay", "stat_hero", "quote_card"],
}

_KIT_FREDDY_NIGHTMARE: Dict[str, Any] = {
    "name": "Freddy Nightmare",
    "vibe": "horror",
    "palette": {"primary": "#D32F2F", "secondary": "#2E7D32", "accent_neon": "#FDD835"},
    "fonts": {"hook": "display-horror", "body": "display-body", "stat": "display-block"},
    "image_treatments": ["grain", "vignette"],
    "treatment_params": {
        "grain": {"amount": 0.1},
        "vignette": {"intensity": 0.72},
    },
    "sticker_style": "horror",
    "hook_bias": ["hot_take", "reveal", "story_opener"],
    "text_effects": ["rotation", "outline"],
    "default_layout_rotation": ["diagonal", "center", "corner_tl", "full_overlay", "split_top", "quote_card"],
}

# --- Universe defaults ---

_KIT_DEFAULT_MARVEL: Dict[str, Any] = {
    "name": "Marvel Default",
    "vibe": "heroic",
    "palette": {"primary": "#E23636", "secondary": "#202020", "accent_neon": "#F0E847"},
    "fonts": {"hook": "display-hook", "body": "display-body", "stat": "display-stat"},
    "image_treatments": ["cinematic", "grain"],
    "treatment_params": {"grain": {"amount": 0.04}},
    "sticker_style": "heroic",
    "hook_bias": ["numbered_list", "story_opener", "question"],
    "text_effects": ["outline"],
    "default_layout_rotation": ["center", "bottom_boxed", "stat_hero", "top_boxed", "full_overlay", "quote_card"],
}

_KIT_DEFAULT_DC: Dict[str, Any] = {
    "name": "DC Default",
    "vibe": "heroic",
    "palette": {"primary": "#0047AB", "secondary": "#FFD700", "accent_neon": "#FFFFFF"},
    "fonts": {"hook": "display-hook", "body": "display-body", "stat": "display-stat"},
    "image_treatments": ["cinematic", "vignette"],
    "treatment_params": {"vignette": {"intensity": 0.5}},
    "sticker_style": "heroic",
    "hook_bias": ["reveal", "numbered_list", "superlative"],
    "text_effects": ["outline"],
    "default_layout_rotation": ["center", "stat_hero", "bottom_boxed", "corner_br", "full_overlay", "quote_card"],
}

_KIT_DEFAULT_STAR_WARS: Dict[str, Any] = {
    "name": "Star Wars Default",
    "vibe": "scifi",
    "palette": {"primary": "#FFC600", "secondary": "#212121", "accent_neon": "#E60023"},
    "fonts": {"hook": "display-scifi", "body": "display-body", "stat": "display-mono"},
    "image_treatments": ["cinematic", "grain"],
    "treatment_params": {"grain": {"amount": 0.05}},
    "sticker_style": "tech",
    "hook_bias": ["story_opener", "reveal", "numbered_list"],
    "text_effects": ["outline", "neon_glow"],
    "default_layout_rotation": ["center", "stat_hero", "bottom_boxed", "corner_tl", "full_overlay", "quote_card"],
}

_KIT_DEFAULT_ANIME: Dict[str, Any] = {
    "name": "Anime Default",
    "vibe": "anime",
    "palette": {"primary": "#FF6F91", "secondary": "#1E88E5", "accent_neon": "#FDD835"},
    "fonts": {"hook": "display-shout", "body": "display-body", "stat": "display-mono"},
    "image_treatments": ["halftone", "grain"],
    "treatment_params": {"grain": {"amount": 0.05}},
    "sticker_style": "anime",
    "hook_bias": ["superlative", "story_opener", "comparison"],
    "text_effects": ["outline"],
    "default_layout_rotation": ["stat_hero", "center", "diagonal", "full_overlay", "split_bottom", "corner_br"],
}

_KIT_DEFAULT_FANTASY: Dict[str, Any] = {
    "name": "Fantasy Default",
    "vibe": "fantasy",
    "palette": {"primary": "#6D4C41", "secondary": "#2E7D32", "accent_neon": "#FFD54F"},
    "fonts": {"hook": "display-serif", "body": "display-body", "stat": "display-slab"},
    "image_treatments": ["cinematic", "grain", "vignette"],
    "treatment_params": {"grain": {"amount": 0.05}, "vignette": {"intensity": 0.55}},
    "sticker_style": "parchment",
    "hook_bias": ["story_opener", "reveal", "question"],
    "text_effects": ["outline"],
    "default_layout_rotation": ["quote_card", "center", "stat_hero", "top_boxed", "bottom_boxed", "full_overlay"],
}

_KIT_DEFAULT_SCIFI: Dict[str, Any] = {
    "name": "Sci-Fi Default",
    "vibe": "scifi",
    "palette": {"primary": "#00BCD4", "secondary": "#0D47A1", "accent_neon": "#FFEB3B"},
    "fonts": {"hook": "display-scifi", "body": "display-body", "stat": "display-mono"},
    "image_treatments": ["split_tone", "grain"],
    "treatment_params": {"split_tone": {"warm_hex": "#FFEB3B", "cool_hex": "#0D47A1"}},
    "sticker_style": "tech",
    "hook_bias": ["numbered_list", "superlative", "question"],
    "text_effects": ["neon_glow", "outline"],
    "default_layout_rotation": ["center", "stat_hero", "corner_br", "full_overlay", "diagonal", "quote_card"],
}

_KIT_DEFAULT_TV: Dict[str, Any] = {
    "name": "TV Default",
    "vibe": "cinematic",
    "palette": {"primary": "#FB8C00", "secondary": "#3949AB", "accent_neon": "#F06292"},
    "fonts": {"hook": "display-hook", "body": "display-body", "stat": "display-stat"},
    "image_treatments": ["cinematic", "grain"],
    "treatment_params": {"grain": {"amount": 0.04}},
    "sticker_style": "minimal",
    "hook_bias": ["reveal", "story_opener", "question"],
    "text_effects": ["outline"],
    "default_layout_rotation": ["center", "bottom_boxed", "top_boxed", "stat_hero", "quote_card", "corner_br"],
}

_KIT_DEFAULT_FILM: Dict[str, Any] = {
    "name": "Film Default",
    "vibe": "cinematic",
    "palette": {"primary": "#B71C1C", "secondary": "#212121", "accent_neon": "#FDD835"},
    "fonts": {"hook": "display-hook", "body": "display-body", "stat": "display-stat"},
    "image_treatments": ["cinematic", "grain", "vignette"],
    "treatment_params": {"grain": {"amount": 0.05}, "vignette": {"intensity": 0.5}},
    "sticker_style": "minimal",
    "hook_bias": ["reveal", "story_opener", "numbered_list"],
    "text_effects": ["outline"],
    "default_layout_rotation": ["center", "stat_hero", "bottom_boxed", "top_boxed", "quote_card", "full_overlay"],
}


BRAND_KITS: Dict[str, Dict[str, Any]] = {
    # Heroes
    "batman":               _KIT_BATMAN_NOIR,
    "bruce_wayne":          _KIT_BATMAN_NOIR,
    "superman":             _KIT_SUPERMAN_CLASSIC,
    "clark_kent":           _KIT_SUPERMAN_CLASSIC,
    "wonder_woman":         _KIT_WONDER_WOMAN_HEROIC,
    "diana_prince":         _KIT_WONDER_WOMAN_HEROIC,
    "spider_man":           _KIT_SPIDER_MAN_COMIC,
    "peter_parker":         _KIT_SPIDER_MAN_COMIC,
    "spiderman":            _KIT_SPIDER_MAN_COMIC,
    "captain_america":      _KIT_CAPTAIN_AMERICA_PATRIOT,
    "steve_rogers":         _KIT_CAPTAIN_AMERICA_PATRIOT,
    "thor":                 _KIT_THOR_NORDIC,
    "iron_man":             _KIT_IRON_MAN_TECH,
    "tony_stark":           _KIT_IRON_MAN_TECH,
    "ironman":              _KIT_IRON_MAN_TECH,
    "hulk":                 _KIT_HULK_RAGE,
    "bruce_banner":         _KIT_HULK_RAGE,

    # Villains
    "joker":                _KIT_JOKER_CHAOS,
    "thanos":               _KIT_THANOS_COSMIC,
    "darth_vader":          _KIT_DARTH_VADER_NOIR,
    "anakin_skywalker":     _KIT_DARTH_VADER_NOIR,
    "voldemort":            _KIT_VOLDEMORT_GOTHIC,
    "tom_riddle":           _KIT_VOLDEMORT_GOTHIC,
    "loki":                 _KIT_LOKI_TRICKSTER,
    "magneto":              _KIT_MAGNETO_REGAL,
    "erik_lehnsherr":       _KIT_MAGNETO_REGAL,
    "sauron":               _KIT_SAURON_DOOM,

    # Anti-heroes
    "wolverine":            _KIT_WOLVERINE_GRIT,
    "logan":                _KIT_WOLVERINE_GRIT,
    "deadpool":             _KIT_DEADPOOL_META,
    "wade_wilson":          _KIT_DEADPOOL_META,
    "punisher":             _KIT_PUNISHER_NOIR,
    "frank_castle":         _KIT_PUNISHER_NOIR,
    "venom":                _KIT_VENOM_BLACK,
    "eddie_brock":          _KIT_VENOM_BLACK,

    # Fantasy
    "gandalf":              _KIT_GANDALF_PARCHMENT,
    "daenerys_targaryen":   _KIT_DAENERYS_FIRE,
    "daenerys":             _KIT_DAENERYS_FIRE,
    "arya_stark":           _KIT_ARYA_SHADOW,
    "arya":                 _KIT_ARYA_SHADOW,
    "frodo":                _KIT_FRODO_HUMBLE,
    "frodo_baggins":        _KIT_FRODO_HUMBLE,

    # Sci-fi
    "rey":                  _KIT_REY_JEDI,
    "rey_skywalker":        _KIT_REY_JEDI,
    "chewbacca":            _KIT_CHEWBACCA_WARMTH,
    "c_3po":                _KIT_C3PO_GOLD,
    "c3po":                 _KIT_C3PO_GOLD,
    "groot":                _KIT_GROOT_NATURE,

    # Anime
    "goku":                 _KIT_GOKU_SAIYAN,
    "son_goku":             _KIT_GOKU_SAIYAN,
    "naruto":               _KIT_NARUTO_NINJA,
    "naruto_uzumaki":       _KIT_NARUTO_NINJA,
    "luffy":                _KIT_LUFFY_PIRATE,
    "monkey_d_luffy":       _KIT_LUFFY_PIRATE,
    "eren":                 _KIT_EREN_TITAN,
    "eren_yeager":          _KIT_EREN_TITAN,

    # Horror
    "pennywise":            _KIT_PENNYWISE_TERROR,
    "freddy_krueger":       _KIT_FREDDY_NIGHTMARE,

    # Universe defaults
    "_default_marvel":      _KIT_DEFAULT_MARVEL,
    "_default_dc":          _KIT_DEFAULT_DC,
    "_default_star_wars":   _KIT_DEFAULT_STAR_WARS,
    "_default_anime":       _KIT_DEFAULT_ANIME,
    "_default_fantasy":     _KIT_DEFAULT_FANTASY,
    "_default_lotr":        _KIT_DEFAULT_FANTASY,
    "_default_harry_potter": _KIT_DEFAULT_FANTASY,
    "_default_scifi":       _KIT_DEFAULT_SCIFI,
    "_default_gaming":      _KIT_DEFAULT_SCIFI,
    "_default_tv":          _KIT_DEFAULT_TV,
    "_default_film":        _KIT_DEFAULT_FILM,
}


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


def get_brand_kit(
    name: Optional[str] = None,
    universe: Optional[str] = None,
    franchise: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Return the best brand kit for a character.

    Priority: name slug, then franchise slug, then universe default, then film default.
    Always returns a dict (never None).
    """
    # Try exact name slug
    if name:
        slug = normalize_slug(name)
        if slug in BRAND_KITS:
            return BRAND_KITS[slug]
        # Try first word of name (e.g. "Thor Odinson" -> "thor")
        first = slug.split("_")[0]
        if first and first in BRAND_KITS:
            return BRAND_KITS[first]

    # Try franchise
    if franchise:
        fslug = normalize_slug(franchise)
        candidate = f"_default_{fslug}"
        if candidate in BRAND_KITS:
            return BRAND_KITS[candidate]

    # Try universe
    if universe:
        uslug = normalize_slug(universe)
        candidate = f"_default_{uslug}"
        if candidate in BRAND_KITS:
            return BRAND_KITS[candidate]

    # Tag-based fallback
    if tags:
        joined = " ".join(str(t).lower() for t in tags)
        if "horror" in joined:
            return BRAND_KITS["_default_film"]
        if "anime" in joined:
            return BRAND_KITS["_default_anime"]
        if "fantasy" in joined:
            return BRAND_KITS["_default_fantasy"]

    return BRAND_KITS["_default_film"]


# ---------------------------------------------------------------------------
# Per-carousel enrichment — nudge palette so two characters in the same kit
# don't produce identical-looking carousels.
# ---------------------------------------------------------------------------


def _hex_to_rgb(hex_str: str) -> tuple:
    hex_str = hex_str.lstrip("#")
    return (
        int(hex_str[0:2], 16) / 255.0,
        int(hex_str[2:4], 16) / 255.0,
        int(hex_str[4:6], 16) / 255.0,
    )


def _rgb_to_hex(rgb: tuple) -> str:
    return "#{:02X}{:02X}{:02X}".format(
        max(0, min(255, int(rgb[0] * 255))),
        max(0, min(255, int(rgb[1] * 255))),
        max(0, min(255, int(rgb[2] * 255))),
    )


def _hue_shift(hex_str: str, delta_h: float) -> str:
    """Rotate hue by delta_h (0.0-1.0). Keeps saturation + lightness."""
    r, g, b = _hex_to_rgb(hex_str)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    h = (h + delta_h) % 1.0
    nr, ng, nb = colorsys.hls_to_rgb(h, l, s)
    return _rgb_to_hex((nr, ng, nb))


def enrich_brand_kit(base: Dict[str, Any], carousel_id: str) -> Dict[str, Any]:
    """Apply a small deterministic hue nudge so two carousels for the same
    character (or two characters with the same kit) look subtly different.
    """
    import hashlib
    h = hashlib.md5((carousel_id or "x").encode()).digest()
    shift = ((h[0] << 8 | h[1]) % 31 - 15) / 360.0  # +/- 15 degrees
    new_kit = {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v)
               for k, v in base.items()}
    palette = dict(base.get("palette", {}))
    try:
        for key in ("primary", "secondary", "accent_neon"):
            if key in palette and isinstance(palette[key], str):
                palette[key] = _hue_shift(palette[key], shift)
    except (ValueError, TypeError):
        pass
    new_kit["palette"] = palette
    return new_kit


def list_brand_kits() -> List[str]:
    """Return a list of all kit slug keys for debugging/admin."""
    return sorted(BRAND_KITS.keys())
