"""
Genera icone PNG per la PWA WorkMind.
Richiede: pip install Pillow
Esegui: python scripts/generate_pwa_icons.py
"""
from pathlib import Path
import sys

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("Installa Pillow: pip install Pillow")
    sys.exit(1)


def make_icon(size: int, output: Path) -> None:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Gradiente simulato: riga per riga da #0a4fa8 a #0071e3
    for y in range(size):
        t = y / size
        r = int(10 + (0 - 10) * t)
        g = int(79 + (113 - 79) * t)
        b = int(168 + (227 - 168) * t)
        draw.line([(0, y), (size - 1, y)], fill=(r, g, b, 255))

    # Maschera angoli arrotondati (stile iOS)
    radius = int(size * 0.224)
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([(0, 0), (size - 1, size - 1)], radius=radius, fill=255)
    img.putalpha(mask)

    # Ricalcola draw dopo putalpha
    draw = ImageDraw.Draw(img)

    # Funzione di scaling dal coordinate-space 512x512
    def s(v):
        return int(v * size / 512)

    sw = max(5, int(54 * size / 512))  # spessore stroke

    # Disegna la W come segmenti
    pts = [(72, 128), (164, 390), (256, 226), (348, 390), (440, 128)]
    scaled = [(s(x), s(y)) for x, y in pts]
    for i in range(len(scaled) - 1):
        draw.line([scaled[i], scaled[i + 1]], fill=(255, 255, 255, 255), width=sw)

    # Punti giuntura (per arrotondare visivamente)
    dot_r = sw // 2
    for x, y in scaled:
        draw.ellipse([(x - dot_r, y - dot_r), (x + dot_r, y + dot_r)],
                     fill=(255, 255, 255, 255))

    # Circuit dots
    cy = s(440)
    cr = max(3, s(9))
    for cx in [152, 208, 256, 304, 360]:
        x = s(cx)
        draw.ellipse([(x - cr, cy - cr), (x + cr, cy + cr)],
                     fill=(255, 255, 255, 110))

    img.save(output, "PNG")
    print(f"  OK {output.name}  ({size}x{size}px)")


output_dir = Path(__file__).parent.parent / "static" / "icons"
output_dir.mkdir(parents=True, exist_ok=True)

print("Generazione icone WorkMind PWA...")
make_icon(512, output_dir / "icon-512.png")
make_icon(192, output_dir / "icon-192.png")
make_icon(180, output_dir / "apple-touch-icon.png")  # iOS homescreen
make_icon(32,  output_dir / "favicon-32.png")
print(f"\nIcone salvate in: {output_dir}")
