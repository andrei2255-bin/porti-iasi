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


def test_limitele_de_ore():
    from app.config import ORE_MAX, ORE_MIN
    assert ORE_MIN == 1 and ORE_MAX == 12


def test_ore_in_afara_limitelor_sunt_respinse(client):
    assert client.post("/api/reservations",
                       json={"poarta": "cug", "numar": "IS 48 ORE", "t": 500, "ore": 24}).status_code == 422
    assert client.post("/api/reservations",
                       json={"poarta": "cug", "numar": "IS 49 ORE", "t": 500, "ore": 0}).status_code == 422
    # valoare aleasă liber în interval: 6 ore, fără card => 30 lei
    r = client.post("/api/reservations",
                    json={"poarta": "cug", "numar": "IS 50 ORE", "t": 500, "abonament": False, "ore": 6}).json()
    assert r["ore"] == 6 and r["cost"] == 30
    # verifica întoarce și limitele
    t = client.post("/api/ctp/verifica", json={"card": "CTP1001"}).json()["tarif"]
    assert t["ore_min"] == 1 and t["ore_max"] == 12


def test_plata_dubla_si_inexistenta(client):
    rez = client.post("/api/reservations",
                     json={"poarta": "bucium", "numar": "IS 46 PAY", "t": 500, "abonament": False, "ore": 4}).json()
    assert client.post("/api/plata", json={"rezervare": rez["id"], "numar_card": "4111111111111111"}).json()["platit"]
    # a doua plată nu creează altă tranzacție
    din_nou = client.post("/api/plata", json={"rezervare": rez["id"]}).json()
    assert "deja plătită" in din_nou["mesaj"]
    assert client.post("/api/plata", json={"rezervare": "RNIMIC"}).status_code == 404


def test_bariera_fara_card_nu_zice_card_valid(client):
    # IS 23 OKC e în lista de abonați demo, dar dacă rezerv FĂRĂ card, bariera nu trebuie să zică „card valid”
    rez = client.post("/api/reservations",
                     json={"poarta": "cug", "numar": "IS 23 OKC", "t": 500, "abonament": False, "ore": 3}).json()
    assert rez["cost"] == 15 and rez["are_card"] is False
    client.post("/api/plata", json={"rezervare": rez["id"], "numar_card": "4111111111111111"})
    e = client.post("/api/gate-events", json={"numar": "IS 23 OKC", "t": 510}).json()
    assert e["abonament"] is False and e["platit"] is True
    assert "Fără card" in e["mesaj"] and "Plătit" in e["mesaj"]


def test_bariera_nu_se_ridica_daca_nu_e_platit(client):
    rez = client.post("/api/reservations",
                     json={"poarta": "dancu", "numar": "IS 60 NEP", "t": 500, "abonament": False, "ore": 4}).json()
    assert rez["necesita_plata"] is True
    e = client.post("/api/gate-events", json={"numar": "IS 60 NEP", "t": 510}).json()
    assert e["permis"] is False and "neplătită" in e["mesaj"]


def test_reset_sterge_si_plata(client):
    client.post("/api/reservations", json={"poarta": "copou", "numar": "IS 47 RST", "t": 500, "ore": 4})
    assert "rezervări" in client.post("/api/demo/reset").json()["mesaj"]
