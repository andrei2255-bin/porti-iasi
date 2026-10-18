"""Porțile Iașului – serverul (backend).

Pornire:   python -m app            (sau: uvicorn app.main:app --reload)
Frontend:  http://localhost:8000
Documentație și testare endpoint-uri: http://localhost:8000/docs
"""
from __future__ import annotations

import logging
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import Literal, Optional

import numpy as np
from pydantic import BaseModel, Field
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import anpr, db, istoric, predictie
from .config import (CAPACITATE_TOTALA, CARD_ORE_GRATIS, CARD_TARIF_ORA, CO2_KG_PE_KM, DESTINATII, DIR_STATIC,
                     KM_EVITATI_PE_MASINA, ORE_IMPLICIT, ORIGINI, PAS, PERSOANE_PE_MASINA, PORTI, PORTI_DUPA_ID,
                     PRAG_PLIN, REZERVARE_MIN, TARIF_FARA_CARD_ORA, VECINI, ZI_START)
from .logica import recomanda
from .plata import cod_tranzactie, cost_sedere, explica_tarif, normalizeaza_card, verifica_card
from .numere import corecteaza_ocr, normalizeaza
from .ocupare import (context_cu_scenariu, cronologie, poarta_api, rezultat_zi, scenariu_curent, sector_si_loc,
                      seteaza_scenariu, stare_porti)
from .predictie import PROGNOZATOR
from .surse.evenimente import Eveniment
from .timp import din_ora, jround, limiteaza, ora, ora_curenta, slot, zi_demo
from .web import Api, EroareAPI

log = logging.getLogger("porti")

api = Api(
    titlu="Porțile Iașului – API",
    versiune="1.0",
    descriere=(
        "Backendul pentru Park & Ride inteligent în Iași (echipa OK COMPUTER).\n\n"
        "Ora se transmite ca **minute de la miezul nopții**: `t=510` înseamnă 08:30. "
        "Dacă lipsește, se folosește ora reală din Iași. Ziua implicită este ziua demo-ului."
    ),
)

# ======================================================================
# Modele pentru cereri
# ======================================================================

_DESC_T = "Ora simulată, în minute de la miezul nopții (510 = 08:30). Lipsă = ora reală din Iași."
_DESC_ZI = "Ziua (AAAA-LL-ZZ). Lipsă = ziua demo-ului."


class QueryTimp(BaseModel):
    t: Optional[int] = Field(None, ge=0, le=1439, description=_DESC_T)
    zi: Optional[date] = Field(None, description=_DESC_ZI)


class CerereRecomandare(BaseModel):
    origine: int = Field(..., ge=0, le=len(ORIGINI) - 1,
                         description="Indexul comunei: " + ", ".join(f"{i} = {o[0]}" for i, o in enumerate(ORIGINI)))
    destinatie: int = Field(..., ge=0, le=len(DESTINATII) - 1,
                            description="Indexul destinației: " + ", ".join(f"{i} = {d[0]}" for i, d in enumerate(DESTINATII)))
    t: Optional[int] = Field(None, ge=0, le=1439, description=_DESC_T)
    abonament: bool = Field(True, description="Șoferul are abonament CTP")
    zi: Optional[date] = Field(None, description=_DESC_ZI)


class CerereCard(BaseModel):
    card: str = Field(..., description="Numărul cardului CTP (demo). Carduri de test: CTP1001, 1234 1234 1234 1234")


class CerereRezervare(BaseModel):
    poarta: str = Field(..., description="Id-ul porții: " + ", ".join(p["id"] for p in PORTI))
    numar: str = Field(..., description="Numărul mașinii, ex. IS 23 OKC sau B 123 ABC")
    t: Optional[int] = Field(None, ge=0, le=1439, description=_DESC_T)
    abonament: bool = Field(True, description="Șoferul are card/abonament CTP (dacă nu dă card_ctp)")
    card_ctp: Optional[str] = Field(None, description="Numărul cardului CTP (demo). Dacă e valid, 2 ore gratuite.")
    ore: float = Field(float(ORE_IMPLICIT), ge=0.5, le=24, description="Durata estimată de ședere, în ore")
    zi: Optional[date] = Field(None, description=_DESC_ZI)


class CererePlata(BaseModel):
    rezervare: str = Field(..., description="Id-ul rezervării de plătit")
    nume: Optional[str] = Field(None, description="Numele de pe card (demo)")
    numar_card: Optional[str] = Field(None, description="Numărul cardului bancar (demo; nu se procesează real)")


class EvenimentBariera(BaseModel):
    numar: str = Field(..., description="Numărul citit de cameră (se corectează automat erorile tipice de citire)")
    poarta: Optional[str] = Field(None, description="Poarta. Lipsă = poarta din rezervarea mașinii.")
    tip: Literal["intrare", "iesire"] = "intrare"
    t: Optional[int] = Field(None, ge=0, le=1439, description=_DESC_T)
    zi: Optional[date] = Field(None, description=_DESC_ZI)


def _zi_t(zi: Optional[date], t: Optional[int]) -> tuple[date, int]:
    return (zi or zi_demo()), (limiteaza(t) if t is not None else ora_curenta())


