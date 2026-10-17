"""Numere de înmatriculare românești: validare, formatare și corectarea erorilor tipice de OCR.

Formate acceptate:
  județ:     IS 23 OKC   (2 litere + 2 cifre + 3 litere)
  București: B 123 ABC   (B + 2 sau 3 cifre + 3 litere)
"""
from __future__ import annotations

import re

JUDETE = {
    "AB", "AG", "AR", "B", "BC", "BH", "BN", "BR", "BT", "BV", "BZ", "CJ", "CL", "CS", "CT", "CV",
    "DB", "DJ", "GJ", "GL", "GR", "HD", "HR", "IF", "IL", "IS", "MH", "MM", "MS", "NT", "OT", "PH",
    "SB", "SJ", "SM", "SV", "TL", "TM", "TR", "VL", "VN", "VS",
}

# Confuzii frecvente la citirea automată
_CIFRA_IN_LITERA = {"0": "O", "1": "I", "2": "Z", "4": "A", "5": "S", "6": "G", "7": "T", "8": "B"}
_LITERA_IN_CIFRA = {"O": "0", "Q": "0", "D": "0", "U": "0", "I": "1", "L": "1", "J": "1", "T": "7",
                    "Z": "2", "S": "5", "B": "8", "G": "6", "A": "4"}
_TIPARE = {7: ("LLCCLLL", "LCCCLLL"), 6: ("LCCLLL",)}   # județ / București cu 3 cifre / București cu 2 cifre


def _curata(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def normalizeaza(text: str) -> str | None:
    """Întoarce numărul în forma standard ('IS 23 OKC') sau None dacă nu e un număr valid."""
    s = _curata(text)
    m = re.fullmatch(r"B(\d{2,3})([A-Z]{3})", s)
    if m:
        return f"B {m[1]} {m[2]}"
    m = re.fullmatch(r"([A-Z]{2})(\d{2})([A-Z]{3})", s)
    if m and m[1] in JUDETE:
        return f"{m[1]} {m[2]} {m[3]}"
    return None


def _forteaza(sir: str, tipare: str) -> tuple[str, int] | None:
    """Aplică tiparul (L = literă, C = cifră); întoarce textul corectat și câte caractere au fost schimbate."""
    rez, schimbari = [], 0
    for ch, tip in zip(sir, tipare):
        nou = _CIFRA_IN_LITERA.get(ch, ch) if tip == "L" else _LITERA_IN_CIFRA.get(ch, ch)
        if (tip == "L" and not nou.isalpha()) or (tip == "C" and not nou.isdigit()):
            return None
        schimbari += nou != ch
        rez.append(nou)
    return "".join(rez), schimbari


def corecteaza_ocr(text: str) -> str | None:
    """Transformă un text citit de OCR în cel mai plauzibil număr valid, sau None.

    Încearcă textul întreg, bucăți din el (rama, banda „RO”) și variante cu un caracter în plus scos,
    apoi alege varianta care cere cele mai puține corecturi.
    Ex.: 'IS23 0KC' -> 'IS 23 OKC', '1S 23 OKC' -> 'IS 23 OKC', 'VS0O5BRL' -> 'VS 05 BRL'.
    """
    direct = normalizeaza(text)
    if direct:
        return direct
    s = _curata(text)
    if len(s) < 6 or len(s) > 12:
        return None
    # șir de încercat -> (cost, câte caractere am scos). Caracterele în plus de la început (banda „RO”,
    # rama) sunt frecvente și costă 1; cele de la sfârșit sau din mijloc costă 2, ca o literă corectată.
    variante: dict[str, tuple[int, int]] = {}

    def adauga(sir: str, cost: int, scoase: int) -> None:
        if sir not in variante or (cost, scoase) < variante[sir]:
            variante[sir] = (cost, scoase)

    for lung in (7, 6):
        for start in range(0, len(s) - lung + 1):
            dreapta = len(s) - start - lung
            adauga(s[start:start + lung], start + 2 * dreapta, start + dreapta)
    if len(s) in (7, 8):
        for i in range(len(s)):
            adauga(s[:i] + s[i + 1:], 1 if i == 0 else 2, 1)
    cel_mai_bun: tuple[int, int, str] | None = None
    for sir, (cost_scoase, scoase) in variante.items():
        for tipare in _TIPARE.get(len(sir), ()):
            fortat = _forteaza(sir, tipare)
            if not fortat:
                continue
            candidat, schimbari = fortat
            if tipare.startswith("LC") and candidat[0] != "B":
                continue
            numar = normalizeaza(candidat)
            if numar:
                cheie = (schimbari * 2 + cost_scoase, scoase, numar)
                if cel_mai_bun is None or cheie < cel_mai_bun:
                    cel_mai_bun = cheie
    return cel_mai_bun[2] if cel_mai_bun else None
