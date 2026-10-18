"""Tarifare, verificarea cardului CTP și plata — toate pentru DEMO.

Plata e simulată: nu se procesează niciun card bancar real și nu se încasează bani.
Verificarea cardului CTP compară cu o listă de carduri de test; în realitate s-ar face
în sistemul de ticketing CTP.

Tarife (din config):
  fără card CTP:  5 lei/oră
  cu card CTP:    primele 2 ore gratis, apoi 3 lei/oră
"""
from __future__ import annotations

import re
import sqlite3
import uuid

from .config import CARD_ORE_GRATIS, CARD_TARIF_ORA, TARIF_FARA_CARD_ORA


def normalizeaza_card(card: str) -> str:
    """'1234 1234-1234 1234' -> '1234123412341234'; 'ctp 1001' -> 'CTP1001'."""
    return re.sub(r"[\s-]", "", (card or "")).upper()


def cost_sedere(ore: float, are_card: bool) -> float:
    """Costul parcării pentru o ședere de `ore` ore."""
    ore = max(0.0, float(ore))
    if are_card:
        return round(max(0.0, ore - CARD_ORE_GRATIS) * CARD_TARIF_ORA, 2)
    return round(ore * TARIF_FARA_CARD_ORA, 2)


def explica_tarif(ore: float, are_card: bool) -> str:
    """Text scurt cu modul de calcul, pentru aplicație."""
    ore = max(0.0, float(ore))
    h = f"{ore:g}".replace(".", ",")
    if are_card:
        platite = max(0.0, ore - CARD_ORE_GRATIS)
        if platite == 0:
            return f"{h} h incluse în cele {CARD_ORE_GRATIS} ore gratuite cu cardul CTP."
        p = f"{platite:g}".replace(".", ",")
        return f"{CARD_ORE_GRATIS} h gratis cu cardul CTP + {p} h × {CARD_TARIF_ORA} lei."
    return f"{h} h × {TARIF_FARA_CARD_ORA} lei (fără card CTP)."


def verifica_card(con: sqlite3.Connection, card: str) -> dict:
    """Caută cardul în lista demo. Întoarce {valid, nume, card}."""
    norm = normalizeaza_card(card)
    if not norm:
        return {"valid": False, "card": "", "mesaj": "Introdu numărul cardului CTP."}
    r = con.execute("SELECT nume FROM carduri_ctp WHERE card=?", (norm,)).fetchone()
    if r:
        return {"valid": True, "card": norm, "nume": r["nume"],
                "mesaj": f"Card CTP valid · {r['nume']}. Ai 2 ore gratuite."}
    return {"valid": False, "card": norm,
            "mesaj": "Card CTP negăsit. Poți parca fără card, cu 5 lei/oră."}


def cod_tranzactie() -> str:
    return "TX-" + uuid.uuid4().hex[:8].upper()
