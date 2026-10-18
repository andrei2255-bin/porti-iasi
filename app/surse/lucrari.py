"""Lucrări care reduc capacitatea unei porți toată ziua (ex. se schimbă șinele de tramvai).

Spre deosebire de evenimente (care aduc mașini în plus pe o fereastră de timp), o lucrare
blochează o parte din locuri cât ține ziua, deci poarta funcționează la capacitate redusă.

Se citesc din resurse/lucrari.json. O intrare cu "zi": "demo" se aplică automat în ziua demo-ului,
ca prezentarea să meargă indiferent de data din calendar.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import date
from functools import lru_cache

from ..config import DIR_RESURSE, PORTI_DUPA_ID

log = logging.getLogger("porti.lucrari")


@dataclass
class Lucrare:
    poarta: str
    nume: str
    procent_blocat: int     # cât din locuri sunt blocate (0–100)

    @property
    def fractie(self) -> float:
        return min(0.95, max(0.0, self.procent_blocat / 100))

    def ca_dict(self) -> dict:
        return {**asdict(self), "poarta_nume": PORTI_DUPA_ID[self.poarta]["nume"]}


@lru_cache(maxsize=1)
def _din_fisier() -> dict[str, tuple]:
    cale = DIR_RESURSE / "lucrari.json"
    rezultat: dict[str, list] = {}
    try:
        brut = json.loads(cale.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("Nu pot citi %s: %s", cale, e)
        return {}
    for lu in brut.get("lucrari", []):
        try:
            if lu["poarta"] not in PORTI_DUPA_ID:
                continue
            rezultat.setdefault(str(lu["zi"]), []).append(
                Lucrare(lu["poarta"], lu["nume"], int(lu.get("procent_blocat", 50))))
        except (KeyError, ValueError) as e:
            log.warning("Lucrare ignorată (date incomplete: %s): %s", e, lu)
    return {zi: tuple(v) for zi, v in rezultat.items()}


def lucrari_zi(zi: date) -> list[Lucrare]:
    din_fisier = _din_fisier()
    lista = list(din_fisier.get(zi.isoformat(), ()))
    from ..timp import zi_demo
    if zi == zi_demo():
        lista += list(din_fisier.get("demo", ()))
    return lista