def _poarta_sau_eroare(gid: str) -> dict:
    if gid not in PORTI_DUPA_ID:
        raise EroareAPI(404, f"Poarta „{gid}” nu există. Porți valide: {', '.join(PORTI_DUPA_ID)}.")
    return PORTI_DUPA_ID[gid]


# ======================================================================
# Prognoza (partea de AI), folosită de recomandări și de dispecerat
# ======================================================================

def _ocupari(zi: date, t: int) -> tuple[dict, dict, dict]:
    """Starea porților acum și ocuparea de acum 30 de minute (cât de repede se umple fiecare poartă)."""
    with db.conexiune() as con:
        acum = stare_porti(con, zi, t)
        inainte = stare_porti(con, zi, max(ZI_START, t - 30))
    return acum, {g: s["ocupare"] for g, s in acum.items()}, {g: s["ocupare"] for g, s in inainte.items()}


def _prognoza(zi: date, t: int, porti: Optional[list[str]] = None) -> tuple[dict, dict]:
    stare, acum, inainte = _ocupari(zi, t)
    return stare, PROGNOZATOR.prezice(context_cu_scenariu(zi), t, acum, inainte, porti)


def _prognoza_la(zi: date, t: int, gid: str, t_tinta: int) -> Optional[float]:
    """Ocuparea prezisă a unei porți la ora t_tinta, sau None dacă modelul nu e gata."""
    if PROGNOZATOR.pachet is None or t_tinta <= t:
        return None
    p = _prognoza(zi, t, [gid])[1][gid]
    return float(np.interp(t_tinta, p["ore"], p["ocupare"])) if p["ore"] else None


def _cere_model() -> dict:
    if PROGNOZATOR.pachet is None:
        raise EroareAPI(503, "Modelul de predicție nu e încă antrenat. Reîncercați în câteva secunde.")
    return PROGNOZATOR.pachet


# ======================================================================
# Endpoint-urile folosite de frontend
# ======================================================================

@api.ruta("GET", "/api/health", tag="Sistem", rezumat="Verifică dacă serverul merge")
async def health(request: Request):
    return {"stare": "ok", "zi_demo": zi_demo().isoformat(), "ora_reala": ora(ora_curenta())}


@api.ruta("GET", "/api/gates", query=QueryTimp, tag="Porți", rezumat="Starea porților la o anumită oră")
async def gates(request: Request, q: QueryTimp):
    """Lista celor 6 porți, cu ocuparea (0–1) și locurile libere. Același format ca API.gates() din frontend."""
    zi, t = _zi_t(q.zi, q.t)
    with db.conexiune() as con:
        stare = stare_porti(con, zi, t)
    return [poarta_api(g["id"], stare[g["id"]]) for g in PORTI]


@api.ruta("POST", "/api/recommend", corp=CerereRecomandare, tag="Șofer", rezumat="Recomandă poarta pentru un traseu")
async def recommend(request: Request, corp: CerereRecomandare):
    """Poarta potrivită, timpii (prin poartă vs. cu mașina), costurile și eventuala redirecționare
    când poarta firească va fi plină la ora sosirii. Același format ca API.recommend() din frontend."""
    zi, t = _zi_t(corp.zi, corp.t)
    with db.conexiune() as con:
        stare = stare_porti(con, zi, t)
    prognoza = (lambda gid, t_tinta: _prognoza_la(zi, t, gid, t_tinta)) if PROGNOZATOR.pachet else None
    rec = recomanda(corp.origine, corp.destinatie, t, corp.abonament, stare, prognoza)
    # dacă poarta firească e sub lucrări (capacitate redusă) și am redirecționat, spunem de ce
    naturala = ORIGINI[corp.origine][1]
    rec["lucrari_nota"] = None
    if rec["redirected"]:
        ctx = context_cu_scenariu(zi)
        lu = next((x for x in ctx.lucrari if x.poarta == naturala), None)
        if lu:
            rec["lucrari_nota"] = f"{lu.nume}: P+R {PORTI_DUPA_ID[naturala]['nume']} e semi-închis azi."
    rec["gate"] = poarta_api(rec["gate"], stare[rec["gate"]])
    if rec["redirected"]:
        rec["redirected"] = poarta_api(rec["redirected"], stare[rec["redirected"]])
    rec["prognoza"]["ora_sosire_text"] = ora(rec["prognoza"]["ora_sosire"])
    return rec


@api.ruta("POST", "/api/ctp/verifica", corp=CerereCard, tag="Șofer", rezumat="Verifică un card CTP (demo)")
async def ctp_verifica(request: Request, corp: CerereCard):
    """Verifică dacă numărul de card CTP e valid. Demo: compară cu o listă de carduri de test."""
    with db.conexiune() as con:
        rez = verifica_card(con, corp.card)
    rez["tarif"] = {"fara_card_ora": TARIF_FARA_CARD_ORA, "ore_gratis": CARD_ORE_GRATIS, "cu_card_ora": CARD_TARIF_ORA}
    return rez


