"""Contextul unei zile: tot ce știm dinainte și influențează traficul la porți.

Vine din surse deschise (OSINT): calendarul (sărbători, vacanțe), vremea (Open-Meteo)
și evenimentele publice. Același context îl folosesc și simulatorul, și modelul de predicție.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np

from .surse.calendar_ro import e_vacanta, tip_zi
from .surse.evenimente import Eveniment, evenimente_planificate, evenimente_sintetice
from .surse.lucrari import Lucrare, lucrari_zi
from .surse.meteo import ploaie_zilnica

NUME_TIP_ZI = {0: "zi lucrătoare", 1: "sâmbătă", 2: "duminică / sărbătoare"}


@dataclass
class ContextZi:
    zi: date
    tip_zi: int                 # 0 lucrătoare, 1 sâmbătă, 2 duminică sau sărbătoare legală
    vacanta: bool               # vacanță școlară
    ploaie_mm: float            # precipitații în ziua respectivă
    evenimente: list[Eveniment] = field(default_factory=list)
    sursa_meteo: str = "estimare"
    lucrari: list[Lucrare] = field(default_factory=list)   # porți cu capacitate redusă (ex. lucrări la șine)

    def fractie_blocata(self, gid: str) -> float:
        """Cât din capacitatea porții e blocată de lucrări (0–0,95)."""
        return min(0.95, sum(lu.fractie for lu in self.lucrari if lu.poarta == gid))

    def ca_dict(self) -> dict:
        return {"zi": self.zi.isoformat(), "tip_zi": self.tip_zi, "tip_zi_text": NUME_TIP_ZI[self.tip_zi],
                "vacanta": self.vacanta, "ploaie_mm": self.ploaie_mm, "sursa_meteo": self.sursa_meteo,
                "evenimente": [e.ca_dict() for e in self.evenimente],
                "lucrari": [lu.ca_dict() for lu in self.lucrari]}


def seed_zi(zi: date) -> int:
    return int(zi.strftime("%Y%m%d"))


def _ploaie_estimata(zi: date) -> float:
    """Pentru zilele din trecut fără date reale: o vreme plauzibilă de toamnă (30% din zile cu ploaie)."""
    rng = np.random.default_rng(seed_zi(zi) + 7)
    return round(float(rng.gamma(1.5, 4.0)), 1) if rng.random() < 0.30 else 0.0


def context_zi(zi: date, *, istoric: bool = False) -> ContextZi:
    """istoric=True pentru zilele din trecut folosite la antrenare (completăm golurile cu estimări)."""
    meteo = ploaie_zilnica()
    if zi.isoformat() in meteo:
        ploaie, sursa = round(meteo[zi.isoformat()], 1), "open-meteo.com"
    elif istoric:
        ploaie, sursa = _ploaie_estimata(zi), "estimare"
    else:
        ploaie, sursa = 0.0, "fără date (presupunem fără ploaie)"
    evenimente = evenimente_planificate(zi)
    if not evenimente and istoric:
        evenimente = evenimente_sintetice(zi)
    # Lucrările se aplică doar la zilele „live” (demo), nu la istoricul de antrenare.
    lucrari = [] if istoric else lucrari_zi(zi)
    return ContextZi(zi, tip_zi(zi), e_vacanta(zi), ploaie, evenimente, sursa, lucrari=lucrari)
