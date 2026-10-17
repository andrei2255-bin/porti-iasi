"""Ocuparea porților: câte mașini sunt în fiecare parcare la o anumită oră.

Ocupare = mașinile „de fond” (din simulator)
        + mașinile intrate prin API la barieră (cele din demo)
        + locurile rezervate în aplicație și încă nefolosite.
"""
from __future__ import annotations

import math
import sqlite3
import threading
from datetime import date
from typing import Optional

from .config import PAS, PORTI, PORTI_DUPA_ID, ZI_START
from .context import ContextZi, context_zi
from .simulator import NR_SLOTURI, RezultatZi, simuleaza_zi
from .timp import slot


def ocupare_formula(g: dict, t: int) -> float:
    """Curba din frontend (rezervă, dacă simulatorul nu e disponibil)."""
    h = t / 60
    sig = lambda x: 1 / (1 + math.exp(-x))  # noqa: E731
    wob = 0.012 * math.sin(t / 17 + g["loc"]) + 0.008 * math.sin(t / 7.3 + g["x"])
    v = 0.06 + (g["max"] - 0.06) * sig((h - g["rise"]) / 0.32) * (1 - 0.88 * sig((h - g["fall"]) / 0.55)) + wob
    return max(0.03, min(1.0, v))


# ---------- mașinile de fond (simulatorul) ----------
#
# Ziua e simulată o singură dată și ținută în memorie. Un „scenariu” (ploaie, eveniment) poate
# schimba contextul zilei din demo, ca să arătați juriului cum reacționează sistemul.

_simulari: dict[date, RezultatZi] = {}
_scenariu: Optional[dict] = None
_lacat = threading.RLock()


def scenariu_curent() -> Optional[dict]:
    return _scenariu


def seteaza_scenariu(scenariu: Optional[dict]) -> None:
    """scenariu = {'zi': '2026-10-19', 'ploaie_mm': 8, 'vacanta': False, 'evenimente': [Eveniment...]} sau None."""
    global _scenariu
    with _lacat:
        _scenariu = scenariu
        _simulari.clear()


def context_cu_scenariu(zi: date) -> ContextZi:
    ctx = context_zi(zi)
    sc = _scenariu
    if sc and sc.get("zi") == zi.isoformat():
        if sc.get("ploaie_mm") is not None:
            ctx.ploaie_mm, ctx.sursa_meteo = float(sc["ploaie_mm"]), "scenariu demo"
        if sc.get("vacanta") is not None:
            ctx.vacanta = bool(sc["vacanta"])
        ctx.evenimente = ctx.evenimente + list(sc.get("evenimente", []))
    return ctx


def rezultat_zi(zi: date) -> RezultatZi:
    """Simularea zilei (mașinile de fond), calculată o dată și păstrată în memorie."""
    with _lacat:
        if zi not in _simulari:
            if len(_simulari) > 30:
                _simulari.clear()
            _simulari[zi] = simuleaza_zi(context_cu_scenariu(zi))
        return _simulari[zi]


def masini_baza(gid: str, zi: date, t: int) -> int:
    """Mașinile de fond la ora t."""
    return int(rezultat_zi(zi).masini[gid][slot(t)])


def cronologie_baza(zi: date) -> dict[str, list[int]]:
    """Mașinile de fond pentru toată ziua, la fiecare 5 minute."""
    rez = rezultat_zi(zi)
    return {g["id"]: rez.masini[g["id"]].tolist() for g in PORTI}


# ---------- mașinile reale (din API) ----------

def _citeste_reale(con: sqlite3.Connection, zi: date):
    ev = con.execute(
        "SELECT poarta, numar, t, tip FROM evenimente_bariera WHERE zi=? ORDER BY t, id", (zi.isoformat(),)
    ).fetchall()
    rez = con.execute(
        "SELECT poarta, t, expira_t FROM rezervari WHERE zi=? AND stare='activa'", (zi.isoformat(),)
    ).fetchall()
    return ev, rez


def _reale_la(ev, rez, t: int) -> dict[str, int]:
    inauntru: dict[str, str] = {}
    for r in ev:
        if r["t"] > t:
            break
        if r["tip"] == "intrare":
            inauntru[r["numar"]] = r["poarta"]
        else:
            inauntru.pop(r["numar"], None)
    numar = {g["id"]: 0 for g in PORTI}
    for poarta in inauntru.values():
        numar[poarta] += 1
    for r in rez:
        if r["t"] <= t < r["expira_t"]:
            numar[r["poarta"]] += 1
    return numar


def masini_reale(con: sqlite3.Connection, zi: date, t: int) -> dict[str, int]:
    ev, rez = _citeste_reale(con, zi)
    return _reale_la(ev, rez, t)


# ---------- ce folosesc endpoint-urile ----------

def stare_porti(con: sqlite3.Connection, zi: date, t: int) -> dict[str, dict]:
    """Pentru fiecare poartă: mașini, ocupare (0–1) și locuri libere la ora t."""
    reale = masini_reale(con, zi, t)
    rez = {}
    for g in PORTI:
        masini = min(g["loc"], masini_baza(g["id"], zi, t) + reale[g["id"]])
        rez[g["id"]] = {"masini": masini, "ocupare": masini / g["loc"], "libere": g["loc"] - masini}
    return rez


def cronologie(con: sqlite3.Connection, zi: date) -> dict[str, list[int]]:
    """Mașinile din fiecare poartă la fiecare 5 minute, cu tot cu cele din demo."""
    baza = cronologie_baza(zi)
    ev, rez = _citeste_reale(con, zi)
    if not ev and not rez:
        return {gid: [min(PORTI_DUPA_ID[gid]["loc"], m) for m in v] for gid, v in baza.items()}
    rezultat = {g["id"]: [] for g in PORTI}
    for k in range(NR_SLOTURI):
        reale = _reale_la(ev, rez, ZI_START + k * PAS)
        for g in PORTI:
            rezultat[g["id"]].append(min(g["loc"], baza[g["id"]][k] + reale[g["id"]]))
    return rezultat


def poarta_api(gid: str, stare: dict) -> dict:
    """Obiectul „poartă” exact cum îl folosește frontendul (plus ocupare și locuri libere)."""
    g = {k: v for k, v in PORTI_DUPA_ID[gid].items() if k != "cerere"}
    return {**g, "ocupare": round(stare["ocupare"], 4), "libere": stare["libere"]}


def sector_si_loc(indice: int) -> tuple[str, int]:
    """Locul cu numărul 237 -> sectorul C, locul 37 (sectoare de câte 100 de locuri)."""
    indice = max(1, indice)
    return "ABCDEFGHIJ"[min(9, (indice - 1) // 100)], (indice - 1) % 100 + 1


__all__ = ["NR_SLOTURI", "stare_porti", "cronologie", "poarta_api", "masini_reale", "slot", "sector_si_loc"]