def _rezervare_json(r, g_nume: Optional[str] = None) -> dict:
    return {"id": r["id"], "gid": r["poarta"], "poarta": g_nume or PORTI_DUPA_ID[r["poarta"]]["nume"],
            "plate": r["numar"], "numar": r["numar"], "minute": REZERVARE_MIN, "expira_la": ora(r["expira_t"]),
            "ore": r["ore"], "cost": r["cost"], "card": r["card"], "platit": bool(r["platit"]),
            "tranzactie": r["tranzactie"], "stare": r["stare"],
            "explicatie_tarif": explica_tarif(r["ore"], bool(r["card"])),
            "necesita_plata": r["cost"] > 0 and not r["platit"]}


@api.ruta("POST", "/api/reservations", corp=CerereRezervare, tag="Șofer", rezumat="Rezervă un loc și calculează costul")
async def reservations(request: Request, corp: CerereRezervare):
    """Păstrează un loc la poartă, verifică cardul CTP și calculează costul șederii.
    Dacă rezultă un cost, se plătește cu POST /api/plata. O mașină are o singură rezervare activă."""
    g = _poarta_sau_eroare(corp.poarta)
    numar = normalizeaza(corp.numar)
    if not numar:
        raise EroareAPI(422, "Scrie numărul ca pe plăcuță, de exemplu IS 23 OKC sau B 123 ABC.")
    zi, t = _zi_t(corp.zi, corp.t)
    with db.conexiune() as con:
        # cardul CTP: fie e dat explicit și verificat, fie semnalul vechi „abonament”
        card = None
        if corp.card_ctp:
            v = verifica_card(con, corp.card_ctp)
            card = v["card"] if v["valid"] else None
        elif corp.abonament:
            card = normalizeaza_card(numar)   # compatibilitate cu site-ul vechi (trimite doar abonament=true)
        are_card = card is not None
        cost = cost_sedere(corp.ore, are_card)

        con.execute("UPDATE rezervari SET stare='anulata' WHERE zi=? AND numar=? AND stare='activa'",
                    (zi.isoformat(), numar))
        stare = stare_porti(con, zi, t)
        if stare[g["id"]]["libere"] <= 0:
            alt = PORTI_DUPA_ID[VECINI[g["id"]]]
            raise EroareAPI(409, f"P+R {g['nume']} e plină. Încearcă P+R {alt['nume']} "
                                 f"({stare[alt['id']]['libere']} locuri libere).", alternativa=alt["id"])
        if are_card:
            # Demo: legăm numărul de un abonament CTP valid, ca bariera să-l recunoască.
            con.execute(
                "INSERT INTO abonamente_ctp(numar, card, valabil_pana, sursa) VALUES (?,?,?,'aplicatie') "
                "ON CONFLICT(numar) DO UPDATE SET valabil_pana=MAX(valabil_pana, excluded.valabil_pana)",
                (numar, card, (zi + timedelta(days=30)).isoformat()),
            )
        rid = "R" + uuid.uuid4().hex[:7].upper()
        platit = 1 if cost == 0 else 0     # gratuit = nimic de plătit
        con.execute(
            "INSERT INTO rezervari(id, poarta, numar, zi, t, expira_t, bilet_platit, stare, ore, cost, card, "
            "platit, tranzactie, creat_la) VALUES (?,?,?,?,?,?,?,'activa',?,?,?,?,?,?)",
            (rid, g["id"], numar, zi.isoformat(), t, t + REZERVARE_MIN, 0 if are_card else 1,
             corp.ore, cost, card, platit, None, db.acum_iso()),
        )
        r = con.execute("SELECT * FROM rezervari WHERE id=?", (rid,)).fetchone()
    rez = _rezervare_json(r, g["nume"])
    rez["tarif"] = cost          # compatibilitate cu site-ul vechi (câmpul „tarif”)
    rez["are_card"] = are_card
    return rez


@api.ruta("POST", "/api/plata", corp=CererePlata, tag="Șofer", rezumat="Plătește o rezervare (demo)")
async def plata(request: Request, corp: CererePlata):
    """Plată SIMULATĂ: nu se procesează niciun card bancar real. Marchează rezervarea ca plătită."""
    with db.conexiune() as con:
        r = con.execute("SELECT * FROM rezervari WHERE id=?", (corp.rezervare,)).fetchone()
        if not r:
            raise EroareAPI(404, "Rezervarea nu există.")
        if r["stare"] == "anulata":
            raise EroareAPI(409, "Rezervarea a fost anulată.")
        if r["platit"]:
            return {**_rezervare_json(r), "mesaj": "Rezervarea e deja plătită."}
        if r["cost"] <= 0:
            con.execute("UPDATE rezervari SET platit=1 WHERE id=?", (r["id"],))
        else:
            tx = cod_tranzactie()
            con.execute("UPDATE rezervari SET platit=1, tranzactie=? WHERE id=?", (tx, r["id"]))
        r = con.execute("SELECT * FROM rezervari WHERE id=?", (r["id"],)).fetchone()
    lei = f"{r['cost']:g}".replace(".", ",")
    return {**_rezervare_json(r), "mesaj": f"Plată reușită: {lei} lei. (demo — fără tranzacție reală)"}


