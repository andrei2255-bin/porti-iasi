"""Ora și ziua folosite de backend.

Frontendul trimite ora simulată ca minute de la miezul nopții (510 = 08:30).
Dacă nu trimite nimic, folosim ora reală din Iași.
"""
from __future__ import annotations

import math
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import FUS_ORAR, PAS, ZI_FINAL, ZI_START

TZ = ZoneInfo(FUS_ORAR)


def acum() -> datetime:
    return datetime.now(TZ)


def ora_curenta() -> int:
    """Ora reală din Iași, în minute, limitată la intervalul din demo."""
    n = acum()
    return limiteaza(n.hour * 60 + n.minute)


def limiteaza(t: int) -> int:
    return min(ZI_FINAL, max(ZI_START, int(t)))


def slot(t: int) -> int:
    """Indexul intervalului de 5 minute (0 = 05:00)."""
    return (limiteaza(t) - ZI_START) // PAS


def ora(t: int) -> str:
    t = int(t)
    return f"{t // 60 % 24:02d}:{t % 60:02d}"


def din_ora(text: str) -> int:
    """'08:30' -> 510"""
    h, m = text.strip().split(":")
    return int(h) * 60 + int(m)


def jround(x: float) -> int:
    """Rotunjire ca Math.round din JavaScript (2.5 -> 3), ca cifrele să fie identice cu frontendul."""
    return math.floor(x + 0.5)


def zi_demo() -> date:
    """Ziua pe care o arată demo-ul.

    Implicit: azi, dacă e zi lucrătoare; altfel următoarea zi lucrătoare
    (la hackathon, în weekend, vrem totuși o zi cu vârf de dimineață).
    Se poate fixa cu variabila de mediu PORTI_ZI_DEMO=2026-10-19.
    """
    fix = os.getenv("PORTI_ZI_DEMO")
    if fix:
        return date.fromisoformat(fix)
    from .surse.calendar_ro import e_zi_libera  # import târziu, ca să evităm importuri circulare
    z = acum().date()
    while e_zi_libera(z):
        z += timedelta(days=1)
    return z
