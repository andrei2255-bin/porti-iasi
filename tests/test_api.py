"""Teste pentru endpoint-urile folosite de frontend. Rulare:  pytest -q"""

CHEI_POARTA = {"id", "nume", "dir", "din", "loc", "spre", "x", "y", "ocupare", "libere"}
CHEI_RECOMANDARE = {"oname", "dname", "gate", "redirected", "pr", "car", "legs", "search", "carCity",
                    "prCost", "carCost", "co2", "headway"}


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["stare"] == "ok"
    assert r.json()["zi_demo"] == "2026-10-19"


def test_gates_are_formatul_din_frontend(client):
    r = client.get("/api/gates", params={"t": 510})
    assert r.status_code == 200
    porti = r.json()
    assert [p["id"] for p in porti] == ["copou", "dancu", "bucium", "ciurea", "cug", "pacurari"]
    for p in porti:
        assert CHEI_POARTA <= p.keys()
        assert 0 <= p["ocupare"] <= 1
        assert 0 <= p["libere"] <= p["loc"]
        assert p["libere"] == round(p["loc"] * (1 - p["ocupare"]))


def test_recomandare_are_formatul_din_frontend(client):
    r = client.post("/api/recommend", json={"origine": 2, "destinatie": 0, "t": 780, "abonament": True})
    assert r.status_code == 200
    rec = r.json()
    assert CHEI_RECOMANDARE <= rec.keys()
    assert CHEI_POARTA <= rec["gate"].keys()
    legs = rec["legs"]
    assert legs["toGate"] + legs["walk"] + legs["wait"] + legs["ride"] + legs["last"] == rec["pr"]
    assert rec["prCost"] < rec["carCost"]


def test_redirectionare_la_ora_de_varf(client):
    # 08:30, din Lețcani: Păcurari e plină, deci sistemul trimite mașina la CUG
    rec = client.post("/api/recommend", json={"origine": 0, "destinatie": 0, "t": 510}).json()
    assert rec["redirected"]["id"] == "pacurari"
    assert rec["gate"]["id"] == "cug"
    assert rec["prognoza"]["ocupare_la_sosire"] < 0.93


def test_fara_redirectionare_la_pranz(client):
    rec = client.post("/api/recommend", json={"origine": 2, "destinatie": 1, "t": 700}).json()
    assert rec["redirected"] is None
    assert rec["gate"]["id"] == "cug"


def test_flux_complet_rezervare_bariera_iesire(client):
    # card CTP valid + 2 ore => gratuit, fără plată
    rez = client.post("/api/reservations",
                      json={"poarta": "cug", "numar": "is 23 okc", "t": 515, "card_ctp": "CTP1001", "ore": 2}).json()
    assert rez["plate"] == "IS 23 OKC" and rez["minute"] == 20 and rez["id"].startswith("R")
    assert rez["cost"] == 0 and rez["platit"] is True and rez["necesita_plata"] is False
    # camera citește greșit 0 în loc de O: backendul corectează
    e = client.post("/api/gate-events", json={"numar": "IS23 0KC", "t": 530}).json()
    assert e["recunoscut"] and e["permis"] and e["abonament"] is True and e["tarif"] == 0
    assert e["poarta"] == "cug" and e["sector"] in "ABCDEFGHIJ" and 1 <= e["loc"] <= 100
    assert client.get(f"/api/reservations/{rez['id']}").json()["stare"] == "folosita"
    # a doua citire a aceleiași mașini nu o dublează
    assert client.post("/api/gate-events", json={"numar": "IS 23 OKC", "t": 531}).json()["loc"] == e["loc"]
    x = client.post("/api/gate-events", json={"numar": "IS 23 OKC", "tip": "iesire", "t": 1050}).json()
    assert x["durata_min"] == 520 and x["permis"]


def test_fara_card_plateste_pe_ora(client):
    # fără card, 8 ore => 8 × 5 = 40 lei, trebuie plătit
    rez = client.post("/api/reservations",
                      json={"poarta": "dancu", "numar": "CJ 99 XYZ", "t": 600, "abonament": False, "ore": 8}).json()
    assert rez["cost"] == 40 and rez["tarif"] == 40 and rez["necesita_plata"] is True and rez["platit"] is False
    plata = client.post("/api/plata", json={"rezervare": rez["id"], "numar_card": "4111 1111 1111 1111"}).json()
    assert plata["platit"] is True and plata["tranzactie"].startswith("TX-") and "40" in plata["mesaj"]
    e = client.post("/api/gate-events", json={"numar": "CJ 99 XYZ", "t": 610}).json()
    assert e["abonament"] is False and e["platit"] is True and "Plătit" in e["mesaj"]


def test_rezervarea_ocupa_un_loc(client):
    inainte = {p["id"]: p["libere"] for p in client.get("/api/gates", params={"t": 800}).json()}
    client.post("/api/reservations", json={"poarta": "ciurea", "numar": "IS 55 ABC", "t": 800})
    dupa = {p["id"]: p["libere"] for p in client.get("/api/gates", params={"t": 800}).json()}
    assert dupa["ciurea"] == inainte["ciurea"] - 1


def test_erori_clare(client):
    r = client.post("/api/reservations", json={"poarta": "cug", "numar": "ABC", "t": 600})
    assert r.status_code == 422 and "IS 23 OKC" in r.json()["detail"]
    r = client.post("/api/reservations", json={"poarta": "nicaieri", "numar": "IS 11 AAA"})
    assert r.status_code == 404
    r = client.post("/api/recommend", json={"origine": 99, "destinatie": 0})
    assert r.status_code == 422 and r.json()["erori"][0]["camp"] == "origine"
    r = client.post("/api/recommend", content=b"nu e json", headers={"content-type": "application/json"})
    assert r.status_code == 400
    r = client.post("/api/gate-events", json={"numar": "???", "poarta": "cug"})
    assert r.status_code == 200 and r.json()["recunoscut"] is False


def test_documentatie(client):
    spec = client.get("/openapi.json").json()
    assert "/api/recommend" in spec["paths"] and "post" in spec["paths"]["/api/recommend"]
    assert "CerereRecomandare" in spec["components"]["schemas"]
    assert client.get("/docs").status_code == 200
