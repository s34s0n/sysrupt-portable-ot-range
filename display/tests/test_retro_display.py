"""Tests for Session 9b retro arcade display elements."""

import pytest
import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from display.server import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def html(client):
    r = client.get("/")
    return r.data.decode()


# --- Retro aesthetic tests ---

def test_crt_scanline_overlay(html):
    assert "repeating-linear-gradient" in html
    assert "pointer-events:none" in html or "pointer-events: none" in html


def test_monospace_font_only(html):
    assert "Courier New" in html
    # Must not use Arial/Helvetica as body font
    assert "font-family:Arial" not in html.replace(" ", "")
    assert "font-family: Arial" not in html


def test_body_dimensions(html):
    assert "width:320px" in html or "width: 320px" in html
    assert "height:240px" in html or "height: 240px" in html
    assert "overflow:hidden" in html or "overflow: hidden" in html


def test_no_emoji_characters(html):
    emoji_pat = re.compile(
        r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF"
        r"\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF"
        r"\U00002702-\U000027B0\U0001f900-\U0001f9FF"
        r"\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF"
        r"\u2600-\u26FF\u2700-\u27BF]"
    )
    emojis = emoji_pat.findall(html)
    assert len(emojis) == 0, f"Found emoji characters: {emojis}"


def test_no_external_resources(html):
    assert "cdn." not in html.lower()
    assert "googleapis" not in html.lower()
    assert "cloudflare" not in html.lower()


def test_screens_hidden_by_default(html):
    assert "display:none" in html.replace(" ", "")


def test_color_palette(html):
    for color in ["#00FF41", "#FFB000", "#FF0066", "#E8593C"]:
        assert color in html, f"Missing palette color {color}"


# --- Celebrations tests ---

def test_celebrations_object_exists(html):
    assert "CELEBRATIONS" in html


def test_celebrations_has_10_entries(html):
    # Each entry has a title field
    count = html.count("title:")
    assert count >= 10, f"Expected 10+ celebration entries, found {count}"


def test_celebrations_challenge_titles(html):
    expected = ["HACKERMAN", "GALAXY BRAIN", "I'M IN", "FREE REAL ESTATE",
                "THIS IS FINE", "STONKS", "UNLIMITED POWER", "PID HACKED",
                "SAFETY BYPASSED", "GG WP"]
    for title in expected:
        assert title in html, f"Missing celebration title: {title}"


def test_celebrations_have_art(html):
    # Each celebration should have an art array
    assert html.count("art:") >= 10 or html.count("art: [") >= 10


def test_celebrations_have_quotes(html):
    expected_quotes = ["I'm in.", "It's free real estate", "This is fine",
                       "STONKS", "The PID is mine now"]
    for q in expected_quotes:
        assert q in html, f"Missing quote: {q}"


# --- Screen content tests ---

def test_boot_screen_has_sysrupt_logo(html):
    assert 'class="logo"' in html
    assert "SYSRUPT" in html


def test_boot_screen_has_loading_bar(html):
    assert "bar-fill" in html
    assert "bootbar" in html


def test_idle_screen_press_start(html):
    assert "PRESS START" in html


def test_idle_screen_connection_info(html):
    assert "192.168.1.0/24" in html or "TARGET" in html


def test_progress_screen_challenge_grid(html):
    assert "pg-grid" in html


def test_hint_screen_coin(html):
    assert "HINT COIN USED" in html


def test_plant_mini_six_cells(html):
    for label in ["INTAKE", "CHEMICAL", "FILTER", "POWER", "SAFETY", "DIST"]:
        assert label in html, f"Missing plant cell: {label}"


def test_plant_mini_normal_operation(html):
    assert "NORMAL OPERATION" in html


def test_plant_mini_anomaly_detected(html):
    assert "ANOMALY DETECTED" in html


def test_attack_alert_bottom_message(html):
    assert "SOMEONE IS MESSING WITH THE WATER" in html


def test_sis_trip_game_over(html):
    assert "GAME OVER" in html


def test_sis_trip_hint_text(html):
    assert "defeat the SIS first next time" in html


def test_victory_gg_wp(html):
    assert "GG WP --- SYSRUPT OT RANGE" in html


def test_victory_no_conference_names(html):
    for name in ["DEFCON", "BlackHat", "BLACKHAT", "Black Hat", "DEF CON"]:
        assert name not in html, f"Found conference name: {name}"


def test_victory_plant_compromised(html):
    assert "PLANT COMPROMISED" in html


def test_victory_glitch_animation(html):
    assert "glitch" in html


def test_flash_border_animation(html):
    assert "flash-border" in html


# --- JavaScript structure tests ---

def test_polling_pattern(html):
    assert "fetch('/api/state')" in html or 'fetch("/api/state")' in html


def test_setinterval_polling(html):
    assert "setInterval(updateDisplay" in html


def test_boot_shown_immediately(html):
    assert "screen-boot" in html
    assert "display = 'flex'" in html or "display='flex'" in html


def test_update_content_function(html):
    assert "function updateContent" in html


def test_file_size_under_50kb(html):
    assert len(html.encode("utf-8")) < 50000, f"File is {len(html.encode('utf-8'))} bytes, exceeds 50KB"


# --- API endpoint test ---

def test_api_state_endpoint(client):
    r = client.get("/api/state")
    assert r.status_code == 200
    import json
    data = json.loads(r.data)
    assert "screen" in data
    assert "score" in data
    assert "total_points" in data
