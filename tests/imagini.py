"""Generează poze de test cu o plăcuță de înmatriculare (o mașină stilizată pe un fundal cu zgomot)."""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTURI = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
           "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
           "C:/Windows/Fonts/arialbd.ttf", "/Library/Fonts/Arial Bold.ttf"]


def font(marime: int):
    for cale in FONTURI:
        if Path(cale).exists():
            return ImageFont.truetype(cale, marime)
    return None


def poza_cu_placuta(text: str = "IS 23 OKC", rotatie: float = 2.0, seed: int = 1) -> bytes:
    rng = np.random.default_rng(seed)
    w, h = 1280, 860
    zgomot = rng.normal(120, 25, (h, w, 3)).clip(0, 255).astype("uint8")
    img = Image.fromarray(zgomot).filter(ImageFilter.GaussianBlur(2))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([200, 260, 1080, 760], radius=60, fill=(40, 60, 90))          # caroseria
    d.rectangle([330, 300, 950, 470], fill=(150, 180, 200))                           # parbrizul
    d.ellipse([260, 520, 380, 600], fill=(230, 230, 200))                             # faruri
    d.ellipse([900, 520, 1020, 600], fill=(230, 230, 200))
    pw, ph = 470, 100                                                                 # plăcuța (520 × 110 mm)
    placuta = Image.new("RGB", (pw, ph), "white")
    dp = ImageDraw.Draw(placuta)
    dp.rectangle([0, 0, pw - 1, ph - 1], outline="black", width=4)
    dp.rectangle([4, 4, 44, ph - 5], fill=(0, 51, 153))                               # banda UE
    f_mic = font(22)
    marime = 74
    while marime > 30 and (f := font(marime)) is not None and f.getbbox(text)[2] > pw - 80:
        marime -= 2                                                                   # textul trebuie să încapă
    f_mare = font(marime)
    dp.text((12, 62), "RO", fill="white", font=f_mic)
    latime = f_mare.getbbox(text)[2] if f_mare else 300
    dp.text((48 + (pw - 48 - latime) // 2, 8 + (74 - marime) // 2), text, fill="black", font=f_mare)
    placuta = placuta.rotate(rotatie, expand=True, fillcolor=(40, 60, 90))
    img.paste(placuta, (640 - placuta.width // 2, 600))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()
