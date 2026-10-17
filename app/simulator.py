"""Simulatorul de trafic: generează, mașină cu mașină, o zi la cele 6 porți.

Fiecare mașină are o oră de sosire, o oră de plecare și o poartă. Tipuri de mașini:
  navetiști   vin dimineața (în jurul orei la care se umple poarta) și pleacă seara;
  vizitatori  vin între 9 și 17 (pe weekend 10–19) și stau 1–4 ore;
  peste noapte câteva mașini care sunt deja în parcare la 05:00;
  eveniment   mașini în plus înainte de un meci sau concert.

Când o poartă e plină, mașina e trimisă la poarta vecină (ce face sistemul real); dacă și
aceea e plină, mașina intră în oraș („fără loc”). Contextul zilei schimbă cererea:
weekend și sărbători (mult mai puțini navetiști), vacanță (-15%), ploaie (până la +10%).

Rezultatul arată ca datele pe care le-ar da camerele de la bariere, la fiecare 5 minute.
Până la pilot, din el se generează istoricul pe care învață modelul.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass

import numpy as np

from .config import PAS, PORTI, VECINI, ZI_FINAL, ZI_START
from .context import ContextZi, seed_zi

NR_SLOTURI = (ZI_FINAL - ZI_START) // PAS + 1
_IDS = [g["id"] for g in PORTI]
_INDEX = {gid: i for i, gid in enumerate(_IDS)}


@dataclass
class RezultatZi:
    ctx: ContextZi
    masini: dict[str, np.ndarray]           # mașini în parcare la fiecare 5 minute
    sosiri: dict[str, np.ndarray]           # mașini intrate în fiecare interval de 5 minute
    redirectionate: dict[str, np.ndarray]   # mașini trimise de la poarta plină la vecina ei
    fara_loc: np.ndarray                    # mașini care n-au găsit loc nicăieri


def _cereri(ctx: ContextZi, rng: np.random.Generator) -> list[tuple[float, float, int]]:
    zgomot = float(rng.lognormal(0.0, 0.05))                  # fiecare zi e puțin diferită
    f_ploaie = 1.0 + min(0.10, 0.015 * ctx.ploaie_mm)        # pe ploaie, mai mulți vin cu mașina
    cereri: list[tuple[float, float, int]] = []
    for i, g in enumerate(PORTI):
        cap = g["loc"]
        if ctx.tip_zi == 0:
            f = (0.85 if ctx.vacanta else 1.0) * f_ploaie * zgomot
            n = int(rng.poisson(cap * g["cerere"] * f))
            sos = rng.normal(g["rise"] * 60 - 5, 35, n)
            pleaca_devreme = rng.random(n) < 0.10
            plec = np.where(pleaca_devreme, rng.normal(13.5 * 60, 60, n), rng.normal(g["fall"] * 60 + 10, 50, n))
            nv = int(rng.poisson(cap * 0.12 * zgomot))
            sos_v = rng.uniform(9 * 60, 17 * 60, nv)
        else:
            f = (0.25 if ctx.tip_zi == 1 else 0.12) * f_ploaie * zgomot
            n = int(rng.poisson(cap * g["cerere"] * f))
            sos = rng.normal(g["rise"] * 60 + 90, 50, n)
            plec = rng.normal(g["fall"] * 60 - 90, 60, n)
            nv = int(rng.poisson(cap * (0.30 if ctx.tip_zi == 1 else 0.20) * zgomot))
            sos_v = rng.uniform(10 * 60, 19 * 60, nv)
        plec = np.maximum(plec, sos + 90)
        plec_v = sos_v + rng.uniform(60, 240, nv)
        nn = int(rng.poisson(cap * 0.04))
        sos_n = np.full(nn, ZI_START - 1.0)
        plec_n = rng.uniform(6 * 60, 22 * 60, nn)
        for s, p in ((sos, plec), (sos_v, plec_v), (sos_n, plec_n)):
            cereri.extend(zip(s.tolist(), p.tolist(), [i] * len(s)))
    for ev in ctx.evenimente:
        for gid in ev.porti:
            if gid not in _INDEX:
                continue
            n = int(rng.poisson(ev.masini))
            sos = rng.normal(ev.start - 50, 20, n)
            plec = np.maximum(rng.normal(ev.final + 25, 15, n), sos + 30)
            cereri.extend(zip(sos.tolist(), plec.tolist(), [_INDEX[gid]] * n))
    # cine a venit înainte de 05:00 e deja în parcare la 05:00
    cereri = [(max(s, ZI_START - 1.0), p, i) for s, p, i in cereri if s <= ZI_FINAL]
    cereri.sort()
    return cereri


def simuleaza_zi(ctx: ContextZi, seed: int | None = None) -> RezultatZi:
    rng = np.random.default_rng(seed_zi(ctx.zi) if seed is None else seed)
    cereri = _cereri(ctx, rng)
    k_porti = len(PORTI)
    capacitate = [g["loc"] for g in PORTI]
    vecin = [_INDEX[VECINI[g["id"]]] for g in PORTI]
    ocupate = [0] * k_porti
    masini = np.zeros((k_porti, NR_SLOTURI), dtype=np.int32)
    sosiri = np.zeros((k_porti, NR_SLOTURI), dtype=np.int32)
    redir = np.zeros((k_porti, NR_SLOTURI), dtype=np.int32)
    fara_loc = np.zeros(NR_SLOTURI, dtype=np.int32)
    plecari: list[tuple[float, int]] = []
    urm = 0
    for k in range(NR_SLOTURI):
        moment = ZI_START + k * PAS
        while True:   # toate sosirile și plecările până la `moment`, în ordine cronologică
            t_sos = cereri[urm][0] if urm < len(cereri) else float("inf")
            t_plec = plecari[0][0] if plecari else float("inf")
            if min(t_sos, t_plec) > moment:
                break
            if t_plec <= t_sos:
                _, i = heapq.heappop(plecari)
                ocupate[i] -= 1
                continue
            _, t_plecare, i = cereri[urm]
            urm += 1
            tinta = i
            if ocupate[i] >= capacitate[i]:
                v = vecin[i]
                if ocupate[v] < capacitate[v]:
                    tinta = v
                    redir[i, k] += 1
                else:
                    fara_loc[k] += 1
                    continue
            ocupate[tinta] += 1
            sosiri[tinta, k] += 1
            heapq.heappush(plecari, (t_plecare, tinta))
        masini[:, k] = ocupate
    return RezultatZi(
        ctx=ctx,
        masini={gid: masini[i] for i, gid in enumerate(_IDS)},
        sosiri={gid: sosiri[i] for i, gid in enumerate(_IDS)},
        redirectionate={gid: redir[i] for i, gid in enumerate(_IDS)},
        fara_loc=fara_loc,
    )
