"""PWA 아이콘 PNG 생성 (192/512)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (185, 28, 28, 255))
    draw = ImageDraw.Draw(img)
    radius = size // 6
    draw.rounded_rectangle((0, 0, size, size), radius=radius, fill=(185, 28, 28, 255))

    inner = size // 3
    draw.ellipse(
        (size // 2 - inner, size // 2 - inner, size // 2 + inner, size // 2 + inner),
        fill=(254, 242, 242, 45),
    )

    font_size = max(48, size // 3)
    try:
        font = ImageFont.truetype("seguiemj.ttf", font_size)
    except OSError:
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except OSError:
            font = ImageFont.load_default()

    text = "!"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(
        ((size - tw) / 2, (size - th) / 2 - size * 0.04),
        text,
        fill=(255, 255, 255, 255),
        font=font,
    )
    return img


def main() -> None:
    out_dir = Path(__file__).resolve().parent / "pwa" / "icons"
    out_dir.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        draw_icon(size).save(out_dir / f"icon-{size}.png", format="PNG")
    print(f"Generated icons in {out_dir}")


if __name__ == "__main__":
    main()
