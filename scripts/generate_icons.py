"""One-time script to generate PWA icons from the MAS logo.

Run from project root:
    python scripts/generate_icons.py

Outputs:
    static/img/icon-192.png
    static/img/icon-512.png
    static/img/icon-maskable-512.png  (with safe padding for Android)
"""
import os
from pathlib import Path
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "static" / "img" / "mas_logo.png"
OUT_DIR = PROJECT_ROOT / "static" / "img"


def make_icon(size: int, padding_pct: float = 0.0, out_name: str = None):
    """Create a square icon. padding_pct=0.2 means 20% padding for maskable."""
    if not SRC.exists():
        raise SystemExit(f"Source logo not found at {SRC}")

    logo = Image.open(SRC).convert("RGBA")

    canvas = Image.new("RGBA", (size, size), (255, 255, 255, 255))

    inner = int(size * (1 - padding_pct * 2))
    logo.thumbnail((inner, inner), Image.LANCZOS)

    x = (size - logo.width) // 2
    y = (size - logo.height) // 2
    canvas.paste(logo, (x, y), logo)

    out = OUT_DIR / (out_name or f"icon-{size}.png")
    canvas.convert("RGB").save(out, "PNG", optimize=True)
    print(f"  OK {out.relative_to(PROJECT_ROOT)} ({size}x{size})")


if __name__ == "__main__":
    print("Generating PWA icons from MAS logo...")
    make_icon(192, padding_pct=0.05)
    make_icon(512, padding_pct=0.05)
    make_icon(512, padding_pct=0.18, out_name="icon-maskable-512.png")
    print("Done.")
