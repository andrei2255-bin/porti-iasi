"""Evenimente publice care aduc mașini în plus la porți (meciuri, concerte, festivaluri).

Evenimentele reale se trec în resurse/evenimente.json. Pentru zilele din istoricul simulat,
generăm și evenimente fictive (în ~12% din zile), ca modelul să învețe cum arată o seară cu eveniment.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import date
from functools import lru_cache

import numpy as np

from ..config import DIR_RESURSE, PORTI, PORTI_DUPA_ID

log = logging.getLogger("porti.evenimente")


@dataclass
class Eveniment:
    nume: str
    start: int          # minute de la miezul nopții
    final: int
    porti: list[str]
    masini: int         # mașini în plus la fiecare poartă afectată

    def ca_dict(self) -> dict:
        return asdict(self)


def _minute(text: str) -> int:
    h, m = text.split(":")
    return int(h) * 60 + int(m)


@lru_cache(maxsize=1)
def _din_fisier() -> dict[str, tuple]:
    cale = DIR_RESURSE / "evenimente.json"
    rezultat: dict[str, list] = {}
    try:
        brut = json.loads(cale.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("Nu pot citi %s: %s", cale, e)
        return {}
    for ev in brut.get("evenimente", []):
        try:
            porti = [p for p in ev["porti"] if p in PORTI_DUPA_ID]
            rezultat.setdefault(ev["zi"], []).append(Eveniment(
                ev["nume"], _minute(ev["start"]), _minute(ev["final"]), porti, int(ev.get("masini_in_plus", 60))))
        except (KeyError, ValueError) as e:
            log.warning("Eveniment ignorat (date incomplete: %s): %s", e, ev)
    return {zi: tuple(lista) for zi, lista in rezultat.items()}


def evenimente_planificate(zi: date) -> list[Eveniment]:
    return list(_din_fisier().get(zi.isoformat(), ()))


def evenimente_sintetice(zi: date) -> list[Eveniment]:
    """Evenimente fictive pentru istoricul simulat (deterministe: aceeași zi dă același rezultat)."""
    rng = np.random.default_rng(int(zi.strftime("%Y%m%d")) + 99)
    if rng.random() >= 0.12:
        return []
    start = int(rng.choice([1080, 1140, 1200]))
    durata = int(rng.choice([120, 150, 180]))
    nr = int(rng.integers(1, 3))
    porti = [str(p) for p in rng.choice([g["id"] for g in PORTI], size=nr, replace=False)]
    return [Eveniment("Eveniment simulat", start, start + durata, porti, int(rng.integers(30, 151)))]