@api.ruta("GET", "/api/reservations/{id}", tag="Șofer", rezumat="Starea unei rezervări")
async def reservation_status(request: Request):
    with db.conexiune() as con:
        r = con.execute("SELECT * FROM rezervari WHERE id=?", (request.path_params["id"],)).fetchone()
    if not r:
        raise EroareAPI(404, "Rezervarea nu există.")
    return _rezervare_json(r)


@api.ruta("POST", "/api/gate-events", corp=EvenimentBariera, tag="Barieră", rezumat="Camera de la barieră a citit un număr")
async def gate_events(request: Request, corp: EvenimentBariera):
    """Intrare: verifică abonamentul CTP, ridică bariera și alocă un loc.
    Ieșire: închide șederea. Același format ca API.gateEntry() din frontend."""
    zi, t = _zi_t(corp.zi, corp.t)
    numar = corecteaza_ocr(corp.numar)
    if not numar:
        return {"recunoscut": False, "permis": False, "text_citit": corp.numar,
                "mesaj": "Numărul nu a putut fi citit. Bariera rămâne închisă; operatorul e anunțat."}
    with db.conexiune() as con:
        return _eveniment_bariera(con, zi, t, numar, corp.poarta, corp.tip)


def _eveniment_bariera(con, zi: date, t: int, numar: str, poarta: Optional[str], tip: str) -> dict:
    ultim = con.execute(
        "SELECT * FROM evenimente_bariera WHERE zi=? AND numar=? ORDER BY t DESC, id DESC LIMIT 1",
        (zi.isoformat(), numar)).fetchone()
    inauntru = ultim is not None and ultim["tip"] == "intrare"

    if tip == "iesire":
        if not inauntru:
            raise EroareAPI(409, f"Mașina {numar} nu e înregistrată în nicio parcare.")
        t_iesire = max(t, ultim["t"])
        con.execute(
            "INSERT INTO evenimente_bariera(poarta, numar, zi, t, tip, abonament, tarif, creat_la) "
            "VALUES (?,?,?,?, 'iesire', ?, 0, ?)",
            (ultim["poarta"], numar, zi.isoformat(), t_iesire, ultim["abonament"], db.acum_iso()))
        return {"recunoscut": True, "permis": True, "numar": numar, "poarta": ultim["poarta"],
                "durata_min": t_iesire - ultim["t"], "tarif": ultim["tarif"], "mesaj": "Bariera se ridică. Drum bun!"}

    if inauntru:
        return {"recunoscut": True, "permis": True, "numar": numar, "poarta": ultim["poarta"],
                "abonament": bool(ultim["abonament"]), "tarif": ultim["tarif"], "sector": ultim["sector"],
                "loc": ultim["loc"], "mesaj": "Mașina e deja înregistrată în parcare."}

    rez = con.execute(
        "SELECT * FROM rezervari WHERE zi=? AND numar=? AND stare='activa' ORDER BY creat_la DESC LIMIT 1",
        (zi.isoformat(), numar)).fetchone()
    gid = poarta or (rez["poarta"] if rez else None)
    if not gid:
        raise EroareAPI(422, "Lipsește poarta (și mașina nu are rezervare).")
    g = _poarta_sau_eroare(gid)
    are_rezervare = rez is not None and rez["poarta"] == gid

    ab = con.execute("SELECT valabil_pana FROM abonamente_ctp WHERE numar=?", (numar,)).fetchone()
    abonament = ab is not None and ab["valabil_pana"] >= zi.isoformat()

    stare = stare_porti(con, zi, t)[gid]
    if not are_rezervare and stare["libere"] <= 0:
        alt = PORTI_DUPA_ID[VECINI[gid]]
        return {"recunoscut": True, "permis": False, "numar": numar, "poarta": gid, "abonament": abonament,
                "tarif": 0, "mesaj": f"Parcare plină. Mergeți la P+R {alt['nume']}."}

    # Mesajul de la barieră reflectă plata făcută la rezervare (noul model: plata e în aplicație).
    if are_rezervare and rez["platit"]:
        lei = f"{rez['cost']:g}".replace(".", ",")
        tarif = int(round(rez["cost"]))
        mesaj = "Card CTP valid. Parcare gratuită (2 ore incluse)." if rez["cost"] == 0 \
            else f"Plătit la rezervare: {lei} lei. Bariera se ridică."
    elif are_rezervare:
        tarif = int(round(rez["cost"]))
        mesaj = "Rezervare găsită, dar neplătită. Finalizează plata în aplicație."
    elif abonament:
        tarif = 0
        mesaj = f"Card CTP valid. Primele {CARD_ORE_GRATIS} ore gratuite, apoi {CARD_TARIF_ORA} lei/oră."
    else:
        tarif = 0
        mesaj = f"Fără card CTP: {TARIF_FARA_CARD_ORA} lei/oră, se plătește la ieșire."

    sector, loc = sector_si_loc(min(g["loc"], stare["masini"] + (0 if are_rezervare else 1)))
    con.execute(
        "INSERT INTO evenimente_bariera(poarta, numar, zi, t, tip, abonament, tarif, sector, loc, creat_la) "
        "VALUES (?,?,?,?, 'intrare', ?,?,?,?,?)",
        (gid, numar, zi.isoformat(), t, int(abonament), tarif, sector, loc, db.acum_iso()))
    if rez is not None:
        con.execute("UPDATE rezervari SET stare='folosita' WHERE id=?", (rez["id"],))
    return {"recunoscut": True, "permis": True, "numar": numar, "poarta": gid, "abonament": abonament,
            "tarif": tarif, "sector": sector, "loc": loc,
            "rezervare": rez["id"] if are_rezervare else None,
            "platit": bool(rez["platit"]) if are_rezervare else False, "mesaj": mesaj}


