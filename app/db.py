"""Baza de date SQLite (un singur fișier: data/porti.db).

Tabele:
  abonamente_ctp      numere de mașini legate de un abonament CTP valid
  rezervari           locuri rezervate din aplicație (valabile 20 de minute)
  evenimente_bariera  intrări și ieșiri citite de camera de la barieră
  zile                contextul fiecărei zile din istoric (vreme, vacanță, evenimente)
  istoric_ocupare     ocuparea fiecărei porți la fiecare 15 minute (datele de antrenare ale modelului)
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS abonamente_ctp (
    numar        TEXT PRIMARY KEY,
    card         TEXT NOT NULL,
    valabil_pana TEXT NOT NULL,
    sursa        TEXT NOT NULL DEFAULT 'ctp'
);
CREATE TABLE IF NOT EXISTS rezervari (
    id           TEXT PRIMARY KEY,
    poarta       TEXT NOT NULL,
    numar        TEXT NOT NULL,
    zi           TEXT NOT NULL,
    t            INTEGER NOT NULL,
    expira_t     INTEGER NOT NULL,
    bilet_platit INTEGER NOT NULL DEFAULT 0,
    stare        TEXT NOT NULL DEFAULT 'activa',      -- activa | folosita | anulata
    ore          REAL NOT NULL DEFAULT 0,             -- durata estimată de ședere
    cost         REAL NOT NULL DEFAULT 0,             -- lei de plătit pentru ședere
    card         TEXT,                                -- cardul CTP folosit la rezervare (demo)
    platit       INTEGER NOT NULL DEFAULT 0,          -- 0 = neplătit, 1 = plătit
    tranzactie   TEXT,                                -- codul plății (demo)
    creat_la     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_rezervari ON rezervari(zi, numar);
CREATE TABLE IF NOT EXISTS carduri_ctp (
    card   TEXT PRIMARY KEY,                          -- numărul cardului, normalizat
    nume   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evenimente_bariera (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    poarta    TEXT NOT NULL,
    numar     TEXT NOT NULL,
    zi        TEXT NOT NULL,
    t         INTEGER NOT NULL,
    tip       TEXT NOT NULL,                          -- intrare | iesire
    abonament INTEGER NOT NULL DEFAULT 0,
    tarif     INTEGER NOT NULL DEFAULT 0,
    sector    TEXT,
    loc       INTEGER,
    creat_la  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_bariera ON evenimente_bariera(zi, poarta);
CREATE TABLE IF NOT EXISTS zile (
    zi         TEXT PRIMARY KEY,
    tip_zi     INTEGER NOT NULL,
    vacanta    INTEGER NOT NULL,
    ploaie_mm  REAL NOT NULL,
    evenimente TEXT NOT NULL DEFAULT '[]',
    sursa      TEXT NOT NULL                          -- simulare | zi_observata
);
CREATE TABLE IF NOT EXISTS istoric_ocupare (
    zi             TEXT NOT NULL,
    poarta         TEXT NOT NULL,
    t              INTEGER NOT NULL,
    masini         INTEGER NOT NULL,
    ocupare        REAL NOT NULL,
    sosiri         INTEGER NOT NULL,
    redirectionate INTEGER NOT NULL,
    PRIMARY KEY (zi, poarta, t)
);
"""


def acum_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def conexiune():
    config.DIR_DATE.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.CALE_DB, timeout=15)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


# Coloane adăugate după prima versiune: le punem și în bazele de date deja existente,
# ca aplicația să meargă și pe un deploy mai vechi, fără să ștergem datele.
_COLOANE_NOI = [
    ("rezervari", "ore", "REAL NOT NULL DEFAULT 0"),
    ("rezervari", "cost", "REAL NOT NULL DEFAULT 0"),
    ("rezervari", "card", "TEXT"),
    ("rezervari", "platit", "INTEGER NOT NULL DEFAULT 0"),
    ("rezervari", "tranzactie", "TEXT"),
]


def _migreaza(con: sqlite3.Connection) -> None:
    for tabel, coloana, tip in _COLOANE_NOI:
        existente = {r["name"] for r in con.execute(f"PRAGMA table_info({tabel})")}
        if coloana not in existente:
            con.execute(f"ALTER TABLE {tabel} ADD COLUMN {coloana} {tip}")


def initializeaza() -> None:
    with conexiune() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(SCHEMA)
        _migreaza(con)
        for i, numar in enumerate(config.ABONAMENTE_DEMO, start=1):
            con.execute(
                "INSERT OR IGNORE INTO abonamente_ctp(numar, card, valabil_pana, sursa) VALUES (?,?,?,?)",
                (numar, f"CTP-DEMO-{i:04d}", "2027-12-31", "demo"),
            )
        for card, nume in config.CARDURI_CTP_DEMO.items():
            con.execute("INSERT OR IGNORE INTO carduri_ctp(card, nume) VALUES (?,?)", (card, nume))
