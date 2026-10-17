"""Teste pentru recunoașterea numerelor din poză (se sar dacă nu e instalat niciun motor ANPR)."""
import pytest

from app import anpr
from imagini import font, poza_cu_placuta

necesita_motor = pytest.mark.skipif(not anpr.stare_motor()["disponibil"] or font(20) is None,
                                    reason="niciun motor ANPR instalat (vezi requirements-anpr.txt)")


@necesita_motor
@pytest.mark.parametrize("text,rotatie", [("IS 23 OKC", 2.0), ("B 123 ABC", -3.0), ("CJ 07 XYZ", 4.0)])
def test_citeste_numarul_din_poza(text, rotatie):
    assert anpr.citeste_numar(poza_cu_placuta(text, rotatie, seed=len(text)))["numar"] == text


@necesita_motor
def test_bariera_cu_poza(client):
    client.post("/api/reservations", json={"poarta": "dancu", "numar": "IS 77 PRR", "t": 700, "abonament": True})
    r = client.post("/api/gate-events/foto", data={"t": "710"},
                    files={"foto": ("masina.jpg", poza_cu_placuta("IS 77 PRR", -2.0, seed=7), "image/jpeg")})
    assert r.status_code == 200, r.text
    rez = r.json()
    assert rez["anpr"]["numar"] == "IS 77 PRR" and rez["permis"] and rez["poarta"] == "dancu" and rez["tarif"] == 0


def test_poza_invalida(client):
    if not anpr.stare_motor()["disponibil"]:
        pytest.skip("niciun motor ANPR instalat")
    r = client.post("/api/anpr", files={"foto": ("x.jpg", b"nu e o imagine", "image/jpeg")})
    assert r.status_code == 422
    assert client.post("/api/anpr", data={"altceva": "1"}).status_code == 422


def test_stare_motor(client):
    s = client.get("/api/anpr/stare").json()
    assert "disponibil" in s
