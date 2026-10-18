"""Teste pentru lucrări (capacitate redusă) — ex. șinele de tramvai la Copou, în ziua demo."""


def test_copou_are_capacitate_redusa(client):
    porti = {g["id"]: g for g in client.get("/api/gates", params={"t": 780}).json()}
    copou = porti["copou"]
    assert copou["lucrari"] is True and copou["blocat"] > 0
    assert copou["cap_efectiva"] < copou["loc"]          # locuri utile mai puține
    # o poartă fără lucrări rămâne la capacitate normală
    assert porti["dancu"]["lucrari"] is False and porti["dancu"]["cap_efectiva"] == porti["dancu"]["loc"]


def test_alerta_de_lucrari_in_dispecerat(client):
    alerte = client.get("/api/forecast", params={"t": 780}).json()["alerte"]
    lucrari = [a for a in alerte if a["tip"] == "lucrari"]
    assert lucrari and lucrari[0]["poarta"] == "copou"
    assert "semi-închis" in lucrari[0]["mesaj"] and "Păcurari" in lucrari[0]["mesaj"]


def test_recomandarea_ocoleste_poarta_cu_lucrari(client):
    # Rediu / Botoșani (origine 6) folosește normal Copou; cu lucrări e trimis la vecina
    rec = client.post("/api/recommend", json={"origine": 6, "destinatie": 0, "t": 780}).json()
    assert rec["redirected"] is not None and rec["redirected"]["id"] == "copou"
    assert rec["gate"]["id"] != "copou"
    assert rec["lucrari_nota"] and "semi-închis" in rec["lucrari_nota"]


def test_concert_palas_apare_seara(client):
    f = client.get("/api/forecast", params={"t": 1140}).json()   # 19:00
    assert any("Palas" in e["nume"] for e in f["context"]["evenimente"])
    assert any(a["tip"] == "eveniment" and "Palas" in a["mesaj"] for a in f["alerte"])
