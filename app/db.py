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
    creat_la     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_rezervari ON rezervari(zi, numar);
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


def initializeaza() -> None:
    with conexiune() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(SCHEMA)
        for i, numar in enumerate(config.ABONAMENTE_DEMO, start=1):
            con.execute(
                "INSERT OR IGNORE INTO abonamente_ctp(numar, card, valabil_pana, sursa) VALUES (?,?,?,?)",
                (numar, f"CTP-DEMO-{i:04d}", "2027-12-31", "demo"),
            )
