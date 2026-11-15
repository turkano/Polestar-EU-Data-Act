"""Top-down SVG picture of the car showing doors, windows, hood, locks ...

Home Assistant free so it can be unit tested and previewed on its own. The
drawing is a generic, original car silhouette (not any manufacturer's design).
Colours work on light and dark backgrounds because the SVG is transparent.
"""

from __future__ import annotations

from typing import Any

from .catalog import SPECS_BY_KEY

DOORS = ("front_left_door", "front_right_door", "rear_left_door", "rear_right_door")
WINDOWS = ("front_left_window", "front_right_window", "rear_left_window", "rear_right_window")
PANELS = ("hood", "tailgate", "tank_lid", "sunroof")
IMAGE_KEYS = DOORS + WINDOWS + PANELS + ("central_lock",)

# state: True = open (or unlocked), False = closed (or locked), None = not reported
States = dict[str, bool | None]

BODY = "#b9c2cc"
BODY_STROKE = "#56616e"
GLASS = "#33414f"
OPEN = "#e5484d"
OPEN_STROKE = "#9c2b2f"
WINDOW_OPEN = "#f5a524"
LOCKED = "#30a46c"
UNKNOWN_OPACITY = 0.4

DEFS = (
    "<defs>"
    '<linearGradient id="paint" x1="0" x2="1" y1="0" y2="0">'
    '<stop offset="0" stop-color="#8d98a5"/><stop offset=".3" stop-color="#d3dae1"/>'
    '<stop offset=".5" stop-color="#e9edf1"/><stop offset=".7" stop-color="#d3dae1"/>'
    '<stop offset="1" stop-color="#8d98a5"/></linearGradient>'
    '<linearGradient id="glass" x1="0" x2="0" y1="0" y2="1">'
    '<stop offset="0" stop-color="#4a5b6d"/><stop offset="1" stop-color="#27323e"/></linearGradient>'
    '<linearGradient id="shine" x1="0" x2="1" y1="0" y2="1">'
    '<stop offset="0" stop-color="#fff" stop-opacity=".45"/><stop offset=".5" stop-color="#fff" stop-opacity="0"/></linearGradient>'
    '<radialGradient id="shadow"><stop offset=".6" stop-color="#000" stop-opacity=".30"/>'
    '<stop offset="1" stop-color="#000" stop-opacity="0"/></radialGradient>'
    "</defs>"
)

# Part geometry shared by drawing helpers (viewBox 240 x 440, nose at the top)
BODY_PATH = (
    "M88 30 C100 25 140 25 152 30 C166 38 174 62 175 104 L176 150 L176 300 L175 352 "
    "C174 384 166 404 150 410 C136 413 104 413 90 410 C74 404 66 384 65 352 L64 300 L64 150 "
    "L65 104 C66 62 74 38 88 30 Z"
)
HOOD_PATH = "M84 46 C100 41 140 41 156 46 C163 74 166 104 166 128 L74 128 C74 104 77 74 84 46 Z"
TAILGATE_PATH = (
    "M76 314 L164 314 C164 336 163 360 158 384 C148 394 136 397 120 397 "
    "C104 397 92 394 82 384 C77 360 76 336 76 314 Z"
)


def exterior_states(exterior: dict[str, Any] | None) -> States:
    """Read every state used by the picture from an ``exterior`` payload."""
    return {key: SPECS_BY_KEY[key].extract(exterior) for key in IMAGE_KEYS}


def open_parts(states: States) -> list[str]:
    """Keys of the parts that are open (windows and unlocked included)."""
    return [k for k in IMAGE_KEYS if states.get(k) is True]


def _opacity(state: bool | None) -> str:
    return "" if state is not None else f' opacity="{UNKNOWN_OPACITY}"'


def _wheels() -> str:
    out = []
    for x in (52, 172):
        for y in (86, 306):
            out.append(f'<rect x="{x}" y="{y}" width="16" height="48" rx="7" fill="#1b1f24"/>')
            out.append(f'<rect x="{x + 4 if x < 100 else x + 2}" y="{y + 8}" width="10" height="32" rx="4" fill="#3a424b"/>')
    return "".join(out)


