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
import os
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
KEYMAP = REPO / "config" / "sweep.keymap"
LAYOUT = REPO / "config" / "sweep.json"
ASSETS = REPO / "Keyboard Companion" / "assets"

# Output dir for the LVGL I1 C image arrays. These land directly in the
# zmk-vfx-sweep-pro-display module's images dir so the shield build picks them
# up. The module is a sibling clone of this repo by default; override with the
# KEYMAP_I1_OUT_DIR env var (or the --i1-out-dir CLI arg) to point elsewhere.
DEFAULT_I1_OUT_DIR = (
    REPO.parent
    / "zmk-vfx-sweep-pro-display"
    / "boards"
    / "shields"
    / "sweep_display"
    / "images"
)
I1_OUT_DIR = Path(os.environ.get("KEYMAP_I1_OUT_DIR", DEFAULT_I1_OUT_DIR))

# Base layers get no mini-keymap image (they keep the normal status screen).
BASE_LAYERS = {"win", "mac"}

# I1 target image dimensions (left-half e-ink drawable area after rotation).
I1_W = 152
I1_H = 152

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


# ── I1 mini-keymap emission ─────────────────────────────────────────────────

def _is_trans(binding: str) -> bool:
    return binding.split()[0] in ("&trans", "&none")


def busy_side(bindings, layout):
    """Return 'left' or 'right': the hand with more non-trans/none bindings.

    Left hand = layout keys with integer x in 0..3, right hand = x in 8..11.
    """
    left = right = 0
    for i, keydef in enumerate(layout):
        if i >= len(bindings) or _is_trans(bindings[i]):
            continue
        x = keydef["x"]
        # Only count the outer finger columns of each hand.
        if 0 <= x <= 3:
            left += 1
        elif 8 <= x <= 11:
            right += 1
    return "left" if left >= right else "right"


def extract_grid(bindings, layout, side):
    """Return a 3x4 grid (rows 0..2, 4 outer finger cols) of (main, sub) labels.

    Drops the inner 5th column (x==4 / x==7) and the thumb row (row 3).
    For the right hand, columns are mirrored so the pinky column is outermost.
    """
    if side == "left":
        cols = [0, 1, 2, 3]          # pinky -> index (outer -> inner)
    else:
        cols = [11, 10, 9, 8]        # mirror: pinky (x=11) outermost

    grid = [[("", "") for _ in range(4)] for _ in range(3)]
    for i, keydef in enumerate(layout):
        if i >= len(bindings):
            break
        row = keydef.get("row")
        x = keydef["x"]
        if row not in (0, 1, 2) or x not in cols:
            continue
        c = cols.index(x)
        grid[row][c] = binding_labels(bindings[i])
    return grid


def render_i1_layer(name, bindings, layout):
    """Render a 152x152 mode '1' image: header + 4x3 label grid. Returns Image."""
    side = busy_side(bindings, layout)
    grid = extract_grid(bindings, layout, side)

    img = Image.new("1", (I1_W, I1_H), 1)  # 1 == white background
    d = ImageDraw.Draw(img)

    hdr_font = load_font(20)
    main_font = load_font(18)
    sub_font = load_font(11)

    # Header band with layer name.
    header = name.upper()
    hb = d.textbbox((0, 0), header, font=hdr_font)
    d.text(((I1_W - (hb[2] - hb[0])) / 2 - hb[0], 4 - hb[1]),
           header, font=hdr_font, fill=0)
    d.line([(0, 30), (I1_W - 1, 30)], fill=0, width=1)

    # 4 cols x 3 rows grid below the header.
    top = 34
    cell_w = I1_W / 4
    cell_h = (I1_H - top) / 3
    for r in range(3):
        for c in range(4):
            x0 = c * cell_w
            y0 = top + r * cell_h
            x1 = x0 + cell_w
            y1 = y0 + cell_h
            d.rectangle([x0, y0, x1 - 1, y1 - 1], outline=0, width=1)
            main, sub = grid[r][c]
            cx = (x0 + x1) / 2
            cy = (y0 + y1) / 2
            if main:
                if sub:
                    mb = d.textbbox((0, 0), main, font=main_font)
                    d.text((cx - (mb[2] - mb[0]) / 2 - mb[0],
                            cy - (mb[3] - mb[1]) / 2 - mb[1] - 8),
                           main, font=main_font, fill=0)
                    sb = d.textbbox((0, 0), sub, font=sub_font)
                    d.text((cx - (sb[2] - sb[0]) / 2 - sb[0],
                            cy - (sb[3] - sb[1]) / 2 - sb[1] + 12),
                           sub, font=sub_font, fill=0)
                else:
                    mb = d.textbbox((0, 0), main, font=main_font)
                    d.text((cx - (mb[2] - mb[0]) / 2 - mb[0],
                            cy - (mb[3] - mb[1]) / 2 - mb[1]),
                           main, font=main_font, fill=0)
    return img


