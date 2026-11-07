"""YouTube thumbnail (1280x720) for the Homeward demo. Run: python demo/make_thumbnail.py"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1280, 720
HERE = Path(__file__).resolve().parent
FONTS = Path("C:/Windows/Fonts")
BG1, BG2 = (15, 26, 34), (22, 48, 58)
GREEN, RED, INK, MUTED, AMBER = (95, 211, 154), (255, 138, 128), (238, 243, 246), (159, 176, 188), (240, 192, 96)


def f(name, size):
    return ImageFont.truetype(str(FONTS / name), size)


img = Image.new("RGB", (W, H), BG1)
px = img.load()
for y in range(H):                                   # diagonal gradient
    for x in range(0, W):
        t = (x / W * 0.5 + y / H * 0.5)
        px[x, y] = tuple(int(BG1[i] + (BG2[i] - BG1[i]) * t) for i in range(3))
glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow)
gd.ellipse((700, 60, 1260, 620), fill=(95, 211, 154, 46))
glow = glow.filter(ImageFilter.GaussianBlur(90))
img = Image.alpha_composite(img.convert("RGBA"), glow)
d = ImageDraw.Draw(img)


def centered(text, font, cx, y, fill):
    w = d.textlength(text, font=font)
    d.text((cx - w / 2, y), text, font=font, fill=fill)


# logo + name
d.rounded_rectangle((56, 48, 116, 108), radius=15, fill=GREEN)
d.line([(68, 82), (86, 66), (104, 82)], fill=BG1, width=5, joint="curve")
d.line([(74, 78), (74, 98), (98, 98), (98, 78)], fill=BG1, width=5, joint="curve")
d.text((132, 52), "Homeward", font=f("segoeuib.ttf", 46), fill=INK)

# headline
d.text((56, 160), "Fit to go home", font=f("segoeuib.ttf", 58), fill=INK)
d.text((56, 228), "at 10:00.", font=f("segoeuib.ttf", 58), fill=INK)
d.text((56, 316), "9 hours later,", font=f("segoeuib.ttf", 58), fill=RED)
d.text((56, 384), "she's still here.", font=f("segoeuib.ttf", 58), fill=RED)
d.text((60, 484), "Not one minute was medical.", font=f("segoeui.ttf", 36), fill=MUTED)

# right: 19:10 struck through -> 12:40
cx = 960
d.rounded_rectangle((740, 84, 1190, 292), radius=30, fill=(31, 51, 64), outline=(52, 78, 94), width=3)
centered("usual day", f("segoeuib.ttf", 28), cx, 94, MUTED)
big = f("consolab.ttf", 118)
centered("19:10", big, cx, 152, RED)
w = d.textlength("19:10", font=big)
d.line([(cx - w / 2 - 12, 222), (cx + w / 2 + 12, 222)], fill=RED, width=9)
d.polygon([(cx - 26, 308), (cx + 26, 308), (cx, 346)], fill=GREEN)             # arrow down
d.rounded_rectangle((740, 362, 1190, 592), radius=30, fill=(21, 58, 49), outline=GREEN, width=5)
centered("with Homeward", f("segoeuib.ttf", 28), cx, 372, GREEN)
centered("12:40", f("consolab.ttf", 136), cx, 424, INK)
centered("6.5 hours handed back", f("segoeuib.ttf", 28), cx, 552, GREEN)

# bottom strip
d.rounded_rectangle((0, 636, W, H), radius=0, fill=(10, 18, 24))
d.text((56, 650), "AI agents chase", font=f("segoeuib.ttf", 34), fill=(138, 180, 255))
d.text((330, 650), "·  Nurses approve", font=f("segoeuib.ttf", 34), fill=(195, 176, 255))
d.text((640, 650), "·  Doctors decide", font=f("segoeuib.ttf", 34), fill=GREEN)
tag = "FLIP THE SWITCH"
tw = d.textlength(tag, font=f("segoeuib.ttf", 30))
d.rounded_rectangle((W - tw - 90, 650, W - 40, 700), radius=14, fill=AMBER)
d.text((W - tw - 65, 656), tag, font=f("segoeuib.ttf", 30), fill=(15, 26, 34))

out = HERE / "homeward-thumbnail.png"
img.convert("RGB").save(out, optimize=True)
print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
