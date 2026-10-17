"""Modelul AI: prezice ocuparea fiecărei porți pentru următoarele 4 ore.

Ce primește modelul (pentru o poartă, la ora t0, ca să prezică ora t1):
  - ocuparea acum și acum 30 de minute (cât de repede se umple);
  - profilul obișnuit al porții (media din istoric pentru același tip de zi și aceeași oră);
  - contextul zilei din surse deschise: tipul zilei, vacanța, ploaia, evenimentele;
  - ora acum, ora țintă și cât de departe în viitor e (orizontul).
Ce întoarce: ocuparea (0–1) la ora t1.

Algoritm: gradient boosting pe arbori de decizie (HistGradientBoostingRegressor din scikit-learn):
rapid, merge bine pe date tabelare și se antrenează în câteva secunde pe un laptop.

Evaluare cinstită: modelul e testat pe ultimele 21 de zile, pe care NU le-a văzut la antrenare,
și comparat cu două metode simple: „rămâne cum e acum” și „media din istoric”.
Atenție: până la pilot, istoricul e simulat, deci cifrele arată că metoda funcționează,
nu cât de precisă va fi pe datele reale ale Iașului.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

from . import db
from .config import CALE_MODEL, PORTI, PRAG_PLIN, ZI_FINAL, ZI_START
from .context import ContextZi

log = logging.getLogger("porti.model")

T15 = np.arange(ZI_START, ZI_FINAL + 1, 15)        # orele din istoric (la 15 minute): 73 de valori
N15 = len(T15)
ORIZONTURI = np.arange(15, 241, 15)                 # prezicem la 15, 30, …, 240 de minute
INDEX_POARTA = {g["id"]: i for i, g in enumerate(PORTI)}
CAPACITATI = np.array([g["loc"] for g in PORTI], dtype=float)
CARACTERISTICI = ["poarta", "capacitate", "tip_zi", "zi_saptamana", "vacanta", "ploaie_mm",
                  "eveniment_masini_raportat_la_locuri", "eveniment_minute_fata_de_start",
                  "ora_acum", "ora_tinta", "orizont_min", "ocupare_acum", "ocupare_acum_30min",
                  "profil_acum", "profil_tinta", "abatere_de_la_profil"]


# ---------- caracteristici (aceeași funcție la antrenare și la predicție) ----------

def _matrice(gi: int, tip: int, zi_sapt: int, vacanta: int, ploaie: float, evenimente: list[tuple[int, int, int]],
             t0: np.ndarray, t1: np.ndarray, occ0: np.ndarray, occ30: np.ndarray, profil: np.ndarray) -> np.ndarray:
    n = len(t0)
    i0 = np.clip(np.rint((t0 - ZI_START) / 15).astype(int), 0, N15 - 1)
    i1 = np.clip(np.rint((t1 - ZI_START) / 15).astype(int), 0, N15 - 1)
    p0, p1 = profil[gi, tip, i0], profil[gi, tip, i1]
    # evenimentul cel mai apropiat de ora țintă: câte mașini aduce (raportat la locuri) și cât e până la start
    ev_masini, ev_minute = np.zeros(n), np.full(n, 999.0)
    for start, final, masini in evenimente:
        relevant = (t1 >= start - 240) & (t1 <= final + 90)
        ev_masini = np.where(relevant, np.maximum(ev_masini, masini / CAPACITATI[gi]), ev_masini)
        ev_minute = np.where(relevant & (np.abs(t1 - start) < np.abs(ev_minute)), t1 - start, ev_minute)
    plin = lambda v: np.full(n, v, dtype=float)  # noqa: E731
    return np.column_stack([plin(gi), plin(CAPACITATI[gi]), plin(tip), plin(zi_sapt), plin(vacanta), plin(ploaie),
                            ev_masini, ev_minute, t0, t1, t1 - t0, occ0, occ30, p0, p1, occ0 - p0])


def _intervale(evenimente: list, gid: str) -> list[tuple[int, int, int]]:
    """Evenimentele care privesc poarta: (start, final, mașini în plus)."""
    rez = []
    for e in evenimente:
        e = e if isinstance(e, dict) else e.ca_dict()
        if gid in e["porti"]:
            rez.append((e["start"], e["final"], e["masini"]))
    return rez


# ---------- datele de antrenare ----------

def _incarca_istoric():
    with db.conexiune() as con:
        zile = {r["zi"]: dict(r) for r in con.execute("SELECT * FROM zile ORDER BY zi")}
        ocupare: dict[tuple[str, str], np.ndarray] = {}
        for zi, poarta, t, occ in con.execute("SELECT zi, poarta, t, ocupare FROM istoric_ocupare"):
            ocupare.setdefault((zi, poarta), np.full(N15, np.nan))[(t - ZI_START) // 15] = occ
    for z in zile.values():
        z["evenimente"] = json.loads(z["evenimente"] or "[]")
        z["zi_saptamana"] = datetime.fromisoformat(z["zi"]).weekday()
    return zile, ocupare


def _profil(lista_zile: list[str], zile: dict, ocupare: dict) -> np.ndarray:
    """Ocuparea medie pe poartă × tip de zi × oră (forma: 6 × 3 × 73)."""
    suma = np.zeros((len(PORTI), 3, N15))
    numar = np.zeros((len(PORTI), 3, 1))
    for zi in lista_zile:
        tip = zile[zi]["tip_zi"]
        for g in PORTI:
            v = ocupare.get((zi, g["id"]))
            if v is not None and not np.isnan(v).any():
                suma[INDEX_POARTA[g["id"]], tip] += v
                numar[INDEX_POARTA[g["id"]], tip] += 1
    medie_totala = suma.sum(axis=1, keepdims=True) / np.maximum(1, numar.sum(axis=1, keepdims=True))
    return np.where(numar > 0, suma / np.maximum(1, numar), medie_totala)


def _set_date(lista_zile, zile, ocupare, profil, rng, toate_orizonturile=False):
    X, y = [], []
    for zi in lista_zile:
        m = zile[zi]
        for g in PORTI:
            v = ocupare.get((zi, g["id"]))
            if v is None or np.isnan(v).any():
                continue
            i0 = np.arange(2, N15)
            if toate_orizonturile:
                i0, pasi = np.meshgrid(i0, np.arange(1, 17), indexing="ij")
                i0, pasi = i0.ravel(), pasi.ravel()
            else:
                i0 = np.repeat(i0, 4)
                pasi = rng.integers(1, 17, size=len(i0))
            i1 = i0 + pasi
            ok = i1 < N15
            i0, i1 = i0[ok], i1[ok]
            X.append(_matrice(INDEX_POARTA[g["id"]], m["tip_zi"], m["zi_saptamana"], m["vacanta"], m["ploaie_mm"],
                              _intervale(m["evenimente"], g["id"]), T15[i0].astype(float), T15[i1].astype(float),
                              v[i0], v[i0 - 2], profil))
            y.append(v[i1])
    return np.vstack(X), np.concatenate(y)


def _model_nou() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(max_iter=300, learning_rate=0.06, max_leaf_nodes=31, min_samples_leaf=30,
                                         l2_regularization=1.0, categorical_features=[0, 2], random_state=0,
                                         early_stopping=False)


def antreneaza(zile_test: int = 21) -> dict:
    """Evaluează pe ultimele zile, apoi reantrenează pe tot istoricul și salvează modelul."""
    zile, ocupare = _incarca_istoric()
    lista = sorted(zile)
    if len(lista) < 20:
        raise ValueError(f"Prea puțin istoric pentru antrenare ({len(lista)} zile, minimum 20).")
    zile_test = min(zile_test, max(5, len(lista) // 5))
    antrenare, test = lista[:-zile_test], lista[-zile_test:]
    rng = np.random.default_rng(0)

    profil = _profil(antrenare, zile, ocupare)
    X_tr, y_tr = _set_date(antrenare, zile, ocupare, profil, rng)
    X_te, y_te = _set_date(test, zile, ocupare, profil, rng, toate_orizonturile=True)
    model = _model_nou().fit(X_tr, y_tr)
    pred = np.clip(model.predict(X_te), 0, 1)
    col = {nume: i for i, nume in enumerate(CARACTERISTICI)}
    metode = {"model_ai": pred, "ramane_ca_acum": X_te[:, col["ocupare_acum"]],
              "media_din_istoric": X_te[:, col["profil_tinta"]]}

    def eroare(mask):
        return {nume: round(float(np.mean(np.abs(p[mask] - y_te[mask]))) * 100, 2) for nume, p in metode.items()}

    orizont = X_te[:, col["orizont_min"]]
    metrici = {
        "unitate": "eroare medie absolută, în puncte procentuale de ocupare (mai mic = mai bine)",
        "zile_test": zile_test,
        "toate_orizonturile": eroare(np.ones(len(y_te), dtype=bool)),
        "la_30_min": eroare(orizont == 30),
        "la_60_min": eroare(orizont == 60),
        "la_120_min": eroare(orizont == 120),
    }

    profil_tot = _profil(lista, zile, ocupare)
    X_all, y_all = _set_date(lista, zile, ocupare, profil_tot, np.random.default_rng(0))
    model_final = _model_nou().fit(X_all, y_all)

    anterior = incarca()
    pachet = {
        "model": model_final,
        "profil": profil_tot,
        "metrici": metrici,
        "versiune": (anterior["versiune"] + 1) if anterior else 1,
        "antrenat_la": datetime.now().isoformat(timespec="seconds"),
        "zile_istoric": len(lista),
        "istoric_de_la": lista[0],
        "istoric_pana_la": lista[-1],
        "zile_observate": sum(1 for z in zile.values() if z["sursa"] == "zi_observata"),
        "randuri_antrenare": int(len(y_all)),
        "caracteristici": CARACTERISTICI,
    }
    CALE_MODEL.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pachet, CALE_MODEL)
    PROGNOZATOR.seteaza(pachet)
    log.info("Model v%d antrenat pe %d zile. Eroare la 60 min: model %.1f pp, metodă naivă %.1f pp.",
             pachet["versiune"], len(lista), metrici["la_60_min"]["model_ai"], metrici["la_60_min"]["ramane_ca_acum"])
    return pachet


def incarca() -> dict | None:
    try:
        return joblib.load(CALE_MODEL)
    except Exception:  # lipsă sau salvat cu altă versiune de scikit-learn
        return None


# ---------- predicția ----------

class Prognozator:
    def __init__(self):
        self._pachet: dict | None = None
        self._lacat = threading.Lock()

    def seteaza(self, pachet: dict | None) -> None:
        with self._lacat:
            self._pachet = pachet

    @property
    def pachet(self) -> dict | None:
        return self._pachet

    def prezice(self, ctx: ContextZi, t0: int, occ_acum: dict[str, float], occ_30: dict[str, float],
                porti: list[str] | None = None) -> dict[str, dict]:
        """Pentru fiecare poartă: ocuparea prezisă la fiecare 5 minute în următoarele 4 ore."""
        pachet = self._pachet
        if pachet is None:
            raise RuntimeError("Modelul nu e antrenat.")
        porti = porti or [g["id"] for g in PORTI]
        t1 = t0 + ORIZONTURI
        t1 = t1[t1 <= ZI_FINAL].astype(float)
        rezultat: dict[str, dict] = {}
        if len(t1) == 0:  # ultima oră din zi: nu mai e nimic de prezis
            return {gid: {"ore": [], "ocupare": [], "se_umple_la": t0 if occ_acum[gid] >= PRAG_PLIN else None}
                    for gid in porti}
        blocuri = []
        for gid in porti:
            gi = INDEX_POARTA[gid]
            n = len(t1)
            blocuri.append(_matrice(gi, ctx.tip_zi, ctx.zi.weekday(), int(ctx.vacanta), ctx.ploaie_mm,
                                    _intervale(ctx.evenimente, gid), np.full(n, float(t0)), t1,
                                    np.full(n, occ_acum[gid]), np.full(n, occ_30[gid]), pachet["profil"]))
        pred = np.clip(pachet["model"].predict(np.vstack(blocuri)), 0, 1).reshape(len(porti), len(t1))
        grila = np.arange(t0 + 5, int(t1[-1]) + 1, 5, dtype=float)
        for j, gid in enumerate(porti):
            valori = np.interp(grila, np.concatenate([[t0], t1]), np.concatenate([[occ_acum[gid]], pred[j]]))
            se_umple = t0 if occ_acum[gid] >= PRAG_PLIN else next(
                (int(t) for t, v in zip(grila, valori) if v >= PRAG_PLIN), None)
            rezultat[gid] = {"ore": grila.astype(int).tolist(), "ocupare": np.round(valori, 4).tolist(),
                             "se_umple_la": se_umple}
        return rezultat


PROGNOZATOR = Prognozator()
