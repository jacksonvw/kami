from __future__ import annotations

import tomllib

import pytest

from kami.core.config import AppConfig, AppearanceConfig, load_config, save_config


def test_defaults_when_there_is_no_file(tmp_path):
    assert load_config(tmp_path / "missing.toml") == AppConfig()


def test_round_trip(tmp_path):
    p = tmp_path / "config.toml"
    cfg = AppConfig()
    cfg.appearance.window_opacity = 0.25
    cfg.appearance.bg_color = [10, 20, 30]
    cfg.appearance.bg_tint_strength = 40
    cfg.font_family = 'Fira "Code"'
    cfg.font_size = 12.5
    cfg.word_wrap = False
    cfg.restore_session = False
    cfg.open_in = "window"
    save_config(cfg, p)
    assert load_config(p) == cfg


def test_appearance_section_matches_the_rest_of_the_suite(tmp_path):
    p = tmp_path / "config.toml"
    save_config(AppConfig(), p)
    data = tomllib.loads(p.read_text())
    assert set(data["appearance"]) == {
        "window_opacity", "blur_behind", "bg_color", "bg_tint_strength",
    }


def test_bad_values_fall_back(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        "[appearance]\nwindow_opacity = 7\nbg_color = [300, -5, \"x\"]\n"
        "bg_tint_strength = \"lots\"\n"
        "[editor]\nfont_size = \"big\"\nfont_family = 3\n"
        "[tabs]\nopen_in = \"sideways\"\n"
    )
    cfg = load_config(p)
    assert cfg.appearance.window_opacity == 1.0
    assert cfg.appearance.bg_color == AppConfig().appearance.bg_color
    assert cfg.appearance.bg_tint_strength == 70
    assert cfg.font_size == 0.0
    assert cfg.font_family == ""
    assert cfg.open_in == "tab"


def test_a_broken_file_gives_defaults(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[appearance\n")
    assert load_config(p) == AppConfig()


def test_save_refuses_an_unknown_open_in(tmp_path):
    cfg = AppConfig()
    cfg.open_in = "sideways"
    with pytest.raises(ValueError):
        save_config(cfg, tmp_path / "config.toml")


def test_windows_start_opaque_like_the_rest_of_the_suite(qapp):
    from PySide6.QtGui import QGuiApplication

    from kami.ui.theme import theme_for

    theme = theme_for(AppConfig().appearance, QGuiApplication.palette())
    assert not theme.translucent and theme.paper.alpha() == 255


def test_defaults_match_pepper_and_semibreve():
    assert AppConfig().appearance == AppearanceConfig(
        window_opacity=1.0, blur_behind=True, bg_color=[0, 0, 0], bg_tint_strength=70
    )


def test_translucent_alpha_matches_pepper_and_semibreve(qapp):
    from PySide6.QtGui import QGuiApplication

    from kami.ui.theme import theme_for

    look = AppearanceConfig(window_opacity=0.7, bg_tint_strength=100)
    theme = theme_for(look, QGuiApplication.palette())
    # Pepper's paintEvent: int(int(tint * 255 / 100) * int(opacity * 255) / 255)
    assert theme.paper.alpha() == int(int(100 * 255 / 100) * int(0.7 * 255) / 255)
