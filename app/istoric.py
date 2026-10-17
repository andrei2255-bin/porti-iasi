"""Istoricul de ocupare: datele pe care învață modelul de predicție.

Până la pilot nu avem date reale de la camere, așa că istoricul e generat de simulator
pentru ultimele N zile, fiecare cu contextul ei (vreme, sărbători, vacanțe, evenimente).
Când pilotul pornește, aici intră datele reale, iar restul sistemului rămâne la fel.

Din linia de comandă:
    python -m app.istoric                 generează zilele lipsă (implicit 120)
    python -m app.istoric --zile 200      mai mult istoric
    python -m app.istoric --refa          șterge și regenerează tot
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from datetime import date, timedelta

import numpy as np

from . import db
from .config import PAS, PORTI, ZILE_ISTORIC, ZI_START
from .context import ContextZi, context_zi
from .simulator import NR_SLOTURI, simuleaza_zi
from .timp import zi_demo

log = logging.getLogger("porti.istoric")
PAS_ISTORIC = 15                       # în istoric păstrăm ocuparea la fiecare 15 minute
_SARITURA = PAS_ISTORIC // PAS         # 3 intervale de 5 minute


def salveaza_zi(con: sqlite3.Connection, ctx: ContextZi, masini: dict[str, np.ndarray],
                sosiri: dict[str, np.ndarray], redirectionate: dict[str, np.ndarray], sursa: str) -> None:
    zi = ctx.zi.isoformat()
    con.execute("INSERT OR REPLACE INTO zile(zi, tip_zi, vacanta, ploaie_mm, evenimente, sursa) VALUES (?,?,?,?,?,?)",
                (zi, ctx.tip_zi, int(ctx.vacanta), ctx.ploaie_mm,
                 json.dumps([e.ca_dict() for e in ctx.evenimente], ensure_ascii=False), sursa))
    con.execute("DELETE FROM istoric_ocupare WHERE zi=?", (zi,))
    randuri = []
    for g in PORTI:
        gid, cap = g["id"], g["loc"]
        for k in range(0, NR_SLOTURI, _SARITURA):
            m = int(masini[gid][k])
            fereastra = slice(max(0, k - _SARITURA + 1), k + 1)
            randuri.append((zi, gid, ZI_START + k * PAS, m, round(m / cap, 4),
                            int(sosiri[gid][fereastra].sum()), int(redirectionate[gid][fereastra].sum())))
    con.executemany("INSERT INTO istoric_ocupare VALUES (?,?,?,?,?,?,?)", randuri)


def genereaza(zile: int = ZILE_ISTORIC, pana_la: date | None = None, refa: bool = False) -> int:
    """Simulează zilele din istoric care lipsesc. Întoarce câte zile noi au fost adăugate."""
    pana_la = pana_la or zi_demo()
    lista = [pana_la - timedelta(days=d) for d in range(zile, 0, -1)]
    noi = 0
    with db.conexiune() as con:
        if refa:
            con.execute("DELETE FROM istoric_ocupare WHERE zi IN (SELECT zi FROM zile WHERE sursa='simulare')")
            con.execute("DELETE FROM zile WHERE sursa='simulare'")
        existente = {r[0] for r in con.execute("SELECT zi FROM zile")}
        for z in lista:
            if z.isoformat() in existente:
                continue
            ctx = context_zi(z, istoric=True)
            rez = simuleaza_zi(ctx)
            salveaza_zi(con, ctx, rez.masini, rez.sosiri, rez.redirectionate, sursa="simulare")
            noi += 1
    if noi:
        log.info("Istoric: am simulat %d zile noi (până la %s).", noi, pana_la - timedelta(days=1))
    return noi


def rezumat() -> dict:
    with db.conexiune() as con:
        r = con.execute("SELECT COUNT(*), MIN(zi), MAX(zi), SUM(sursa='zi_observata') FROM zile").fetchone()
    return {"zile": r[0], "de_la": r[1], "pana_la": r[2], "zile_observate": r[3] or 0}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser(description="Generează istoricul de ocupare simulat.")
    p.add_argument("--zile", type=int, default=ZILE_ISTORIC)
    p.add_argument("--refa", action="store_true", help="șterge istoricul simulat și îl regenerează")
    a = p.parse_args()
    db.initializeaza()
    print(f"Zile noi: {genereaza(a.zile, refa=a.refa)}. Istoric: {rezumat()}")