def _mirror(left: bool) -> str:
    x = 64 if left else 176
    d = -1 if left else 1
    return (
        f'<path d="M{x} 142 L{x + d * 8} 140 C{x + d * 16} 138 {x + d * 19} 146 {x + d * 14} 153 '
        f'C{x + d * 10} 158 {x + d * 4} 157 {x} 155 Z" fill="url(#paint)" stroke="{BODY_STROKE}" stroke-width="1.2"/>'
    )


def _door(state: bool | None, left: bool, y: float, length: float) -> str:
    """A door drawn flush with the body, swung outwards when open."""
    x = 64 if left else 164
    hinge_x = 68 if left else 172
    angle = (38 if left else -38) if state else 0
    fill = OPEN if state else "#cdd4db"
    stroke = OPEN_STROKE if state else "#98a3af"
    handle_x = 68 if left else 168
    handle = (
        "" if state else
        f'<rect x="{handle_x}" y="{y + length - 20}" width="4" height="12" rx="2" fill="#8a95a1"/>'
    )
    return (
        f'<g transform="rotate({angle} {hinge_x} {y})"{_opacity(state)}>'
        f'<rect x="{x}" y="{y}" width="12" height="{length}" rx="4" fill="{fill}" stroke="{stroke}" stroke-width="1"/>'
        f"{handle}</g>"
    )


def _window(state: bool | None, left: bool, y: float, length: float) -> str:
    x = 76 if left else 156
    fill = WINDOW_OPEN if state else "url(#glass)"
    return f'<rect x="{x}" y="{y}" width="8" height="{length}" rx="3" fill="{fill}"{_opacity(state)}/>'


def _padlock(unlocked: bool | None) -> str:
    """Green closed padlock when locked, red open one when unlocked."""
    if unlocked is None:
        colour, shackle, opacity = "#8a94a0", "M114 248 v-7 a6 6 0 0 1 12 0 v7", UNKNOWN_OPACITY
    elif unlocked:
        colour, shackle, opacity = OPEN, "M114 248 v-8 a6 6 0 0 1 12 0", 1
    else:
        colour, shackle, opacity = LOCKED, "M114 248 v-7 a6 6 0 0 1 12 0 v7", 1
    return (
        f'<g opacity="{opacity}"><circle cx="120" cy="251" r="17" fill="#fff" opacity=".55"/>'
        f'<path d="{shackle}" fill="none" stroke="{colour}" stroke-width="2.6" stroke-linecap="round"/>'
        f'<rect x="110" y="248" width="20" height="15" rx="3" fill="{colour}"/>'
        f'<circle cx="120" cy="255.5" r="2.2" fill="#ffffff"/></g>'
    )


