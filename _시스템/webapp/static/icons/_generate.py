"""PWA 아이콘 생성 — Toss palette 풍의 단순 로고.

실행: python webapp/static/icons/_generate.py
생성: icon-192.png, icon-512.png, icon-maskable.png, favicon-32.png
"""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

OUT = Path(__file__).parent


def make_icon(size: int, maskable: bool = False) -> Image.Image:
    """Toss primary (#3182F6) 배경 + 흰색 '모' 글자."""
    pad = int(size * 0.12) if maskable else 0  # maskable 은 safe zone
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 둥근 사각형 배경 (Toss primary)
    corner = int(size * 0.22)
    bg_color = (49, 130, 246, 255)  # #3182F6
    draw.rounded_rectangle(
        [(0, 0), (size, size)],
        radius=corner,
        fill=bg_color,
    )

    # 가운데에 '모' 글자 (흰색)
    text = "모"
    font_size = int(size * 0.58)
    try:
        # Windows 기본 한글 폰트
        font = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", font_size)
    except (OSError, IOError):
        try:
            font = ImageFont.truetype("malgun.ttf", font_size)
        except (OSError, IOError):
            font = ImageFont.load_default()

    # 텍스트 가운데 정렬
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - tw) // 2 - bbox[0]
    y = (size - th) // 2 - bbox[1] - int(size * 0.04)  # 살짝 위로
    draw.text((x, y), text, fill=(255, 255, 255, 255), font=font)

    return img


def main():
    # 표준 PWA 아이콘
    make_icon(192).save(OUT / "icon-192.png")
    make_icon(512).save(OUT / "icon-512.png")
    # Maskable (Android 적응형)
    make_icon(512, maskable=True).save(OUT / "icon-maskable.png")
    # Favicon
    make_icon(32).save(OUT / "favicon-32.png")
    # Apple touch icon
    make_icon(180).save(OUT / "apple-touch-icon.png")

    print("✅ 아이콘 5종 생성:")
    for f in OUT.glob("*.png"):
        print(f"   {f.name} ({f.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
