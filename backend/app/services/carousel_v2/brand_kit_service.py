"""Brand-kit tokenization (carosel.txt §2 'Brand-kit tokenization').

Per-property design tokens (colors, fonts, type scale, spacing, LUT path)
keyed by ``BrandKit.key``. Voice files reference these via the ``brand_kit:``
field. Cinematic post-pass + Jinja2 templates both consume ``BrandKit``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class BrandKit:
    key: str
    primary: str           # hex
    secondary: str
    accent: str
    bg: str
    fg: str
    font_hook: str         # display font for slide-1 hook
    font_headline: str
    font_body: str
    font_accent: str       # comic / quote
    type_scale: tuple[int, ...] = (108, 64, 40, 28, 20)  # hook → headline → sub → body → caption
    spacing_scale: tuple[int, ...] = (4, 8, 16, 24, 48)
    lut_path: Optional[str] = None
    grain_opacity: float = 0.07
    vignette_strength: float = 0.35
    chromatic_aberration_px: int = 2
    bloom_threshold: float = 0.85
    notes: str = ""


def _luts_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "luts"


KITS: dict[str, BrandKit] = {
    "mcu": BrandKit(
        key="mcu",
        primary="#E62429",     # Marvel red
        secondary="#1A1A1A",
        accent="#FFC107",
        bg="#0B0B0B",
        fg="#FFFFFF",
        font_hook="Druk Wide Bold",
        font_headline="Anton",
        font_body="Inter",
        font_accent="Bangers",
        lut_path=str(_luts_dir() / "mcu_teal_orange.cube"),
        grain_opacity=0.06,
        notes="MCU teal-and-orange; orange on key subjects, teal in shadows",
    ),
    "dceu": BrandKit(
        key="dceu",
        primary="#0476F2",
        secondary="#0A0A12",
        accent="#FFD400",
        bg="#06060A",
        fg="#F2F2F2",
        font_hook="Druk Wide Bold",
        font_headline="Anton",
        font_body="Inter",
        font_accent="Bangers",
        lut_path=str(_luts_dir() / "dceu_blue_steel.cube"),
        grain_opacity=0.08,
        vignette_strength=0.45,
    ),
    "the_boys": BrandKit(
        key="the_boys",
        primary="#C81E1E",     # Vought red
        secondary="#1A1A1A",
        accent="#FFFFFF",
        bg="#080808",
        fg="#F8F8F8",
        font_hook="Druk Wide Bold",
        font_headline="Anton",
        font_body="Inter",
        font_accent="Bangers",
        lut_path=str(_luts_dir() / "boys_desat_red_punch.cube"),
        grain_opacity=0.10,
        vignette_strength=0.50,
        notes="desat almost-monochrome with red blood-pop",
    ),
    "snyderverse": BrandKit(
        key="snyderverse",
        primary="#1E3A8A",
        secondary="#000000",
        accent="#9CA3AF",
        bg="#03030A",
        fg="#E5E7EB",
        font_hook="Druk Wide Bold",
        font_headline="Anton",
        font_body="Inter",
        font_accent="Bangers",
        lut_path=str(_luts_dir() / "snyder_blue.cube"),
        grain_opacity=0.09,
        vignette_strength=0.55,
        notes="crushed blacks, biblical blue cast",
    ),
    "dc_gunn": BrandKit(
        key="dc_gunn",
        primary="#1971FF",
        secondary="#101820",
        accent="#FFCB05",
        bg="#0A0F18",
        fg="#FFFFFF",
        font_hook="Druk Wide Bold",
        font_headline="Anton",
        font_body="Inter",
        font_accent="Bangers",
        lut_path=str(_luts_dir() / "dc_gunn_warm.cube"),
        grain_opacity=0.05,
    ),
    "got_hotd": BrandKit(
        key="got_hotd",
        primary="#7B1F1F",
        secondary="#0E0A06",
        accent="#C9A14A",
        bg="#0A0805",
        fg="#F2EAD3",
        font_hook="Cinzel",
        font_headline="Cinzel",
        font_body="EB Garamond",
        font_accent="Cinzel Decorative",
        lut_path=str(_luts_dir() / "got_hotd_amber.cube"),
        grain_opacity=0.10,
        vignette_strength=0.50,
    ),
    "stranger_things": BrandKit(
        key="stranger_things",
        primary="#E40000",
        secondary="#0E0E0E",
        accent="#F4F4F4",
        bg="#0A0A0A",
        fg="#F4F4F4",
        font_hook="Benguiat",
        font_headline="Benguiat",
        font_body="Inter",
        font_accent="ITC Benguiat",
        lut_path=str(_luts_dir() / "stranger_red.cube"),
        grain_opacity=0.12,
        vignette_strength=0.55,
        notes="Stephen King 80s book-cover red and black",
    ),
}


def get_brand_kit(key: str | None) -> BrandKit:
    if key:
        kit = KITS.get(key.lower())
        if kit:
            return kit
    return KITS["mcu"]


def list_kits() -> list[str]:
    return sorted(KITS.keys())
