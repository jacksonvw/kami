"""Kami config — TOML-backed dataclass at ~/.config/kami/config.toml.

`[appearance]` is the same section, with the same keys and meanings, as
Pepper's, Salt's and Minim's: background colour, opacity, KWin blur and
tint strength. `[editor]` and `[tabs]` are Kami's own.

The appearance helpers are adapted from Pepper's viewer_core.core.config,
so the file reads the same in every app of the suite.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# What `kami` does when Kami is already open: add a tab to the window used
# last, or open a window of its own.
OPEN_IN = ("tab", "window")


@dataclass
class AppearanceConfig:
    """The [appearance] TOML section, with the same defaults as Pepper,
    Salt and Semibreve, so the same settings look the same in each."""
    window_opacity: float = 1.0
    blur_behind: bool = True
    bg_color: list[int] = field(default_factory=lambda: [0, 0, 0])
    bg_tint_strength: int = 70


@dataclass
class AppConfig:
    appearance: AppearanceConfig = field(default_factory=AppearanceConfig)
    # An empty family means the desktop's fixed-width font, and a size of 0
    # its size, so Kami follows System Settings until told otherwise.
    font_family: str = ""
    font_size: float = 0.0
    word_wrap: bool = True
    # Keep every tab, unsaved text included, between runs, as Windows 11
    # Notepad does.
    restore_session: bool = True
    open_in: str = "tab"


def _clamp_unit(v: float) -> float:
    return max(0.0, min(1.0, v))


def _clamp_byte(v: int) -> int:
    return max(0, min(255, int(v)))


def _clamp_pct(v: int) -> int:
    return max(0, min(100, int(v)))


def _coerce_color(raw, default: list[int]) -> list[int]:
    if not isinstance(raw, (list, tuple)) or len(raw) != 3:
        return list(default)
    try:
        return [_clamp_byte(int(c)) for c in raw]
    except (TypeError, ValueError):
        return list(default)


def _coerce_float(raw, default: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def coerce_appearance(section: dict) -> AppearanceConfig:
    """Build an AppearanceConfig from a raw TOML [appearance] table."""
    defaults = AppearanceConfig()
    try:
        tint = int(section.get("bg_tint_strength", defaults.bg_tint_strength))
    except (TypeError, ValueError):
        tint = defaults.bg_tint_strength
    return AppearanceConfig(
        window_opacity=_clamp_unit(
            _coerce_float(section.get("window_opacity", defaults.window_opacity), 1.0)
        ),
        blur_behind=bool(section.get("blur_behind", defaults.blur_behind)),
        bg_color=_coerce_color(section.get("bg_color", defaults.bg_color), defaults.bg_color),
        bg_tint_strength=_clamp_pct(tint),
    )


def emit_appearance_lines(cfg: AppearanceConfig) -> list[str]:
    """Return the lines that go under [appearance] (no header)."""
    opacity = _clamp_unit(float(cfg.window_opacity))
    tint = _clamp_pct(int(cfg.bg_tint_strength))
    color = _coerce_color(cfg.bg_color, AppearanceConfig().bg_color)
    return [
        f"window_opacity = {opacity:.3f}",
        f"blur_behind = {'true' if cfg.blur_behind else 'false'}",
        f"bg_color = [{color[0]}, {color[1]}, {color[2]}]",
        f"bg_tint_strength = {tint}",
    ]


def app_config_path(app_name: str) -> Path:
    """`$XDG_CONFIG_HOME/<app_name>/config.toml`, `~/.config` by default.

    That is where QSettings already keeps window geometry. Inside a Flatpak
    it is the app's own ~/.var/app/<id>/config, since the sandbox can't
    write to ~/.config.
    """
    base = os.environ.get("XDG_CONFIG_HOME", "")
    # The XDG spec says to ignore a relative path.
    root = Path(base) if os.path.isabs(base) else Path.home() / ".config"
    return root / app_name / "config.toml"


def _default_path() -> Path:
    return app_config_path("kami")


def _toml_string(value: str) -> str:
    """A TOML basic string. Font names are plain, but quote what TOML needs."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def load_config(path: Path | None = None) -> AppConfig:
    p = path or _default_path()
    try:
        with open(p, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        data = {}
    except (OSError, tomllib.TOMLDecodeError):
        # A hand-edited file with a typo shouldn't stop Kami opening.
        data = {}

    defaults = AppConfig()
    editor = data.get("editor", {})
    tabs = data.get("tabs", {})
    open_in = str(tabs.get("open_in", defaults.open_in))
    family = editor.get("font_family", defaults.font_family)
    return AppConfig(
        appearance=coerce_appearance(data.get("appearance", {})),
        font_family=family if isinstance(family, str) else defaults.font_family,
        font_size=max(0.0, min(200.0, _coerce_float(editor.get("font_size", 0.0), 0.0))),
        word_wrap=bool(editor.get("word_wrap", defaults.word_wrap)),
        restore_session=bool(tabs.get("restore_session", defaults.restore_session)),
        open_in=open_in if open_in in OPEN_IN else defaults.open_in,
    )


def save_config(cfg: AppConfig, path: Path | None = None) -> None:
    if cfg.open_in not in OPEN_IN:
        raise ValueError(f"invalid open_in: {cfg.open_in!r}")
    lines = ["[appearance]", *emit_appearance_lines(cfg.appearance), ""]
    lines += [
        "[editor]",
        f"font_family = {_toml_string(cfg.font_family)}",
        f"font_size = {float(cfg.font_size):.1f}",
        f"word_wrap = {'true' if cfg.word_wrap else 'false'}",
        "",
        "[tabs]",
        f"restore_session = {'true' if cfg.restore_session else 'false'}",
        f'open_in = "{cfg.open_in}"',
    ]
    body = "\n".join(lines) + "\n"
    tomllib.loads(body)  # Never write a file that won't read back.
    p = path or _default_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
