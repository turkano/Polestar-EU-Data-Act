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

BODY = "#98a4b3"
BODY_STROKE = "#56616e"
GLASS = "#3d4d60"
OPEN = "#e5484d"
WINDOW_OPEN = "#f5a524"
LOCKED = "#30a46c"
UNKNOWN_OPACITY = 0.4


def exterior_states(exterior: dict[str, Any] | None) -> States:
    """Read every state used by the picture from an ``exterior`` payload."""
    return {key: SPECS_BY_KEY[key].extract(exterior) for key in IMAGE_KEYS}


def open_parts(states: States) -> list[str]:
    """Keys of the parts that are open (windows and unlocked included)."""
    return [k for k in IMAGE_KEYS if states.get(k) is True]


def _opacity(state: bool | None) -> str:
    return "" if state is not None else f' opacity="{UNKNOWN_OPACITY}"'


def _door(state: bool | None, left: bool, y: float, length: float) -> str:
    """A door drawn flush with the body, swung outwards when open."""
    x = 62 if left else 166
    hinge_x = 66 if left else 174
    angle = (38 if left else -38) if state else 0
    fill = OPEN if state else BODY
    stroke = "#9c2b2f" if state else BODY_STROKE
    return (
        f'<rect x="{x}" y="{y}" width="12" height="{length}" rx="4" fill="{fill}" '
        f'stroke="{stroke}" stroke-width="1.5" transform="rotate({angle} {hinge_x} {y})"'
        f"{_opacity(state)}/>"
    )


def _window(state: bool | None, left: bool, y: float, length: float) -> str:
    x = 78 if left else 154
    fill = WINDOW_OPEN if state else GLASS
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
        f'<g opacity="{opacity}">'
        f'<path d="{shackle}" fill="none" stroke="{colour}" stroke-width="2.6" stroke-linecap="round"/>'
        f'<rect x="110" y="248" width="20" height="15" rx="3" fill="{colour}"/>'
        f'<circle cx="120" cy="255.5" r="2.2" fill="#ffffff"/></g>'
    )


def render_svg(states: States) -> str:
    """Render the car as an SVG document for the given part states."""
    g = states.get
    hood, tailgate, lid, sunroof = g("hood"), g("tailgate"), g("tank_lid"), g("sunroof")

    parts: list[str] = []
    # Mirrors (decorative)
    parts.append(f'<ellipse cx="58" cy="139" rx="6" ry="9" fill="{BODY}" stroke="{BODY_STROKE}" stroke-width="1.5"/>')
    parts.append(f'<ellipse cx="182" cy="139" rx="6" ry="9" fill="{BODY}" stroke="{BODY_STROKE}" stroke-width="1.5"/>')
    # Body
    parts.append(
        f'<path d="M86 34 L154 34 C168 40 174 70 174 110 L174 330 C174 368 166 394 150 402 '
        f'L90 402 C74 394 66 368 66 330 L66 110 C66 70 72 40 86 34 Z" fill="{BODY}" '
        f'stroke="{BODY_STROKE}" stroke-width="2.5"/>'
    )
    # Hood
    hood_fill, hood_stroke = (OPEN, "#9c2b2f") if hood else (BODY, BODY_STROKE)
    hood_shift = ' transform="translate(0 -10)"' if hood else ""
    if hood:
        parts.append('<path d="M82 52 L158 52 C164 80 166 106 166 126 L74 126 C74 106 76 80 82 52 Z" fill="#000" opacity="0.18"/>')
    parts.append(
        f'<path d="M82 52 L158 52 C164 80 166 106 166 126 L74 126 C74 106 76 80 82 52 Z" fill="{hood_fill}" '
        f'stroke="{hood_stroke}" stroke-width="2"{hood_shift}{_opacity(hood)}/>'
    )
    # Windshield, rear window
    parts.append(f'<path d="M76 132 L164 132 L158 176 L82 176 Z" fill="{GLASS}"/>')
    parts.append(f'<path d="M82 276 L158 276 L164 306 L76 306 Z" fill="{GLASS}"/>')
    # Roof (+ sunroof when the car reports one)
    parts.append(f'<rect x="80" y="178" width="80" height="96" rx="10" fill="{BODY}" stroke="{BODY_STROKE}" stroke-width="1.5"/>')
    if sunroof is not None:
        parts.append(
            f'<rect x="92" y="186" width="56" height="48" rx="6" '
            f'fill="{WINDOW_OPEN if sunroof else GLASS}" stroke="{BODY_STROKE}" stroke-width="1.5"/>'
        )
    # Tailgate / trunk
    tg_fill, tg_stroke = (OPEN, "#9c2b2f") if tailgate else (BODY, BODY_STROKE)
    tg_shift = ' transform="translate(0 10)"' if tailgate else ""
    if tailgate:
        parts.append('<path d="M76 312 L164 312 C164 330 164 356 160 380 C150 392 136 396 120 396 C104 396 90 392 80 380 C76 356 76 330 76 312 Z" fill="#000" opacity="0.18"/>')
    parts.append(
        f'<path d="M76 312 L164 312 C164 330 164 356 160 380 C150 392 136 396 120 396 C104 396 90 392 80 380 '
        f'C76 356 76 330 76 312 Z" fill="{tg_fill}" stroke="{tg_stroke}" stroke-width="2"{tg_shift}{_opacity(tailgate)}/>'
    )
    # Charge port / tank lid (rear left fender)
    lid_fill = OPEN if lid else BODY
    parts.append(
        f'<circle cx="72" cy="344" r="7" fill="{lid_fill}" stroke="{BODY_STROKE}" stroke-width="1.5"{_opacity(lid)}/>'
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
