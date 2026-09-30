"""Colour tokens for light and dark mode.

Every chart colour does one job:
- series:   identity (observed data is always ``series``)
- scenario: ordinal ramp Low -> High for projection scenarios (one hue, lightness
            steps; validated with the dataviz ordinal checks). In dark mode the
            ramp flips so the step nearest the surface is still "Low".
- diverging: blue (falling) <-> grey <-> red (rising) for station trends on the map.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    mode: str
    surface: str
    page: str
    ink: str
    ink_secondary: str
    ink_muted: str
    grid: str
    axis: str
    series: str
    series_soft: str  # monthly values behind the annual line
    reference: str  # fitted trend lines
    scenario: tuple[str, str, str, str, str]  # Low ... High
    band_alpha: float
    diverging: tuple[str, ...]  # falling ... neutral ... rising
    good: str
    warning: str
    critical: str
    map_style: str


LIGHT = Theme(
    mode="light",
    surface="#fcfcfb",
    page="#f9f9f7",
    ink="#0b0b0b",
    ink_secondary="#52514e",
    ink_muted="#898781",
    grid="#e1e0d9",
    axis="#c3c2b7",
    series="#2a78d6",
    series_soft="#9ec5f4",
    reference="#52514e",
    scenario=("#f99c7c", "#eb7a52", "#d75928", "#bb3f00", "#992f00"),
    band_alpha=0.16,
    diverging=("#184f95", "#3987e5", "#9ec5f4", "#f0efec", "#f0a3a2", "#e34948", "#a8302f"),
    good="#0ca30c",
    warning="#fab219",
    critical="#d03b3b",
    map_style="carto-positron",
)

DARK = Theme(
    mode="dark",
    surface="#1a1a19",
    page="#0d0d0d",
    ink="#ffffff",
    ink_secondary="#c3c2b7",
    ink_muted="#898781",
    grid="#2c2c2a",
    axis="#383835",
    series="#3987e5",
    series_soft="#256abf",
    reference="#c3c2b7",
    scenario=("#953307", "#b84412", "#d75928", "#eb7a52", "#f99c7c"),
    band_alpha=0.22,
    # On the dark surface magnitude reads as lightness, so the arms brighten outward.
    diverging=("#86b6ef", "#3987e5", "#1c5cab", "#383835", "#a8302f", "#e34948", "#f0a3a2"),
    good="#0ca30c",
    warning="#fab219",
    critical="#d03b3b",
    map_style="carto-darkmatter",
)


def get_theme(mode: str | None) -> Theme:
    return DARK if mode == "dark" else LIGHT


def rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"
