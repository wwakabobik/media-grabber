"""Generate AppIcon.icns for media-grabber: a play triangle riding a download
swoosh, on the app's own purple/dark gradient. Run once; output is checked in.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SIZE = 1024
HERE = Path(__file__).parent
ICONSET = HERE / "AppIcon.iconset"


def rounded_square_mask(size: int, margin: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [margin, margin, size - margin, size - margin], radius=radius, fill=255
    )
    return mask


def vertical_gradient(size: int, top: tuple, bottom: tuple) -> Image.Image:
    grad = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        grad.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return grad.resize((size, size))


def build() -> Image.Image:
    margin, radius = 54, 230
    mask = rounded_square_mask(SIZE, margin, radius)

    bg = vertical_gradient(SIZE, top=(32, 33, 46), bottom=(90, 58, 212)).convert("RGBA")
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    img.paste(bg, (0, 0), mask)

    # soft highlight, top-left
    hl = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(hl).ellipse([margin + 20, margin - 40, SIZE * 0.78, SIZE * 0.5], fill=(255, 255, 255, 30))
    hl = hl.filter(ImageFilter.GaussianBlur(70))
    hl_clipped = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    hl_clipped.paste(hl, (0, 0), mask)
    img = Image.alpha_composite(img, hl_clipped)

    # download swoosh: a thick arc sweeping down-right into an arrowhead
    glyph = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glyph)
    accent = (245, 243, 255, 255)
    cx, cy = SIZE * 0.5, SIZE * 0.46
    gd.arc([cx - 230, cy - 230, cx + 230, cy + 230], start=200, end=330, fill=accent, width=46)
    # arrowhead at the arc's end (~330deg), pointing along the sweep direction
    import math

    end_deg = 330
    ex = cx + 230 * math.cos(math.radians(end_deg))
    ey = cy + 230 * math.sin(math.radians(end_deg))
    tangent = math.radians(end_deg + 90)
    ahx, ahy = math.cos(tangent), math.sin(tangent)
    nx, ny = -ahy, ahx
    tip = (ex + ahx * 70, ey + ahy * 70)
    left = (ex - ahx * 20 + nx * 60, ey - ahy * 20 + ny * 60)
    right = (ex - ahx * 20 - nx * 60, ey - ahy * 20 - ny * 60)
    gd.polygon([tip, left, right], fill=accent)

    # play triangle, centered, slightly right of center for optical balance
    tri_cx, tri_cy, r = SIZE * 0.47, SIZE * 0.52, 150
    pts = [
        (tri_cx - r * 0.55, tri_cy - r),
        (tri_cx - r * 0.55, tri_cy + r),
        (tri_cx + r * 1.05, tri_cy),
    ]
    shadow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).polygon(pts, fill=(0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    img = Image.alpha_composite(img, shadow)
    gd.polygon(pts, fill=(255, 255, 255, 255))

    img = Image.alpha_composite(img, glyph)
    return img


def main() -> None:
    icon = build()
    ICONSET.mkdir(exist_ok=True)
    specs = [(16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2), (256, 1), (256, 2), (512, 1), (512, 2)]
    for base, scale in specs:
        px = base * scale
        name = f"icon_{base}x{base}{'@2x' if scale == 2 else ''}.png"
        icon.resize((px, px), Image.LANCZOS).save(ICONSET / name)
    print("iconset written:", ICONSET)


if __name__ == "__main__":
    main()
