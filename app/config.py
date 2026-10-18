"""Setări și date de referință pentru Porțile Iașului.

Tot ce ține de oraș (porți, comune, destinații, ipoteze de calcul) stă aici,
ca să poată fi schimbat într-un singur loc. Valorile sunt aceleași ca în frontend.
"""
from __future__ import annotations

import os
from pathlib import Path

RADACINA = Path(__file__).resolve().parent.parent
DIR_DATE = Path(os.getenv("PORTI_DATA_DIR", str(RADACINA / "data")))   # fișiere generate (bază de date, model)
DIR_RESURSE = RADACINA / "resurse"                                       # fișiere editabile de mână (evenimente, vacanțe)
DIR_STATIC = RADACINA / "static"                                         # frontendul
CALE_DB = DIR_DATE / "porti.db"
CALE_MODEL = DIR_DATE / "model_ocupare.joblib"
CALE_METEO = DIR_DATE / "meteo_cache.json"

FUS_ORAR = "Europe/Bucharest"

# Ziua din demo: 05:00–23:00, la 5 minute (exact ca bara de timp din frontend).
# Ora se transmite peste tot ca „minute de la miezul nopții”: 510 = 08:30.
ZI_START, ZI_FINAL, PAS = 300, 1380, 5

PRAG_PLIN = 0.93        # peste 93% ocupare, o poartă e considerată plină
REZERVARE_MIN = 20      # cât timp e păstrat un loc rezervat
ZILE_ISTORIC = int(os.getenv("PORTI_ZILE_ISTORIC", "120"))   # câte zile de istoric generează simulatorul

# Tarifarea parcării P+R (demo; de validat cu Primăria și CTP)
TARIF_FARA_CARD_ORA = 5     # lei/oră, fără card CTP
CARD_ORE_GRATIS = 2         # ore gratuite cu card CTP valid
CARD_TARIF_ORA = 3          # lei/oră cu card CTP, după orele gratuite
ORE_MIN = 1                 # minimul de ore pe care le poate alege șoferul
ORE_MAX = 12                # maximul de ore
ORE_PAS = 1                 # pasul (din oră în oră)
ORE_IMPLICIT = 8            # durata presupusă dacă șoferul nu alege altceva (o zi de lucru)
# Cost reprezentativ P+R pentru comparația „prin poartă vs. cu mașina” din recomandare (un drum).
# Tariful real pe ore (de mai sus) se aplică la rezervare și plată.
TARIF_PR = 8

# Carduri CTP de test pentru verificarea din aplicație (demo). În realitate, verificarea se face
# în sistemul de ticketing CTP. Numerele se normalizează (fără spații/liniuțe, majuscule).
CARDURI_CTP_DEMO = {
    "1234123412341234": "Andrei Popescu",
    "CTP1001": "Maria Ionescu",
    "CTP2002": "Vlad Marinescu",
    "5500000011112222": "Elena Dobre",
}

# Ipoteze de calcul (aceleași ca în frontend; trebuie validate cu Primăria și CTP)
LEI_PE_KM = 0.65
PARCARE_CENTRU_LEI = 14
CO2_KG_PE_KM = 0.15
PERSOANE_PE_MASINA = 1.3
KM_EVITATI_PE_MASINA = 14

IASI_LAT, IASI_LON = 47.1585, 27.6014

# Cele șase porți. Câmpurile id…y sunt cele din frontend.
#   loc    = locuri de parcare propuse
#   spre   = minute cu CTP de la poartă până în centru
#   cerere = câte mașini de navetiști vin într-o zi lucrătoare obișnuită, raportat la locuri
#            (Păcurari are cerere peste capacitate: se umple la ora de vârf, ca în demo)
#   rise / fall = ora (zecimală) la care se umple / se golește parcarea; max = ocuparea maximă din frontend
PORTI = [
    {"id": "copou",    "nume": "Copou",    "dir": "Nord",     "din": "Rediu · Botoșani",
     "loc": 220, "spre": 12, "x": 300, "y": 58,  "cerere": 0.72, "max": 0.80,  "rise": 7.55, "fall": 17.1},
    {"id": "dancu",    "nume": "Dancu",    "dir": "Est",      "din": "Holboca · Tomești",
     "loc": 380, "spre": 18, "x": 520, "y": 168, "cerere": 0.84, "max": 0.92,  "rise": 7.30, "fall": 17.3},
    {"id": "bucium",   "nume": "Bucium",   "dir": "Sud-Est",  "din": "Bârnova · Vaslui",
     "loc": 260, "spre": 20, "x": 498, "y": 368, "cerere": 0.78, "max": 0.86,  "rise": 7.45, "fall": 17.5},
    {"id": "ciurea",   "nume": "Ciurea",   "dir": "Sud",      "din": "Ciurea · Lunca Cetățuii",
     "loc": 200, "spre": 22, "x": 300, "y": 420, "cerere": 0.64, "max": 0.74,  "rise": 7.50, "fall": 17.0},
    {"id": "cug",      "nume": "CUG",      "dir": "Sud-Vest", "din": "Miroslava",
     "loc": 320, "spre": 20, "x": 105, "y": 358, "cerere": 0.66, "max": 0.88,  "rise": 7.60, "fall": 17.2},
    {"id": "pacurari", "nume": "Păcurari", "dir": "Vest",     "din": "Lețcani · Podu Iloaiei · Târgu Frumos",
     "loc": 450, "spre": 16, "x": 88,  "y": 158, "cerere": 1.06, "max": 0.985, "rise": 7.35, "fall": 17.4},
]
PORTI_DUPA_ID = {p["id"]: p for p in PORTI}
CAPACITATE_TOTALA = sum(p["loc"] for p in PORTI)

# Unde trimitem mașinile când o poartă e plină
VECINI = {"copou": "pacurari", "dancu": "bucium", "bucium": "ciurea",
          "ciurea": "cug", "cug": "pacurari", "pacurari": "cug"}

# (nume, poarta firească, km până la poartă) — aceeași ordine ca în frontend, care trimite indexul
ORIGINI = [
    ("Lețcani / Podu Iloaiei", "pacurari", 9),
    ("Târgu Frumos", "pacurari", 28),
    ("Miroslava", "cug", 8),
    ("Ciurea / Lunca Cetățuii", "ciurea", 9),
    ("Bârnova / Vaslui", "bucium", 12),
    ("Holboca / Tomești", "dancu", 10),
    ("Rediu / Botoșani", "copou", 9),
]

# (nume, minute în plus cu CTP față de centru, km cu mașina prin oraș)
DESTINATII = [
    ("Piața Unirii", 0, 9),
    ("Palas", 3, 8),
    ("UAIC (Copou)", 6, 10),
    ("Spitalul Sf. Spiridon", 2, 9),
    ("Gara", 4, 8),
    ("Tătărași", 5, 10),
]

# Abonamente CTP de test (în realitate vin din sistemul de ticketing CTP)
ABONAMENTE_DEMO = ["IS 23 OKC", "IS 10 CTP", "IS 77 PRR", "VS 05 BRL", "BT 12 NOR", "B 123 ABC"]
