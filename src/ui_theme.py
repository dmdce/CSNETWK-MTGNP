"""Shared visual language for the MTGNP desktop applications."""

BG = "#070b12"
SURFACE = "#0e1622"
SURFACE_2 = "#151f2d"
SURFACE_3 = "#1d2a3a"
GOLD = "#cba45c"
GOLD_BRIGHT = "#f0c979"
TEXT = "#f4f7fb"
MUTED = "#8d9caf"
BLUE = "#55a8f7"
GREEN = "#4fd1a1"
RED = "#ef727a"
LINE = "#26374a"

# These families ship with current Windows releases. Tk automatically falls
# back to its platform default on systems where a family is unavailable.
FONT_DISPLAY = "Bahnschrift"
FONT_BODY = "Segoe UI Variable Text"
FONT_UI = "Segoe UI Variable Display"
FONT_MONO = "Cascadia Mono"

TYPE_HERO = (FONT_DISPLAY, 30, "bold")
TYPE_TITLE = (FONT_DISPLAY, 16, "bold")
TYPE_SECTION = (FONT_UI, 11, "bold")
TYPE_BODY = (FONT_BODY, 10)
TYPE_BODY_SMALL = (FONT_BODY, 9)
TYPE_LABEL = (FONT_UI, 8, "bold")
TYPE_BUTTON = (FONT_UI, 10, "bold")

CARD_COLORS = {
    "W": ("#d8d0b8", "#201e19"),
    "U": ("#244d73", "#f2f7fc"),
    "B": ("#302c39", "#f4f0fa"),
    "R": ("#753b36", "#fff3ed"),
    "G": ("#285440", "#effaf4"),
    "C": ("#414e5d", "#f5f7fa"),
}

PHASE_LABELS = {
    "LOBBY": "Lobby", "MULLIGAN": "Mulligan", "UNTAP": "Untap",
    "UPKEEP": "Upkeep", "DRAW": "Draw", "PRECOMBAT_MAIN": "Main I",
    "BEGIN_COMBAT": "Begin Combat", "DECLARE_ATTACKERS": "Attackers",
    "DECLARE_BLOCKERS": "Blockers", "FIRST_STRIKE_DAMAGE": "First Strike",
    "COMBAT_DAMAGE": "Combat Damage", "END_OF_COMBAT": "End Combat",
    "POSTCOMBAT_MAIN": "Main II", "END_STEP": "End Step", "CLEANUP": "Cleanup",
}