# ======================================================================
# Bariera cu cameră: recunoașterea numărului din poză (ANPR)
# ======================================================================

_CAMP_FOTO = {"type": "string", "format": "binary", "description": "Poza mașinii (JPG sau PNG), cu plăcuța vizibilă"}
_FORMULAR_FOTO = {"type": "object", "required": ["foto"], "properties": {"foto": _CAMP_FOTO}}
_FORMULAR_BARIERA = {"type": "object", "required": ["foto"], "properties": {
    "foto": _CAMP_FOTO,
    "poarta": {"type": "string", "description": "Poarta. Lipsă = poarta din rezervarea mașinii."},
    "tip": {"type": "string", "enum": ["intrare", "iesire"], "default": "intrare"},
    "t": {"type": "integer", "description": _DESC_T},
    "zi": {"type": "string", "format": "date", "description": _DESC_ZI},
}}
_MAX_FOTO = 10 * 1024 * 1024


async def _citeste_foto(request: Request):
    try:
        formular = await request.form(max_part_size=_MAX_FOTO)
    except Exception:
        raise EroareAPI(400, "Trimiteți poza ca formular multipart, în câmpul „foto”.")
    foto = formular.get("foto")
    if foto is None or not hasattr(foto, "read"):
        raise EroareAPI(422, "Lipsește poza (câmpul „foto”).")
    octeti = await foto.read()
    if len(octeti) > _MAX_FOTO:
        raise EroareAPI(413, "Poza e prea mare (maximum 10 MB).")
    return octeti, formular


async def _anpr(octeti: bytes) -> dict:
    try:
        return await run_in_threadpool(anpr.citeste_numar, octeti)
    except anpr.ANPRIndisponibil as e:
        raise EroareAPI(503, str(e))
    except ValueError as e:
        raise EroareAPI(422, str(e))


@api.ruta("GET", "/api/anpr/stare", tag="Barieră", rezumat="Ce motor de recunoaștere a numerelor e disponibil")
async def anpr_stare(request: Request):
    return await run_in_threadpool(anpr.stare_motor)


@api.ruta("POST", "/api/anpr", formular=_FORMULAR_FOTO, tag="Barieră", rezumat="Citește numărul dintr-o poză")
async def anpr_poza(request: Request):
    """Recunoaște numărul de înmatriculare (doar numere românești valide)."""
    octeti, _ = await _citeste_foto(request)
    return await _anpr(octeti)


@api.ruta("POST", "/api/gate-events/foto", formular=_FORMULAR_BARIERA, tag="Barieră",
          rezumat="Bariera cu cameră: poză → număr → intrare sau ieșire")
async def gate_events_foto(request: Request):
    """Ce face bariera reală: citește numărul din poză, verifică abonamentul și ridică bariera."""
    octeti, formular = await _citeste_foto(request)
    citire = await _anpr(octeti)
    if not citire["recunoscut"]:
        return {"recunoscut": False, "permis": False, "anpr": citire,
                "mesaj": "Numărul nu a putut fi citit. Bariera rămâne închisă; operatorul e anunțat."}
    campuri = {k: v for k, v in formular.items() if k != "foto" and v not in ("", None)}
    ev = EvenimentBariera.model_validate({**campuri, "numar": citire["numar"]})
    zi, t = _zi_t(ev.zi, ev.t)
    with db.conexiune() as con:
        rezultat = _eveniment_bariera(con, zi, t, citire["numar"], ev.poarta, ev.tip)
    return {**rezultat, "anpr": citire}


# ======================================================================
# Dispeceratul: prognoze, cronologia zilei, statistici
# ======================================================================

class QueryZi(BaseModel):
    zi: Optional[date] = Field(None, description=_DESC_ZI)


