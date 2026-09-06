"""Generate assets/habitflow.ico from the same shape as static/favicon.svg.

An unsigned exe with no icon and no version resource looks like malware to
Windows Defender's heuristics. This script is run by the release workflow
before PyInstaller so the built exe always carries a real icon.

    python packaging/make_icon.py
"""
import os

from PIL import Image, ImageDraw

ACCENT = (99, 102, 241, 255)   # #6366f1, the app's accent colour
WHITE = (255, 255, 255, 255)
SIZES = [16, 24, 32, 48, 64, 128, 256]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'assets', 'habitflow.ico')


def draw(size):
    """Rounded accent square with a white tick, drawn 8x then downsampled."""
    scale = 8
    s = size * scale
    img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.25), fill=ACCENT)

    # Same polyline as favicon.svg (viewBox 0 0 32 32), scaled to this canvas.
    pts = [(7, 17), (13, 23), (25, 10)]
    width = max(2, int(s * 0.10))
    scaled = [(x / 32 * s, y / 32 * s) for x, y in pts]
    d.line(scaled, fill=WHITE, width=width, joint='curve')
    for x, y in scaled:                      # round the caps
        r = width / 2
        d.ellipse([x - r, y - r, x + r, y + r], fill=WHITE)

    return img.resize((size, size), Image.LANCZOS)


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    frames = [draw(n) for n in SIZES]
    frames[-1].save(OUT, format='ICO', sizes=[(n, n) for n in SIZES])
    print(f'wrote {OUT} ({os.path.getsize(OUT)} bytes)')


if __name__ == '__main__':
    main()
