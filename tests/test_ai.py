"""Teste pentru partea de AI: prognoze, dispecerat, scenarii și bucla de învățare."""
from app.config import PORTI


def test_modelul_bate_metodele_simple(client):
    info = client.get("/api/model").json()
    m = info["metrici"]["la_60_min"]
    assert m["model_ai"] < m["ramane_ca_acum"]
    assert m["model_ai"] < m["media_din_istoric"]
    assert info["zile_istoric"] == 60 and "simulat" in info["atentie"]


def test_prognoza_pentru_toate_portile(client):
    r = client.get("/api/forecast", params={"t": 420})
    assert r.status_code == 200
    f = r.json()
    assert set(f["porti"]) == {g["id"] for g in PORTI}
    p = f["porti"]["pacurari"]
    assert len(p["prognoza"]) == 48                       # 4 ore, la 5 minute
    assert p["prognoza"][0]["ora"] == "07:05"
    assert all(0 <= x["ocupare"] <= 1 for x in p["prognoza"])
    # la 07:00, modelul vede că Păcurari se va umple înainte de 08:30
    assert p["se_umple_la"] is not None and 420 < p["se_umple_la"] <= 510
    assert f["context"]["tip_zi"] == 0


def test_alerte_la_ora_de_varf(client):
    f = client.get("/api/forecast", params={"t": 510}).json()
    plina = [a for a in f["alerte"] if a["poarta"] == "pacurari"]
    assert plina and plina[0]["tip"] in ("plina", "capacitate") and "CUG" in plina[0]["mesaj"]


def test_prognoza_unei_porti(client):
    r = client.get("/api/gates/cug/forecast", params={"t": 600})
    assert r.status_code == 200 and r.json()["poarta"] == "cug"
    assert client.get("/api/gates/nicaieri/forecast").status_code == 404


def test_cronologia_zilei(client):
    tl = client.get("/api/timeline").json()
    assert tl["start"] == 300 and tl["pas"] == 5
    for g in PORTI:
        assert len(tl["porti"][g["id"]]) == 217
        assert max(tl["masini"][g["id"]]) <= g["loc"]


def test_statistici_cresc_in_timpul_zilei(client):
    dimineata = client.get("/api/stats", params={"t": 480}).json()
    pranz = client.get("/api/stats", params={"t": 720}).json()
    assert 0 < dimineata["oprite_azi"] < pranz["oprite_azi"]
    assert pranz["calatorii_ctp_noi"] == round(pranz["oprite_azi"] * 1.3 * 2)
    assert pranz["redirectionate_azi"] > 0


def test_scenariu_eveniment_si_resetare(client):
    inainte = client.get("/api/forecast", params={"t": 1080}).json()["porti"]["copou"]["prognoza"]
    r = client.post("/api/demo/scenariu", json={"ploaie_mm": 6, "evenimente": [
        {"nume": "Meci Poli", "start": "19:00", "final": "21:00", "porti": ["copou"], "masini_in_plus": 120}]})
    assert r.status_code == 200 and r.json()["context"]["ploaie_mm"] == 6
    f = client.get("/api/forecast", params={"t": 1080}).json()
    assert any(a["tip"] == "eveniment" and a["poarta"] == "copou" for a in f["alerte"])
    dupa = f["porti"]["copou"]["prognoza"]
    la_1900 = lambda p: next(x["ocupare"] for x in p if x["ora"] == "19:00")  # noqa: E731
    assert la_1900(dupa) > la_1900(inainte) + 0.2           # modelul vede mașinile de la meci
    assert client.post("/api/demo/scenariu", json={"evenimente": [
        {"start": "21:00", "final": "19:00", "porti": ["copou"]}]}).status_code == 422
    assert client.delete("/api/demo/scenariu").json()["activ"] is False


def test_bucla_de_invatare(client):
    v1 = client.get("/api/model").json()["versiune"]
    r = client.post("/api/model/invata")
    assert r.status_code == 200
    info = client.get("/api/model").json()
    assert info["versiune"] == v1 + 1 and info["zile_observate"] == 1 and info["zile_istoric"] == 61


def test_reset_demo(client):
    client.post("/api/reservations", json={"poarta": "bucium", "numar": "IS 01 RST", "t": 900})
    r = client.post("/api/demo/reset").json()
    assert "rezervări" in r["mesaj"]
    with __import__("app.db", fromlist=["conexiune"]).conexiune() as con:
        assert con.execute("SELECT COUNT(*) FROM rezervari").fetchone()[0] == 0