def pack_i1_rows(img):
    """Pack a mode '1' image into MSB-first 1bpp rows. bit=1 -> black (index 1).

    Pillow mode '1': pixel value 255 == white, 0 == black. We map black->1 so
    palette index 1 (black) is selected, matching a white/black palette prefix.
    """
    w, h = img.size
    stride = (w + 7) // 8
    px = img.load()
    out = bytearray()
    for y in range(h):
        for bx in range(stride):
            byte = 0
            for bit in range(8):
                x = bx * 8 + bit
                if x < w and px[x, y] == 0:  # black pixel -> set bit
                    byte |= 0x80 >> bit
            out.append(byte)
    return bytes(out), stride


def emit_i1_c(name, data, stride, w, h, out_dir):
    """Write an LVGL LV_COLOR_FORMAT_I1 C file matching logo_img.c structure."""
    sym = f"keymap_{name}_img"
    upper = sym.upper()
    # 2-color palette prefix (ARGB8888, 4 bytes each): white then black.
    palette = bytes([0xFF, 0xFF, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0xFF])

    lines = []
    lines.append("#ifdef __has_include")
    lines.append('#if __has_include("lvgl.h")')
    lines.append("#ifndef LV_LVGL_H_INCLUDE_SIMPLE")
    lines.append("#define LV_LVGL_H_INCLUDE_SIMPLE")
    lines.append("#endif")
    lines.append("#endif")
    lines.append("#endif")
    lines.append("")
    lines.append("#if defined(LV_LVGL_H_INCLUDE_SIMPLE)")
    lines.append('#include "lvgl.h"')
    lines.append("#else")
    lines.append('#include "lvgl/lvgl.h"')
    lines.append("#endif")
    lines.append("")
    lines.append("#ifndef LV_ATTRIBUTE_MEM_ALIGN")
    lines.append("#define LV_ATTRIBUTE_MEM_ALIGN")
    lines.append("#endif")
    lines.append("")
    lines.append(f"#ifndef LV_ATTRIBUTE_{upper}")
    lines.append(f"#define LV_ATTRIBUTE_{upper}")
    lines.append("#endif")
    lines.append("")
    lines.append("static const LV_ATTRIBUTE_MEM_ALIGN LV_ATTRIBUTE_LARGE_CONST "
                 f"LV_ATTRIBUTE_{upper} uint8_t")
    lines.append(f" {sym}_map[] = {{")
    lines.append("")

    def fmt(chunk):
        return " ".join(f"0x{b:02x}," for b in chunk)

    lines.append(" " + fmt(palette))
    lines.append("")
    for i in range(0, len(data), 15):
        lines.append(" " + fmt(data[i:i + 15]))
    lines.append("")
    lines.append("};")
    lines.append("")
    lines.append(f"const lv_image_dsc_t {sym} = {{")
    lines.append(" .header =")
    lines.append(" {")
    lines.append(" .magic = LV_IMAGE_HEADER_MAGIC,")
    lines.append(" .cf = LV_COLOR_FORMAT_I1,")
    lines.append(" .flags = 0,")
    lines.append(f" .w = {w},")
    lines.append(f" .h = {h},")
    lines.append(f" .stride = {stride},")
    lines.append(" .reserved_2 = 0,")
    lines.append(" },")
    lines.append(f" .data_size = sizeof({sym}_map),")
    lines.append(f" .data = {sym}_map,")
    lines.append(" .reserved = NULL,")
    lines.append("};")
    lines.append("")

    out = out_dir / f"{sym}.c"
    out.write_text("\n".join(lines), encoding="utf-8")
    total = len(palette) + len(data)
    return out, sym, total


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--i1-out-dir",
        type=Path,
        default=I1_OUT_DIR,
        help="Output dir for the LVGL I1 keymap_<layer>_img.c files "
        "(default: sibling zmk-vfx-sweep-pro-display module images dir, "
        "overridable via the KEYMAP_I1_OUT_DIR env var).",
    )
    args = parser.parse_args()
    i1_out_dir = args.i1_out_dir

    ASSETS.mkdir(parents=True, exist_ok=True)
    i1_out_dir.mkdir(parents=True, exist_ok=True)
    layout = parse_layout()
    layers = parse_layers()
    print(f"Layout keys: {len(layout)}  Layers: {len(layers)}")
    print(f"I1 output dir: {i1_out_dir}")
    for name, bindings in layers:
        out = render_layer(name, bindings, layout)
        print(f"  wrote {out.name}  ({len(bindings)} bindings)")
        if name in BASE_LAYERS:
            print(f"  skip I1 for base layer '{name}'")
            continue
        side = busy_side(bindings, layout)
        i1_img = render_i1_layer(name, bindings, layout)
        data, stride = pack_i1_rows(i1_img)
        cfile, sym, total = emit_i1_c(name, data, stride, I1_W, I1_H, i1_out_dir)
        print(f"  wrote {cfile.name}  (busy={side}, {sym}, {total} bytes)")


if __name__ == "__main__":
    main()
