"""Recomandarea pentru șofer: la ce poartă să lase mașina și cât câștigă față de drumul cu mașina.

Formulele sunt cele din frontend (API.recommend), mutate pe server. În plus, decizia de
redirecționare folosește ocuparea PREZISĂ la ora la care șoferul ajunge la poartă, nu doar
ocuparea de acum: dacă ajungi în 25 de minute, contează câte locuri vor fi atunci.
"""
from __future__ import annotations

import math
from typing import Callable, Optional

from .config import (CO2_KG_PE_KM, DESTINATII, LEI_PE_KM, ORIGINI, PARCARE_CENTRU_LEI, PORTI_DUPA_ID,
                     PRAG_PLIN, TARIF_PR, VECINI)
from .timp import jround


def factor_aglomeratie(t: int) -> float:
    """Cât de aglomerat e orașul la ora t (1 = liber; vârfuri la 8:00 și 17:25)."""
    h = t / 60
    return (1 + 1.25 * math.exp(-((h - 8) / 0.9) ** 2)
            + 1.0 * math.exp(-((h - 17.4) / 1.1) ** 2)
            + 0.25 * math.exp(-((h - 13) / 1.5) ** 2))


def interval_ctp(t: int) -> int:
    """Minute între două curse CTP la capătul de linie."""
    h = t / 60
    if 6.5 <= h <= 9.5 or 15.5 <= h <= 19:
        return 5
    if h < 6 or h > 21.5:
        return 15
    return 8


def recomanda(origine: int, destinatie: int, t: int, abonament: bool, stare: dict[str, dict],
              prognoza: Optional[Callable[[str, int], Optional[float]]] = None) -> dict:
    """stare = ocuparea acum (din ocupare.stare_porti); prognoza(poarta, ora) = ocuparea prezisă (0–1)."""
    nume_origine, gid, km_pana_la_poarta = ORIGINI[origine]
    nume_dest, minute_dest, km_in_oras = DESTINATII[destinatie]
    rf = factor_aglomeratie(t)
    drum = jround(km_pana_la_poarta * 1.25 * min(rf, 1.4))
    t_sosire = t + drum

    def ocupare_la_sosire(poarta: str) -> tuple[float, str]:
        acum = stare[poarta]["ocupare"]
        if prognoza is not None:
            p = prognoza(poarta, t_sosire)
            if p is not None:
                # prudent: nu trimitem pe nimeni la o poartă plină acum, chiar dacă modelul o vede eliberându-se
                return max(acum, p), "model"
        return acum, "ocupare_curenta"

    poarta = PORTI_DUPA_ID[gid]
    redirectionat = None
    occ_sosire, sursa = ocupare_la_sosire(gid)
    if occ_sosire >= PRAG_PLIN:
        vecina = PORTI_DUPA_ID[VECINI[gid]]
        occ_vecina, sursa_v = ocupare_la_sosire(vecina["id"])
        if occ_vecina < occ_sosire:
            redirectionat, poarta = poarta, vecina
            occ_sosire, sursa = occ_vecina, sursa_v

    pana_la_poarta = drum + (4 if redirectionat else 0)
    pe_jos, interval = 3, interval_ctp(t)
    asteptare = jround(interval / 2)
    calatorie = max(8, poarta["spre"] + minute_dest - (8 if poarta["id"] == "copou" and destinatie == 2 else 0))
    ultimul = 4
    prin_poarta = pana_la_poarta + pe_jos + asteptare + calatorie + ultimul

    oras = jround(km_in_oras * 2.2 * rf)
    cautare_loc = jround(4 + 7 * min(1, rf - 1))
    cu_masina = drum + oras + cautare_loc + 2

    combustibil = (km_pana_la_poarta * 2 + km_in_oras * 2) * LEI_PE_KM
    cost_masina = jround(combustibil + PARCARE_CENTRU_LEI)
    cost_pr = jround(km_pana_la_poarta * 2 * LEI_PE_KM + (0 if abonament else TARIF_PR))

    libere_sosire = max(0, round(poarta["loc"] * (1 - occ_sosire)))
    return {
        "oname": nume_origine,
        "dname": nume_dest,
        "gate": poarta["id"],           # înlocuit cu obiectul complet de main.py
        "redirected": redirectionat["id"] if redirectionat else None,
        "pr": prin_poarta,
        "car": cu_masina,
        "legs": {"toGate": pana_la_poarta, "walk": pe_jos, "wait": asteptare, "ride": calatorie, "last": ultimul},
        "search": cautare_loc,
        "carCity": oras,
        "prCost": cost_pr,
        "carCost": cost_masina,
        "co2": round(km_in_oras * 2 * CO2_KG_PE_KM, 1),
        "headway": interval,
        "prognoza": {
            "ora_sosire": t_sosire,
            "ocupare_la_sosire": round(occ_sosire, 3),
            "libere_la_sosire": libere_sosire,
            "sursa": sursa,
        },
    }
