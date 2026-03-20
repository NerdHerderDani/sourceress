from PIL import Image
import os

src = r"C:\Users\Dani\.clawdbot\media\inbound\a21ab9ba-8129-4cb3-af47-056ebb156da9.jpg"
out_dir = r"C:\Users\Dani\clawd\github-sourcer-desktop\src-tauri\icons"
os.makedirs(out_dir, exist_ok=True)

img = Image.open(src).convert("RGBA")

# square crop centered
w, h = img.size
side = min(w, h)
left = (w - side) // 2
top = (h - side) // 2
img = img.crop((left, top, left + side, top + side))


def save_png(size: int, name: str):
    img.resize((size, size), Image.LANCZOS).save(os.path.join(out_dir, name), format="PNG")


save_png(32, "32x32.png")
save_png(128, "128x128.png")
save_png(256, "128x128@2x.png")

# windows ico
sizes = [16, 24, 32, 48, 64, 128, 256]
base = img.resize((256, 256), Image.LANCZOS)
base.save(os.path.join(out_dir, "icon.ico"), format="ICO", sizes=[(s, s) for s in sizes])

# mac icns (Pillow supports ICNS)
img.resize((1024, 1024), Image.LANCZOS).save(os.path.join(out_dir, "icon.icns"), format="ICNS")

print("icons written to", out_dir)
