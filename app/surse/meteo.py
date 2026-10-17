"""Vremea în Iași, de la Open-Meteo (gratuit, fără cont sau cheie API).

Aduce precipitațiile zilnice pentru ultimele 92 de zile și următoarele 7, o dată pe zi,
și le salvează în data/meteo_cache.json. Fără internet, folosește ce e salvat; dacă nu e
nimic salvat, simulatorul estimează vremea (și marchează asta în context).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import urllib.request

from ..config import CALE_METEO, FUS_ORAR, IASI_LAT, IASI_LON

log = logging.getLogger("porti.meteo")

URL = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
       "&daily=precipitation_sum&timezone={tz}&past_days=92&forecast_days=7")

_memorie: dict[str, float] | None = None
_lacat = threading.Lock()


def interpreteaza(raspuns: dict) -> dict[str, float]:
    """Transformă răspunsul Open-Meteo în {'2026-10-17': 3.2, ...} (mm de ploaie pe zi)."""
    zilnic = raspuns["daily"]
    return {zi: float(mm) for zi, mm in zip(zilnic["time"], zilnic["precipitation_sum"]) if mm is not None}


def _citeste_cache() -> dict:
    try:
        return json.loads(CALE_METEO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def ploaie_zilnica() -> dict[str, float]:
    """Precipitațiile zilnice cunoscute. Se descarcă cel mult o dată pe zi și pe proces."""
    global _memorie
    with _lacat:
        if _memorie is not None:
            return _memorie
        from ..timp import acum
        cache = _citeste_cache()
        azi = acum().date().isoformat()
        zile = dict(cache.get("zile", {}))
        if cache.get("descarcat_la") != azi and os.getenv("PORTI_METEO_OFFLINE") != "1":
            try:
                url = URL.format(lat=IASI_LAT, lon=IASI_LON, tz=FUS_ORAR.replace("/", "%2F"))
                with urllib.request.urlopen(url, timeout=4) as r:
                    zile.update(interpreteaza(json.load(r)))
                CALE_METEO.parent.mkdir(parents=True, exist_ok=True)
                CALE_METEO.write_text(json.dumps({"descarcat_la": azi, "sursa": "open-meteo.com", "zile": zile}),
                                      encoding="utf-8")
                log.info("Vremea pentru Iași a fost actualizată de la Open-Meteo (%d zile).", len(zile))
            except Exception as e:  # fără internet, timeout, format neașteptat: mergem mai departe
                log.warning("Nu am putut lua vremea de la Open-Meteo (%s). Folosesc datele salvate sau estimări.", e)
        _memorie = zile
        return _memorie
