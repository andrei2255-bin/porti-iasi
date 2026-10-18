"""Teste pentru tarifare, verificarea cardului CTP și plata (demo)."""
from app.plata import cost_sedere, normalizeaza_card


def test_tarifare():
    # fără card: 5 lei/oră
    assert cost_sedere(8, False) == 40
    assert cost_sedere(2, False) == 10
    # cu card: 2 ore gratis, apoi 3 lei/oră
    assert cost_sedere(2, True) == 0
    assert cost_sedere(1, True) == 0
    assert cost_sedere(8, True) == 18        # (8-2) * 3
    assert cost_sedere(4, True) == 6


def test_normalizare_card():
    assert normalizeaza_card("1234 1234-1234 1234") == "1234123412341234"
    assert normalizeaza_card("ctp 1001") == "CTP1001"


def test_verifica_card(client):
    bun = client.post("/api/ctp/verifica", json={"card": "ctp1001"}).json()
    assert bun["valid"] is True and bun["nume"] == "Maria Ionescu"
    assert client.post("/api/ctp/verifica", json={"card": "1234 1234 1234 1234"}).json()["valid"] is True
    rau = client.post("/api/ctp/verifica", json={"card": "0000"}).json()
    assert rau["valid"] is False and "negăsit" in rau["mesaj"]


def test_rezervare_cu_card_are_doua_ore_gratis(client):
    r = client.post("/api/reservations",
                    json={"poarta": "cug", "numar": "IS 44 CTP", "t": 500, "card_ctp": "CTP2002", "ore": 8}).json()
    assert r["cost"] == 18 and r["are_card"] is True and r["card"] == "CTP2002"
    assert "2 h gratis" in r["explicatie_tarif"]


def test_card_invalid_cade_pe_tarif_fara_card(client):
    r = client.post("/api/reservations",
                    json={"poarta": "ciurea", "numar": "IS 45 XXX", "t": 500, "card_ctp": "9999", "ore": 4}).json()
    assert r["are_card"] is False and r["cost"] == 20     # 4 × 5 lei


def test_plata_dubla_si_inexistenta(client):
    rez = client.post("/api/reservations",
                     json={"poarta": "bucium", "numar": "IS 46 PAY", "t": 500, "abonament": False, "ore": 4}).json()
    assert client.post("/api/plata", json={"rezervare": rez["id"], "numar_card": "4111111111111111"}).json()["platit"]
    # a doua plată nu creează altă tranzacție
    din_nou = client.post("/api/plata", json={"rezervare": rez["id"]}).json()
    assert "deja plătită" in din_nou["mesaj"]
    assert client.post("/api/plata", json={"rezervare": "RNIMIC"}).status_code == 404


def test_reset_sterge_si_plata(client):
    client.post("/api/reservations", json={"poarta": "copou", "numar": "IS 47 RST", "t": 500, "ore": 4})
    assert "rezervări" in client.post("/api/demo/reset").json()["mesaj"]