def render_svg(states: States) -> str:
    """Render the car as an SVG document for the given part states."""
    g = states.get
    hood, tailgate, lid, sunroof = g("hood"), g("tailgate"), g("tank_lid"), g("sunroof")

    parts: list[str] = [DEFS]
    # Soft ground shadow and wheels (under the body)
    parts.append('<ellipse cx="124" cy="226" rx="82" ry="212" fill="url(#shadow)"/>')
    parts.append(_wheels())
    parts.append(_mirror(True))
    parts.append(_mirror(False))
    # Body paint
    parts.append(f'<path d="{BODY_PATH}" fill="url(#paint)" stroke="{BODY_STROKE}" stroke-width="2.2"/>')
    # Lights (generic LED strips)
    parts.append('<path d="M80 34 C88 31 98 30 106 30 L104 38 C96 38 88 40 80 44 Z" fill="#eef3f8" stroke="#6c7783" stroke-width="1"/>')
    parts.append('<path d="M160 34 C152 31 142 30 134 30 L136 38 C144 38 152 40 160 44 Z" fill="#eef3f8" stroke="#6c7783" stroke-width="1"/>')
    parts.append('<rect x="70" y="398" width="30" height="7" rx="3.5" fill="#c43b3b" stroke="#7a1f1f" stroke-width="1"/>')
    parts.append('<rect x="140" y="398" width="30" height="7" rx="3.5" fill="#c43b3b" stroke="#7a1f1f" stroke-width="1"/>')
    # Hood (centre crease), raised when open
    hood_fill, hood_stroke = (OPEN, OPEN_STROKE) if hood else ("url(#paint)", "#7d8996")
    hood_shift = ' transform="translate(0 -10)"' if hood else ""
    if hood:
        parts.append(f'<path d="{HOOD_PATH}" fill="#000" opacity="0.18"/>')
    parts.append(
        f'<g{hood_shift}{_opacity(hood)}><path d="{HOOD_PATH}" fill="{hood_fill}" stroke="{hood_stroke}" stroke-width="1.8"/>'
        '<path d="M120 48 L120 126" stroke="#7d8996" stroke-width="1" opacity=".5"/>'
        '<path d="M94 56 C92 80 92 104 94 124" stroke="#fff" stroke-width="2" opacity=".35" fill="none"/></g>'
    )
    # Windshield and rear window
    parts.append('<path d="M77 134 C100 128 140 128 163 134 L157 178 L83 178 Z" fill="url(#glass)"/>')
    parts.append('<path d="M86 140 L112 138 L96 174 L88 174 Z" fill="url(#shine)"/>')
    parts.append('<path d="M83 274 L157 274 L162 306 C140 311 100 311 78 306 Z" fill="url(#glass)"/>')
    parts.append('<path d="M92 280 L108 280 L100 302 L90 302 Z" fill="url(#shine)"/>')
    # Roof (+ glass roof when the car reports one)
    parts.append('<rect x="80" y="178" width="80" height="96" rx="12" fill="url(#paint)" stroke="#7d8996" stroke-width="1.3"/>')
    if sunroof is not None:
        parts.append(
            f'<rect x="90" y="186" width="60" height="80" rx="8" fill="{WINDOW_OPEN if sunroof else "url(#glass)"}" '
            f'stroke="{BODY_STROKE}" stroke-width="1.2"/>'
        )
        parts.append('<rect x="90" y="186" width="60" height="80" rx="8" fill="url(#shine)"/>')
    # Tailgate / trunk
    tg_fill, tg_stroke = (OPEN, OPEN_STROKE) if tailgate else ("url(#paint)", "#7d8996")
    tg_shift = ' transform="translate(0 10)"' if tailgate else ""
    if tailgate:
        parts.append(f'<path d="{TAILGATE_PATH}" fill="#000" opacity="0.18"/>')
    parts.append(
        f'<path d="{TAILGATE_PATH}" fill="{tg_fill}" stroke="{tg_stroke}" stroke-width="1.8"{tg_shift}{_opacity(tailgate)}/>'
    )
    # Charge port / tank lid (rear left fender)
    lid_fill = OPEN if lid else "#9aa5b1"
    parts.append(
        f'<rect x="66" y="336" width="13" height="15" rx="4" fill="{lid_fill}" stroke="{BODY_STROKE}" '
        f'stroke-width="1.2"{_opacity(lid)}/>'
    )
    # Side windows
    parts.append(_window(g("front_left_window"), True, 146, 56))
    parts.append(_window(g("front_right_window"), False, 146, 56))
    parts.append(_window(g("rear_left_window"), True, 210, 58))
    parts.append(_window(g("rear_right_window"), False, 210, 58))
    # Doors (drawn last so open ones are on top)
    parts.append(_door(g("rear_left_door"), True, 208, 70))
    parts.append(_door(g("rear_right_door"), False, 208, 70))
    parts.append(_door(g("front_left_door"), True, 136, 68))
    parts.append(_door(g("front_right_door"), False, 136, 68))
    # Lock
    parts.append(_padlock(g("central_lock")))

    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 440" width="240" height="440" '
        'role="img" aria-label="Vehicle status">'
        + "".join(parts)
        + "</svg>"
    )
