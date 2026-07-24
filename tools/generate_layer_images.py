"""Render one PNG per keymap layer for the Keyboard Layers App Companion.

Parses config/sweep.keymap (ZMK bindings) and config/sweep.json (physical
layout with per-key x/y/rotation) and draws each layer to
"Keyboard Companion/assets/sweep-<name>.png".

The renderer is intentionally self-contained (only Pillow) so it can be
re-run whenever the keymap changes.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
KEYMAP = REPO / "config" / "sweep.keymap"
LAYOUT = REPO / "config" / "sweep.json"
ASSETS = REPO / "Keyboard Companion" / "assets"

# Render scale: pixels per 1u key unit.
UNIT = 132
KEY = int(UNIT * 0.92)          # drawn key size (small gap between keys)
PAD = UNIT                       # outer margin
RADIUS = 14

BG = (24, 26, 32)
KEY_FILL = (46, 50, 60)
KEY_FILL_TRANS = (32, 35, 42)    # &trans / &none keys are dimmer
KEY_EDGE = (70, 76, 90)
TEXT_MAIN = (236, 238, 242)
TEXT_SUB = (150, 200, 255)       # hold / layer sub-label
TEXT_DIM = (96, 102, 116)
TITLE = (255, 255, 255)

# ── keycode -> display label ────────────────────────────────────────────────
KEY_LABELS = {
    "EXCLAMATION": "!", "AT_SIGN": "@", "HASH": "#", "DOLLAR": "$",
    "PERCENT": "%", "CARET": "^", "AMPERSAND": "&", "ASTERISK": "*",
    "LEFT_PARENTHESIS": "(", "RIGHT_PARENTHESIS": ")",
    "LEFT_BRACKET": "[", "RIGHT_BRACKET": "]",
    "LEFT_BRACE": "{", "RIGHT_BRACE": "}",
    "MINUS": "-", "UNDERSCORE": "_", "EQUAL": "=", "PLUS": "+",
    "SINGLE_QUOTE": "'", "DOUBLE_QUOTES": '"', "GRAVE": "`", "TILDE": "~",
    "BACKSLASH": "\\", "PIPE": "|", "SEMI": ";", "COMMA": ",", "DOT": ".",
    "PERIOD": ".", "FSLH": "/",
    "SPACE": "Spc", "ENTER": "Ent", "ESCAPE": "Esc", "DELETE": "Del",
    "DEL": "Del", "BACKSPACE": "Bspc", "TAB": "Tab", "INS": "Ins",
    "CAPS": "Caps", "SCROLLLOCK": "ScrLk", "PRINTSCREEN": "PrtSc",
    "PAUSE_BREAK": "Pause", "K_LOCK": "Lock",
    "HOME": "Home", "END": "End", "PAGE_UP": "PgUp", "PAGE_DOWN": "PgDn",
    "UP": "Up", "DOWN": "Down", "LEFT": "Left", "RIGHT": "Right",
    "LGUI": "GUI", "RGUI": "GUI", "LALT": "Alt", "RALT": "Alt",
    "LCTRL": "Ctrl", "RCTRL": "Ctrl", "LEFT_SHIFT": "Shift",
    "RIGHT_SHIFT": "Shift", "LSHIFT": "Shift", "RSHIFT": "Shift",
    "C_VOL_DN": "Vol-", "C_VOL_UP": "Vol+", "C_BRI_DEC": "Bri-",
    "C_BRI_UP": "Bri+", "C_BRIGHTNESS_DEC": "Bri-", "C_BRIGHTNESS_INC": "Bri+",
    "C_PLAY_PAUSE": "Play", "C_PREVIOUS": "Prev", "C_NEXT": "Next",
    "LCLK": "LClk", "RCLK": "RClk", "MCLK": "MClk",
    "BT_PRV": "BT<", "BT_NXT": "BT>", "BT_CLR": "BTclr", "BT_CLR_ALL": "BTclr*",
    "NUMBER_1": "1", "N2": "2", "N3": "3", "N4": "4", "N5": "5",
    "N6": "6", "N7": "7", "N8": "8", "N9": "9", "N0": "0", "NUMBER_0": "0",
    "F1": "F1", "F2": "F2", "F3": "F3", "F4": "F4", "F5": "F5", "F6": "F6",
    "F7": "F7", "F8": "F8", "F9": "F9", "F10": "F10", "F11": "F11", "F12": "F12",
}


def kc(code: str) -> str:
    code = code.strip()
    if code in KEY_LABELS:
        return KEY_LABELS[code]
    # Single letters / digits pass through.
    return code


def parse_layout():
    data = json.loads(LAYOUT.read_text(encoding="utf-8"))
    return data["layouts"]["LAYOUT"]["layout"]


def parse_layers():
    """Return list of (name, [binding_str x34])."""
    text = KEYMAP.read_text(encoding="utf-8")
    kmap = text[text.index("keymap {"):]
    layers = []
    # Each layer: "<name>_layer { ... bindings = < ... >;"
    for m in re.finditer(r"(\w+)_layer\s*\{(.*?)\};", kmap, re.DOTALL):
        name = m.group(1)
        body = m.group(2)
        bm = re.search(r"bindings\s*=\s*<(.*?)>;", body, re.DOTALL)
        if not bm:
            continue
        raw = bm.group(1)
        # Split on '&' to get individual bindings.
        tokens = ["&" + t.strip() for t in raw.split("&") if t.strip()]
        layers.append((name, tokens))
    return layers


def binding_labels(binding: str):
    """Return (main, sub) label strings for a single &binding token."""
    parts = binding.split()
    beh = parts[0]
    args = parts[1:]

    if beh == "&trans":
        return ("", "")
    if beh == "&none":
        return ("", "")
    if beh == "&kp":
        return (kc(" ".join(args)), "")
    if beh in ("&hml", "&hmr", "&hrsc"):
        # <mod> <key>: tap=key, hold=mod
        return (kc(args[1]), kc(args[0]))
    if beh == "&lt_tp":
        # <layer> <key>: tap=key, hold=layer
        return (kc(args[1]), f"L{args[0]}")
    if beh == "&ds_z":
        return (kc(args[1]), "scrl")
    if beh == "&sel_x":
        return (kc(args[1]), kc(args[0]))
    if beh == "&td_spc":
        return ("Spc", "Ent")
    if beh == "&mo":
        return (f"L{args[0]}", "")
    if beh == "&tog":
        return (f"tg{args[0]}", "")
    if beh == "&bt":
        if args and args[0] == "BT_SEL":
            return (f"BT{args[1]}", "")
        return (kc(args[0]) if args else "BT", "")
    if beh == "&studio_unlock":
        return ("Studio", "unlock")
    # Fallback: strip leading & and show.
    return (beh[1:], " ".join(args))


def load_font(size: int):
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


FONT_MAIN = load_font(int(KEY * 0.34))
FONT_SUB = load_font(int(KEY * 0.20))
FONT_TITLE = load_font(int(UNIT * 0.7))


def draw_text_center(draw, cx, cy, text, font, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    draw.text((cx - w / 2 - bbox[0], cy - h / 2 - bbox[1]), text, font=font, fill=fill)


def rotated_key_image(main, sub, is_trans, angle):
    """Draw a single key (upright) then rotate; return RGBA image + its size."""
    pad = 6
    size = KEY + pad * 2
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fill = KEY_FILL_TRANS if is_trans else KEY_FILL
    d.rounded_rectangle([pad, pad, pad + KEY, pad + KEY], radius=RADIUS,
                        fill=fill, outline=KEY_EDGE, width=2)
    cx = size / 2
    if main:
        if sub:
            draw_text_center(d, cx, size / 2 - KEY * 0.10, main, FONT_MAIN, TEXT_MAIN)
            draw_text_center(d, cx, size / 2 + KEY * 0.26, sub, FONT_SUB, TEXT_SUB)
        else:
            draw_text_center(d, cx, size / 2, main, FONT_MAIN, TEXT_MAIN)
    if angle:
        img = img.rotate(angle, resample=Image.BICUBIC, expand=True)
    return img


def render_layer(name, bindings, layout):
    xs = [k["x"] for k in layout]
    ys = [k["y"] for k in layout]
    max_x = max(xs) + 1
    max_y = max(ys) + 1.6  # room for rotated thumb keys
    W = int(max_x * UNIT + PAD * 2)
    H = int(max_y * UNIT + PAD * 2 + UNIT)  # extra top band for title

    canvas = Image.new("RGBA", (W, H), BG + (255,))
    draw = ImageDraw.Draw(canvas)
    draw_text_center(draw, W / 2, PAD * 0.6, f"Sweep Pro  -  {name.upper()}",
                     FONT_TITLE, TITLE)

    title_offset = UNIT * 0.7
    for i, keydef in enumerate(layout):
        if i >= len(bindings):
            break
        main, sub = binding_labels(bindings[i])
        is_trans = bindings[i].split()[0] in ("&trans", "&none")
        angle = -keydef.get("r", 0)  # KLE rotation is clockwise-positive
        key_img = rotated_key_image(main, sub, is_trans, angle)

        # Position: rotate around (rx, ry) if present, else key x/y.
        if "r" in keydef and "rx" in keydef:
            rx = keydef["rx"] * UNIT + PAD
            ry = keydef["ry"] * UNIT + PAD + title_offset
            # offset of key center relative to rotation origin, in units
            ox = (keydef["x"] - keydef["rx"] + 0.5) * UNIT
            oy = (keydef["y"] - keydef["ry"] + 0.5) * UNIT
            rad = math.radians(keydef["r"])
            rxp = ox * math.cos(rad) - oy * math.sin(rad)
            ryp = ox * math.sin(rad) + oy * math.cos(rad)
            cx = rx + rxp
            cy = ry + ryp
        else:
            cx = keydef["x"] * UNIT + PAD + KEY / 2
            cy = keydef["y"] * UNIT + PAD + title_offset + KEY / 2

        canvas.alpha_composite(key_img, (int(cx - key_img.width / 2),
                                         int(cy - key_img.height / 2)))

    out = ASSETS / f"sweep-{name}.png"
    canvas.convert("RGB").save(out)
    return out


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    layout = parse_layout()
    layers = parse_layers()
    print(f"Layout keys: {len(layout)}  Layers: {len(layers)}")
    for name, bindings in layers:
        out = render_layer(name, bindings, layout)
        print(f"  wrote {out.name}  ({len(bindings)} bindings)")


if __name__ == "__main__":
    main()