def _alerte(zi: date, t: int, stare: dict, prognoza: dict) -> list[dict]:
    """Sugestiile pentru dispecerat, ordonate după urgență."""
    alerte = []
    ctx = context_cu_scenariu(zi)
    for lu in ctx.lucrari:   # lucrări = capacitate redusă toată ziua (ex. șine de tramvai)
        vecina = PORTI_DUPA_ID[VECINI[lu.poarta]]
        alerte.append({"poarta": lu.poarta, "tip": "lucrari", "urgenta": 5,
                       "mesaj": f"{lu.nume}: P+R {PORTI_DUPA_ID[lu.poarta]['nume']} e semi-închis "
                                f"(capacitate redusă cu {lu.procent_blocat}%). Mașinile sunt trimise la "
                                f"P+R {vecina['nume']} ({stare[vecina['id']]['libere']} locuri libere)."})
    perechi_pline: set[frozenset] = set()
    for g in PORTI:
        gid, s, p = g["id"], stare[g["id"]], prognoza[g["id"]]
        vecina = PORTI_DUPA_ID[VECINI[gid]]
        pereche = frozenset((gid, vecina["id"]))
        if s["ocupare"] >= PRAG_PLIN and stare[vecina["id"]]["ocupare"] >= PRAG_PLIN:
            if pereche not in perechi_pline:  # o singură alertă pentru aceeași pereche de porți pline
                perechi_pline.add(pereche)
                alerte.append({"poarta": gid, "tip": "capacitate", "urgenta": 4,
                               "mesaj": f"P+R {g['nume']} și P+R {vecina['nume']} sunt amândouă aproape pline. "
                                        f"Panourile de pe drumul dinspre {g['din'].split(' · ')[0]} anunță parcările "
                                        f"pline. Dacă se repetă zilnic, zona are nevoie de locuri în plus sau de mai "
                                        f"multe curse CTP din comune."})
        elif s["ocupare"] >= PRAG_PLIN:
            alerte.append({"poarta": gid, "tip": "plina", "urgenta": 3,
                           "mesaj": f"P+R {g['nume']} e aproape plină. Panourile de pe drumul dinspre "
                                    f"{g['din'].split(' · ')[0]} trimit mașinile la P+R {vecina['nume']} "
                                    f"({stare[vecina['id']]['libere']} locuri libere)."})
        elif p["se_umple_la"] is not None and p["se_umple_la"] - t <= 60:
            alerte.append({"poarta": gid, "tip": "se_umple", "urgenta": 2,
                           "mesaj": f"Predicție: P+R {g['nume']} se umple în jurul orei {ora(p['se_umple_la'])}. "
                                    f"Recomandare: o cursă CTP în plus de la capătul de linie și anunț pe panouri."})
        for ev in ctx.evenimente:
            if gid in ev.porti and ev.start - 180 <= t <= ev.start:
                alerte.append({"poarta": gid, "tip": "eveniment", "urgenta": 1,
                               "mesaj": f"{ev.nume} la {ora(ev.start)}: se așteaptă ~{ev.masini} mașini în plus "
                                        f"la P+R {g['nume']}."})
    return sorted(alerte, key=lambda a: -a["urgenta"])


def _forecast_poarta(gid: str, s: dict, p: dict) -> dict:
    cap = PORTI_DUPA_ID[gid]["loc"]
    return {
        "ocupare_acum": round(s["ocupare"], 4),
        "libere_acum": s["libere"],
        "se_umple_la": p["se_umple_la"],
        "se_umple_la_text": ora(p["se_umple_la"]) if p["se_umple_la"] is not None else None,
        "prognoza": [{"t": t1, "ora": ora(t1), "ocupare": v, "libere": max(0, round(cap * (1 - v)))}
                     for t1, v in zip(p["ore"], p["ocupare"])],
    }


def _info_model(pachet: dict) -> dict:
    return {"versiune": pachet["versiune"], "antrenat_la": pachet["antrenat_la"],
            "eroare_60_min_pp": pachet["metrici"]["la_60_min"]["model_ai"]}


@api.ruta("GET", "/api/forecast", query=QueryTimp, tag="Dispecerat (AI)", rezumat="Prognoza AI pentru toate porțile")
async def forecast(request: Request, q: QueryTimp):
    """Ocuparea prezisă pentru următoarele 4 ore (la 5 minute), ora la care se umple fiecare poartă,
    contextul zilei (vreme, sărbători, evenimente) și sugestiile pentru dispecerat."""
    pachet = _cere_model()
    zi, t = _zi_t(q.zi, q.t)
    stare, prog = _prognoza(zi, t)
    return {"zi": zi.isoformat(), "t": t, "ora": ora(t), "model": _info_model(pachet),
            "context": context_cu_scenariu(zi).ca_dict(),
            "porti": {g["id"]: _forecast_poarta(g["id"], stare[g["id"]], prog[g["id"]]) for g in PORTI},
            "alerte": _alerte(zi, t, stare, prog)}


@api.ruta("GET", "/api/gates/{id}/forecast", query=QueryTimp, tag="Dispecerat (AI)", rezumat="Prognoza AI pentru o poartă")
async def forecast_poarta(request: Request, q: QueryTimp):
    pachet = _cere_model()
    gid = _poarta_sau_eroare(request.path_params["id"])["id"]
    zi, t = _zi_t(q.zi, q.t)
    stare, prog = _prognoza(zi, t, [gid])
    return {"zi": zi.isoformat(), "t": t, "ora": ora(t), "poarta": gid, "model": _info_model(pachet),
            **_forecast_poarta(gid, stare[gid], prog[gid])}


@api.ruta("GET", "/api/timeline", query=QueryZi, tag="Dispecerat (AI)", rezumat="Ocuparea pe toată ziua")
async def timeline(request: Request, q: QueryZi):
    """Ocuparea fiecărei porți la fiecare 5 minute, 05:00–23:00. Frontendul o folosește pentru hartă,
    tabel, grafic și panouri (o singură cerere la încărcare, apoi reîmprospătare periodică)."""
    zi = q.zi or zi_demo()
    with db.conexiune() as con:
        masini = cronologie(con, zi)
    return {"zi": zi.isoformat(), "start": ZI_START, "pas": PAS,
            "capacitate": {g["id"]: g["loc"] for g in PORTI},
            "porti": {gid: [round(m / PORTI_DUPA_ID[gid]["loc"], 4) for m in v] for gid, v in masini.items()},
            "masini": masini,
            "context": context_cu_scenariu(zi).ca_dict()}


