"""Teste pentru simulator și istoric."""
from datetime import date

from app.config import PORTI, PAS, ZI_START
from app.context import ContextZi
from app.simulator import simuleaza_zi
from app.surse.evenimente import Eveniment
from app.surse.meteo import interpreteaza


def _k(t):
    return (t - ZI_START) // PAS


LUNI = ContextZi(date(2026, 10, 19), 0, False, 0.0, [])


def test_zi_lucratoare_are_varf_dimineata():
    rez = simuleaza_zi(LUNI)
    for g in PORTI:
        m = rez.masini[g["id"]]
        assert m.max() <= g["loc"]                       # niciodată peste capacitate
        assert m[_k(360)] < m[_k(540)]                   # 06:00 mai liber decât 09:00
        assert m[_k(1260)] < 0.2 * g["loc"]              # seara se golește
    assert rez.masini["pacurari"][_k(510)] >= 0.93 * 450  # Păcurari plină la 08:30, ca în demo
    assert rez.redirectionate["pacurari"].sum() > 0       # deci unele mașini sunt trimise la CUG


def test_determinist_si_variabil():
    a, b = simuleaza_zi(LUNI), simuleaza_zi(LUNI)
    assert (a.masini["dancu"] == b.masini["dancu"]).all()          # aceeași zi, același rezultat
    c = simuleaza_zi(LUNI, seed=123)
    assert (a.masini["dancu"] != c.masini["dancu"]).any()          # altă zi, alt rezultat


def test_contextul_schimba_traficul():
    luni = simuleaza_zi(LUNI)
    duminica = simuleaza_zi(ContextZi(date(2026, 10, 18), 2, False, 0.0, []))
    vacanta = simuleaza_zi(ContextZi(date(2026, 10, 19), 0, True, 0.0, []))
    assert duminica.masini["dancu"].max() < 0.5 * luni.masini["dancu"].max()
    assert vacanta.masini["dancu"][_k(510)] < luni.masini["dancu"][_k(510)]
    meci = simuleaza_zi(ContextZi(date(2026, 10, 19), 0, False, 0.0,
                                  [Eveniment("Meci", 1140, 1260, ["copou"], 90)]))
    assert meci.masini["copou"][_k(1170)] > luni.masini["copou"][_k(1170)] + 50


def test_meteo_interpreteaza_raspunsul_open_meteo():
    raspuns = {"daily": {"time": ["2026-10-16", "2026-10-17"], "precipitation_sum": [0.0, 4.2]}}
    assert interpreteaza(raspuns) == {"2026-10-16": 0.0, "2026-10-17": 4.2}


def test_istoricul_e_generat_la_pornire(client):
    from app import db
    with db.conexiune() as con:
        zile = con.execute("SELECT COUNT(*) FROM zile WHERE sursa='simulare'").fetchone()[0]
        randuri = con.execute("SELECT COUNT(*) FROM istoric_ocupare WHERE zi IN "
                              "(SELECT zi FROM zile WHERE sursa='simulare')").fetchone()[0]
    assert zile == 60
    assert randuri == 60 * 6 * 73
