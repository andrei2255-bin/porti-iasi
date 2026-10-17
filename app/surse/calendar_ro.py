"""Calendarul României: sărbători legale și vacanțe școlare.

Sărbătorile se calculează (inclusiv Paștele ortodox), deci merg pentru orice an.
Vacanțele școlare se citesc din resurse/vacante.json (editabil).
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from functools import lru_cache

from ..config import DIR_RESURSE

# Sărbători legale cu dată fixă (lună, zi)
_FIXE = [(1, 1), (1, 2), (1, 6), (1, 7), (1, 24), (5, 1), (6, 1), (8, 15),
         (11, 30), (12, 1), (12, 25), (12, 26)]


def paste_ortodox(an: int) -> date:
    """Paștele ortodox (algoritmul Meeus pentru calendarul iulian + 13 zile; valabil 1900–2099)."""
    a, b, c = an % 4, an % 7, an % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    luna = (d + e + 114) // 31
    zi = (d + e + 114) % 31 + 1
    return date(an, luna, zi) + timedelta(days=13)


@lru_cache(maxsize=32)
def sarbatori_legale(an: int) -> frozenset:
    p = paste_ortodox(an)
    # Vinerea Mare, Paștele, a doua zi de Paște, Rusaliile (2 zile)
    mobile = [p - timedelta(days=2), p, p + timedelta(days=1), p + timedelta(days=49), p + timedelta(days=50)]
    return frozenset([date(an, luna, zi) for luna, zi in _FIXE] + mobile)


def e_sarbatoare(z: date) -> bool:
    return z in sarbatori_legale(z.year)


def e_zi_libera(z: date) -> bool:
    return z.weekday() >= 5 or e_sarbatoare(z)


def tip_zi(z: date) -> int:
    """0 = zi lucrătoare, 1 = sâmbătă, 2 = duminică sau sărbătoare legală."""
    if e_sarbatoare(z) or z.weekday() == 6:
        return 2
    if z.weekday() == 5:
        return 1
    return 0


@lru_cache(maxsize=1)
def _vacante() -> tuple:
    cale = DIR_RESURSE / "vacante.json"
    try:
        date_brute = json.loads(cale.read_text(encoding="utf-8"))
        return tuple((date.fromisoformat(a), date.fromisoformat(b)) for a, b in date_brute["perioade"])
    except (OSError, KeyError, ValueError):
        return ()


def e_vacanta(z: date) -> bool:
    return any(a <= z <= b for a, b in _vacante())