@api.ruta("GET", "/api/stats", query=QueryTimp, tag="Dispecerat (AI)", rezumat="Indicatorii zilei până la ora dată")
async def stats(request: Request, q: QueryTimp):
    """Mașini oprite în afara centrului, călătorii CTP noi, CO₂ evitat (cu ipotezele din config)."""
    zi, t = _zi_t(q.zi, q.t)
    rez, k = rezultat_zi(zi), slot(t)
    with db.conexiune() as con:
        stare = stare_porti(con, zi, t)
        intrari = con.execute("SELECT COUNT(*) FROM evenimente_bariera WHERE zi=? AND tip='intrare' AND t<=?",
                              (zi.isoformat(), t)).fetchone()[0]
    oprite = int(sum(int(v[:k + 1].sum()) for v in rez.sosiri.values())) + intrari
    return {
        "zi": zi.isoformat(), "t": t, "ora": ora(t),
        "parcate_acum": sum(s["masini"] for s in stare.values()),
        "capacitate": CAPACITATE_TOTALA,
        "oprite_azi": oprite,
        "calatorii_ctp_noi": jround(oprite * PERSOANE_PE_MASINA * 2),
        "co2_evitat_t": round(oprite * KM_EVITATI_PE_MASINA * CO2_KG_PE_KM / 1000, 1),
        "redirectionate_azi": int(sum(int(v[:k + 1].sum()) for v in rez.redirectionate.values())),
        "fara_loc_azi": int(rez.fara_loc[:k + 1].sum()),
        "ipoteze": {"persoane_pe_masina": PERSOANE_PE_MASINA, "km_evitati_pe_masina": KM_EVITATI_PE_MASINA,
                    "co2_kg_pe_km": CO2_KG_PE_KM},
    }


# ---------- modelul: informații și învățare ----------

_lacat_antrenare = threading.Lock()


@api.ruta("GET", "/api/model", tag="Model AI", rezumat="Ce știe modelul și cât de precis e")
async def model_info(request: Request):
    pachet = _cere_model()
    return {"versiune": pachet["versiune"], "antrenat_la": pachet["antrenat_la"],
            "algoritm": "Gradient boosting pe arbori de decizie (scikit-learn HistGradientBoostingRegressor)",
            "zile_istoric": pachet["zile_istoric"], "istoric_de_la": pachet["istoric_de_la"],
            "istoric_pana_la": pachet["istoric_pana_la"], "zile_observate": pachet["zile_observate"],
            "randuri_antrenare": pachet["randuri_antrenare"], "caracteristici": pachet["caracteristici"],
            "metrici": pachet["metrici"],
            "atentie": "Până la pilot, istoricul e simulat. Cifrele arată că metoda funcționează, "
                       "nu precizia pe datele reale ale Iașului."}


@api.ruta("POST", "/api/model/invata", query=QueryZi, tag="Model AI", rezumat="Învață din ziua de azi (reantrenare)")
async def model_invata(request: Request, q: QueryZi):
    """Bucla de învățare: datele zilei (inclusiv mașinile intrate prin API) intră în istoric,
    iar modelul se reantrenează. În producție, asta rulează automat în fiecare noapte."""
    zi = q.zi or zi_demo()
    if not _lacat_antrenare.acquire(blocking=False):
        raise EroareAPI(409, "O antrenare e deja în curs. Reîncercați peste câteva secunde.")
    try:
        def lucru():
            with db.conexiune() as con:
                masini = cronologie(con, zi)
                rez = rezultat_zi(zi)
                istoric.salveaza_zi(con, context_cu_scenariu(zi), {g: np.array(v) for g, v in masini.items()},
                                    rez.sosiri, rez.redirectionate, sursa="zi_observata")
            return predictie.antreneaza()
        pachet = await run_in_threadpool(lucru)
    finally:
        _lacat_antrenare.release()
    return {"mesaj": f"Ziua {zi.isoformat()} a intrat în istoric. Modelul v{pachet['versiune']} a fost "
                     f"reantrenat pe {pachet['zile_istoric']} zile.",
            "versiune": pachet["versiune"], "metrici": pachet["metrici"]}


# ---------- scenarii pentru demo ----------

class EvenimentScenariu(BaseModel):
    nume: str = "Eveniment"
    start: str = Field("19:00", pattern=r"^\d{1,2}:\d{2}$", description="Ora de început, HH:MM")
    final: str = Field("21:00", pattern=r"^\d{1,2}:\d{2}$", description="Ora de final, HH:MM")
    porti: list[str] = Field(..., min_length=1, description="Porțile la care vin mașini în plus")
    masini_in_plus: int = Field(80, ge=0, le=1000, description="Mașini în plus la fiecare poartă")


