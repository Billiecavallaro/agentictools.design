#!/usr/bin/env python3
"""One-off: draw og.png (1200x630), the social share image. Not part of the daily build."""
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F = "/usr/share/fonts/opentype/inter/"
W, H, S = 1200, 630, 2
INK, INK2, CANVAS, BAND, ACCENT, LINE, WIN = "#1D1D1B", "#5D5D57", "#F6F6F3", "#E6E1D8", "#BC4B26", "#DDDDD6", "#FAFAF8"

img = Image.new("RGB", (W * S, H * S), CANVAS)
d = ImageDraw.Draw(img)
def font(name, size): return ImageFont.truetype(F + name, size * S)
def box(x, y, w, h, r, fill, outline=None, width=0):
    d.rounded_rectangle([x * S, y * S, (x + w) * S, (y + h) * S], radius=r * S, fill=fill, outline=outline, width=width * S)

# right-hand painted panel with two app windows, echoing the site's stage
panel = Image.new("RGB", (W * S, H * S), CANVAS)
pd = ImageDraw.Draw(panel)
for i, c in enumerate(["#C9C2D3", "#D9CDBF", "#E6D9C4", "#B8BDC6", "#D8CDBF"]):
    pd.ellipse([(700 + i * 70) * S, (40 + (i % 3) * 140) * S, (1000 + i * 90) * S, (300 + (i % 3) * 160) * S], fill=c)
panel = panel.filter(ImageFilter.GaussianBlur(60 * S))
mask = Image.new("L", (W * S, H * S), 0)
ImageDraw.Draw(mask).rounded_rectangle([700 * S, 48 * S, 1152 * S, 582 * S], radius=6 * S, fill=255)
img.paste(panel, (0, 0), mask)

def window(x, y, w, h, title, stroke):
    box(x + 4, y + 10, w, h, 12, "#CFC9BE")
    box(x, y, w, h, 12, WIN, outline=stroke, width=3)
    d.line([x * S, (y + 34) * S, (x + w) * S, (y + 34) * S], fill=LINE, width=2 * S)
    for i in range(3):
        d.ellipse([(x + 16 + i * 16) * S, (y + 13) * S, (x + 26 + i * 16) * S, (y + 23) * S], fill=LINE)
    d.text(((x + w / 2) * S, (y + 17) * S), title, font=font("Inter-Regular.otf", 13), fill="#8C8C85", anchor="mm")
window(748, 104, 330, 250, "Directory", INK)
for i, (n, tint) in enumerate([("Fi", "#D9CFE6"), ("Lo", "#CFE0DA"), ("Do", "#E6DCC8"), ("Cu", "#E3D3CC")]):
    yy = 156 + i * 46
    box(770, yy, 30, 30, 7, tint)
    d.text((785 * S, (yy + 15) * S), n, font=font("Inter-Medium.otf", 12), fill="#2A2A26", anchor="mm")
    box(812, yy + 6, 150 - i * 18, 8, 4, "#D6D3CC")
    box(812, yy + 19, 96 - i * 10, 6, 3, "#E6E3DC")
window(860, 300, 260, 200, "Workflows", ACCENT)
for i in range(3):
    yy = 354 + i * 40
    d.ellipse([882 * S, yy * S, 902 * S, (yy + 20) * S], outline=LINE, width=2 * S)
    d.text((892 * S, (yy + 10) * S), str(i + 1), font=font("Inter-Medium.otf", 11), fill=INK2, anchor="mm")
    box(914, yy + 6, 160 - i * 30, 8, 4, "#D6D3CC")

# brand
box(64, 62, 24, 20, 4, CANVAS, outline=INK, width=3)
box(76, 74, 24, 20, 4, CANVAS, outline=ACCENT, width=3)
d.text((114 * S, 78 * S), "agentictools.design", font=font("Inter-SemiBold.otf", 26), fill=INK, anchor="lm")

# headline
hf = font("InterDisplay-Regular.otf", 58)
lines = ["Every new AI agent", "for design and", "product work,", "explained in 30 seconds."]
y = 176
for ln in lines:
    d.text((64 * S, y * S), ln, font=hf, fill=INK)
    y += 70
d.ellipse([66 * S, 528 * S, 78 * S, 540 * S], fill="#4E9A5B")
d.text((92 * S, 534 * S), "Updated daily  ·  for designers and PMs", font=font("Inter-Regular.otf", 20), fill=INK2, anchor="lm")

img = img.resize((W, H), Image.LANCZOS)
img.save(os.path.join(ROOT, "og.png"), optimize=True)
print("og.png written")