class Scenariu(BaseModel):
    zi: Optional[date] = Field(None, description=_DESC_ZI)
    ploaie_mm: Optional[float] = Field(None, ge=0, le=100, description="Ploaie în ziua respectivă (mm)")
    vacanta: Optional[bool] = Field(None, description="Forțează zi de vacanță școlară (sau nu)")
    evenimente: list[EvenimentScenariu] = Field(default_factory=list)


def _descrie_scenariul() -> dict:
    sc = scenariu_curent()
    zi = date.fromisoformat(sc["zi"]) if sc else zi_demo()
    return {"activ": sc is not None,
            "scenariu": {**sc, "evenimente": [e.ca_dict() for e in sc["evenimente"]]} if sc else None,
            "context": context_cu_scenariu(zi).ca_dict()}


@api.ruta("GET", "/api/demo/scenariu", tag="Demo", rezumat="Scenariul activ și contextul zilei")
async def scenariu_get(request: Request):
    return _descrie_scenariul()


@api.ruta("POST", "/api/demo/scenariu", corp=Scenariu, tag="Demo", rezumat="Ce-ar fi dacă: ploaie, eveniment, vacanță")
async def scenariu_post(request: Request, corp: Scenariu):
    """Schimbă contextul zilei din demo și resimulează ziua. Exemplu pentru juriu: o seară cu meci,
    apoi uitați-vă cum prognoza și alertele din dispecerat se schimbă."""
    evenimente = []
    for e in corp.evenimente:
        for p in e.porti:
            _poarta_sau_eroare(p)
        start, final = din_ora(e.start), din_ora(e.final)
        if final <= start:
            raise EroareAPI(422, f"La „{e.nume}”, ora de final trebuie să fie după ora de început.")
        evenimente.append(Eveniment(e.nume, start, final, list(e.porti), e.masini_in_plus))
    seteaza_scenariu({"zi": (corp.zi or zi_demo()).isoformat(), "ploaie_mm": corp.ploaie_mm,
                      "vacanta": corp.vacanta, "evenimente": evenimente})
    return {"mesaj": "Scenariul e activ. Ziua a fost resimulată.", **_descrie_scenariul()}


@api.ruta("DELETE", "/api/demo/scenariu", tag="Demo", rezumat="Revino la ziua normală")
async def scenariu_delete(request: Request):
    seteaza_scenariu(None)
    return {"mesaj": "Scenariul a fost oprit.", **_descrie_scenariul()}


@api.ruta("POST", "/api/demo/reset", query=QueryZi, tag="Demo", rezumat="Șterge rezervările și trecerile prin barieră din demo")
async def demo_reset(request: Request, q: QueryZi):
    """Util înainte de prezentare: ziua demo revine la starea inițială (istoricul și modelul rămân)."""
    zi = (q.zi or zi_demo()).isoformat()
    with db.conexiune() as con:
        r = con.execute("DELETE FROM rezervari WHERE zi=?", (zi,)).rowcount
        e = con.execute("DELETE FROM evenimente_bariera WHERE zi=?", (zi,)).rowcount
    seteaza_scenariu(None)
    return {"mesaj": f"Gata: {r} rezervări și {e} treceri prin barieră șterse pentru {zi}. Scenariul a fost oprit."}


# ======================================================================
# Aplicația
# ======================================================================

def _pregateste_modelul() -> None:
    zile_noi = istoric.genereaza()            # prima pornire: simulează istoricul (câteva secunde)
    pachet = predictie.incarca()
    if pachet is None or zile_noi:
        log.info("Antrenez modelul de predicție (durează câteva secunde)…")
        predictie.antreneaza()
    else:
        PROGNOZATOR.seteaza(pachet)
        log.info("Model v%d încărcat (antrenat la %s).", pachet["versiune"], pachet["antrenat_la"])


@asynccontextmanager
async def lifespan(app: Starlette):
    db.initializeaza()
    await run_in_threadpool(_pregateste_modelul)
    log.info("Porțile Iașului: server pornit. Ziua demo: %s", zi_demo())
    yield


async def pagina_principala(request: Request):
    index = DIR_STATIC / "index.html"
    if index.exists():
        return FileResponse(index)
    return HTMLResponse("<h1>Porțile Iașului – API</h1><p>Frontendul lipsește din <code>static/index.html</code>. "
                        "Documentația: <a href='/docs'>/docs</a></p>")


async def aplicatia_mobil(request: Request):
    return FileResponse(DIR_STATIC / "app.html")


async def service_worker(request: Request):
    # servit din rădăcină, ca să poată controla și /app
    return FileResponse(DIR_STATIC / "sw.js", media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


async def manifest(request: Request):
    return FileResponse(DIR_STATIC / "manifest.webmanifest", media_type="application/manifest+json")


def creeaza_aplicatia() -> Starlette:
    rute = [Route("/", pagina_principala), Route("/app", aplicatia_mobil), Route("/sw.js", service_worker),
            Route("/manifest.webmanifest", manifest), *api.rute, *api.rute_documentatie()]
    if DIR_STATIC.exists():
        rute.append(Mount("/static", StaticFiles(directory=DIR_STATIC), name="static"))
    return Starlette(
        routes=rute,
        middleware=[Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])],
        lifespan=lifespan,
    )


app = creeaza_aplicatia()
