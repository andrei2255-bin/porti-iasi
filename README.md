# Porțile Iașului – backend

Serverul pentru Park & Ride inteligent în Iași (echipa OK COMPUTER). Face patru lucruri:

1. **API pentru frontend**: starea porților, recomandarea pentru șofer, rezervări, bariera.
2. **Simulator de trafic**: o zi la cele 6 porți, mașină cu mașină, în funcție de vreme, sărbători, vacanțe și evenimente.
3. **Model AI de predicție**: prezice ocuparea fiecărei porți pe următoarele 4 ore și învață din fiecare zi nouă.
4. **Recunoașterea numerelor (ANPR)**: citește numărul din poza de la barieră.

Frontendul (`static/index.html`) e servit de același server și folosește toate acestea.

---

## Pornire rapidă

Aveți nevoie de **Python 3.10 sau mai nou**.

```bash
cd porti-iasului-backend
python -m venv .venv
# Windows:        .venv\Scripts\activate
# macOS / Linux:  source .venv/bin/activate
pip install -r requirements.txt
python -m app
```

Apoi deschideți:

| Adresă | Ce e acolo |
|---|---|
| http://localhost:8000 | Site-ul cu demo-ul (aplicația șoferului + dispeceratul) |
| http://localhost:8000/docs | Documentația API, unde puteți testa fiecare endpoint din browser |

**Prima pornire durează ~15 secunde**: serverul simulează 120 de zile de istoric și antrenează modelul.
Pornirile următoare sunt instantanee (totul se salvează în folderul `data/`).

În bara de timp din demo apare **„conectat la server · model AI”** (verde) când pagina vorbește cu backendul.
Dacă serverul nu răspunde, apare „simulare locală”, iar demo-ul merge mai departe cu simularea din pagină.

**Demo pe telefon** (în aceeași rețea Wi-Fi cu laptopul):

```bash
# macOS / Linux
HOST=0.0.0.0 python -m app
# Windows PowerShell
$env:HOST="0.0.0.0"; python -m app
```

Apoi pe telefon: `http://<IP-ul laptopului>:8000`.

---

## Structura proiectului

```
app/
  main.py         toate endpoint-urile (aici adăugați endpoint-uri noi)
  config.py       porțile, comunele, destinațiile, ipotezele de calcul  ← date de oraș, de verificat
  logica.py       recomandarea pentru șofer (timpi, costuri, redirecționare)
  ocupare.py      câte mașini sunt în fiecare parcare la o anumită oră
  simulator.py    simulatorul de trafic
  context.py      contextul unei zile (vreme, tip de zi, vacanță, evenimente)
  istoric.py      istoricul de ocupare pe care învață modelul
  predictie.py    modelul AI (antrenare, evaluare, predicție)
  anpr.py         recunoașterea numerelor din poze
  numere.py       validarea și corectarea numerelor de înmatriculare românești
  db.py           baza de date SQLite (data/porti.db)
  web.py          stratul subțire peste Starlette: validare, erori, documentația /docs
  surse/          surse de date deschise: vremea (Open-Meteo), calendarul, evenimentele
resurse/
  evenimente.json evenimente publice (meciuri, concerte) – EDITAȚI cu evenimente reale
  vacante.json    vacanțele școlare (aproximative) – VERIFICAȚI datele
static/index.html frontendul, legat de backend
tests/            teste automate (pytest)
data/             generat automat: baza de date, modelul, vremea salvată
```

Serverul e construit pe **Starlette** (aceeași bază ca FastAPI) cu **pydantic** pentru validare și rulează cu **uvicorn**.

---

## Endpoint-uri

Ora se trimite peste tot ca **minute de la miezul nopții**: `t=510` înseamnă 08:30. Dacă lipsește, se folosește ora reală din Iași.
Ziua implicită e „ziua demo-ului” (azi, sau următoarea zi lucrătoare dacă azi e weekend sau sărbătoare).

| Metodă | Adresă | Ce face |
|---|---|---|
| GET | `/api/health` | Verifică dacă serverul merge |
| GET | `/api/gates?t=510` | Cele 6 porți: ocupare și locuri libere |
| POST | `/api/recommend` | Poarta recomandată, timpi, costuri, redirecționare (pe ocuparea **prezisă** la sosire) |
| POST | `/api/reservations` | Rezervă un loc pentru 20 de minute |
| GET | `/api/reservations/{id}` | Starea unei rezervări |
| POST | `/api/gate-events` | Camera a citit un număr: intrare sau ieșire, verificare abonament CTP |
| POST | `/api/gate-events/foto` | Același lucru, dar din poză (ANPR) |
| POST | `/api/anpr` | Doar citește numărul dintr-o poză |
| GET | `/api/forecast?t=510` | Prognoza AI pe 4 ore pentru toate porțile + alertele pentru dispecerat |
| GET | `/api/gates/{id}/forecast` | Prognoza AI pentru o poartă |
| GET | `/api/timeline` | Ocuparea pe toată ziua, la 5 minute (pentru hartă și grafic) |
| GET | `/api/stats?t=510` | Mașini oprite în afara centrului, călătorii CTP noi, CO₂ evitat |
| GET | `/api/model` | Versiunea modelului și cât de precis e |
| POST | `/api/model/invata` | Ziua de azi intră în istoric și modelul se reantrenează |
| GET / POST / DELETE | `/api/demo/scenariu` | „Ce-ar fi dacă”: ploaie, eveniment, vacanță |
| POST | `/api/demo/reset` | Șterge rezervările și trecerile prin barieră din demo |

Exemple cu `curl`:

```bash
curl "http://localhost:8000/api/gates?t=510"

curl -X POST http://localhost:8000/api/recommend -H "Content-Type: application/json" \
     -d '{"origine": 0, "destinatie": 0, "t": 510, "abonament": true}'

curl -X POST http://localhost:8000/api/gate-events/foto -F "foto=@masina.jpg" -F "poarta=cug" -F "t=530"
```

Erorile au mereu forma `{"detail": "mesaj în română"}` (plus `erori` cu câmpurile greșite, la validare).

---

## Cum funcționează partea de AI

1. **Contextul zilei, din surse deschise (OSINT):** vremea în Iași de la [Open-Meteo](https://open-meteo.com) (gratuit, fără cheie),
   sărbătorile legale (calculate, inclusiv Paștele ortodox), vacanțele școlare și evenimentele publice din `resurse/`.
2. **Simulatorul** generează zile realiste la cele 6 porți: navetiști dimineața, vizitatori la prânz, mașini în plus la evenimente,
   redirecționare la poarta vecină când una e plină. Contextul schimbă cererea (weekend, vacanță, ploaie).
3. **Istoricul**: până la pilot nu avem date de la camere reale, așa că istoricul (120 de zile) e generat de simulator.
4. **Modelul** (gradient boosting pe arbori de decizie, scikit-learn) primește ocuparea de acum și de acum 30 de minute,
   profilul obișnuit al porții, contextul zilei și ora, și prezice ocuparea la 15–240 de minute în viitor.
5. **Evaluarea** se face pe ultimele 21 de zile, pe care modelul nu le-a văzut. Pe istoricul simulat, eroarea medie la o oră
   în avans e de ~1,4 puncte procentuale, față de ~8 pentru „rămâne cum e acum” și ~5 pentru „media din istoric”
   (cifrele exacte: `GET /api/model`).
6. **Bucla de învățare**: `POST /api/model/invata` pune ziua de azi (inclusiv mașinile intrate prin API) în istoric și
   reantrenează modelul. În producție, asta ar rula automat în fiecare noapte.

> **Important pentru prezentare:** cifrele de precizie sunt pe date simulate. Ele arată că metoda funcționează,
> nu cât de precis va fi modelul pe traficul real din Iași. Asta se măsoară în pilot, cu date de la camere.

Unde se folosește predicția:
- **Recomandarea pentru șofer**: dacă poarta firească va fi plină **la ora la care ajunge șoferul**, AI-ul îl trimite la poarta vecină.
- **Dispeceratul**: ora la care se umple fiecare poartă și sugestii („o cursă CTP în plus”, „ambele porți din vest sunt pline,
  zona are nevoie de capacitate”).

---

## Scenariu de demo pentru juriu

1. **Înainte de prezentare:** `POST /api/demo/reset` (din `/docs`), ca să porniți de la zero.
2. **Ora 08:30, din Lețcani spre Piața Unirii:** Păcurari va fi plină, AI-ul trimite șoferul la CUG și îi spune câte locuri vor fi
   la sosire. Rezervați, treceți de barieră, urcați în tramvai.
3. **Dispeceratul:** alertele AI (de exemplu: Păcurari plină, CUG se umple în jurul orei 09:20), panoul LED care redirecționează.
4. **„Ce-ar fi dacă”:** în `/docs`, `POST /api/demo/scenariu` cu:
   ```json
   {"ploaie_mm": 8, "evenimente": [{"nume": "Meci Poli Iași", "start": "19:00", "final": "21:00",
     "porti": ["copou", "pacurari"], "masini_in_plus": 120}]}
   ```
   Mutați ora la 17:30 în dispecerat: apare alerta pentru meci, iar prognoza pentru Copou crește înainte de ora 19:00.
   Reveniți cu `DELETE /api/demo/scenariu`.
5. **Învățarea:** `POST /api/model/invata` → modelul trece la versiunea următoare, cu o zi în plus în istoric.
6. **Bariera cu cameră** (opțional): `POST /api/gate-events/foto` cu o poză a unei mașini.

---

## Recunoașterea numerelor (opțional)

```bash
pip install -r requirements-anpr.txt
```

- **fast-alpr** (recomandat): rețele neuronale, merge pe poze reale. Descarcă modelele la prima folosire (aveți nevoie de internet o dată).
  *Testați-l pe laptop cu câteva poze reale înainte de demo* (`POST /api/anpr` din `/docs`).
- **Tesseract** (rezervă, folosit automat dacă fast-alpr lipsește): merge pe poze clare, făcute din față. Trebuie instalat și programul
  Tesseract (instrucțiuni în `requirements-anpr.txt`).

Indiferent de motor, se acceptă doar numere românești valide, iar confuziile tipice de citire se corectează (0/O, 1/I, 8/B, banda „RO”).
`GET /api/anpr/stare` arată ce motor e activ.

---

## Legătura cu frontendul

`static/index.html` e site-ul vostru, cu aceste modificări:
- obiectul `API` trimite cererile la server; simularea din pagină a rămas ca rezervă (`LOCAL_API`);
- harta, tabelul, graficul și panourile folosesc ocuparea de la server (`/api/timeline`);
- ora la care se umple o poartă, alertele și indicatorii vin de la modelul AI (`/api/forecast`, `/api/stats`);
- recomandarea arată predicția pentru ora sosirii; erorile de la rezervare (număr greșit, poartă plină) apar în aplicație;
- în bara de timp e un indicator „conectat la server · model AI” / „simulare locală”.

Dacă deschideți pagina de pe alt server (de exemplu Live Server din VS Code), adăugați `?api=http://localhost:8000` la adresă.

---

## Configurare

| Variabilă | Implicit | Ce face |
|---|---|---|
| `PORT` | 8000 | Portul serverului |
| `HOST` | 127.0.0.1 | `0.0.0.0` ca să fie accesibil din rețea (telefon) |
| `RELOAD` | 0 | `1` = repornire automată la modificarea codului |
| `PORTI_ZI_DEMO` | azi / următoarea zi lucrătoare | Fixează ziua din demo, ex. `2026-10-19` |
| `PORTI_ZILE_ISTORIC` | 120 | Câte zile de istoric simulează |
| `PORTI_DATA_DIR` | `data/` | Unde se salvează baza de date și modelul |
| `PORTI_METEO_OFFLINE` | 0 | `1` = nu mai cere vremea de la Open-Meteo |
| `PORTI_ANPR` | auto | `fast-alpr` sau `tesseract` ca să forțați un motor |

Alte comenzi utile:

```bash
python -m app.istoric --refa     # regenerează istoricul simulat (apoi reporniți serverul: modelul se reantrenează)
```

Ca să porniți complet de la zero, ștergeți folderul `data/`.

---

## Teste

```bash
pip install -r requirements-dev.txt
pytest
```

Testele verifică formatul răspunsurilor (identic cu ce așteaptă frontendul), fluxul rezervare → barieră → ieșire,
simulatorul, faptul că modelul bate metodele simple, scenariile, bucla de învățare și ANPR (dacă e instalat un motor).

---

## Ce e simulat și ce urmează

| Acum (prototip) | În pilot (cu Primăria și CTP) |
|---|---|
| Istoric generat de simulator | Date reale de la camerele de la barieră |
| Abonamente CTP de test (ex. `IS 23 OKC`) | Legătura cu sistemul de ticketing CTP |
| Locații și capacități propuse în `config.py` | Terenuri și capacități reale |
| Evenimente și vacanțe de exemplu în `resurse/` | Calendarul real al orașului |
| Reantrenare la cerere | Reantrenare automată în fiecare noapte |

## Probleme frecvente

- **„Address already in use”**: portul 8000 e ocupat. Porniți cu `PORT=8001` (Windows: `$env:PORT="8001"`).
- **Vremea nu se descarcă**: serverul merge și fără; marchează vremea ca estimată.
- **După actualizarea scikit-learn**, modelul salvat se reantrenează automat la pornire.
- **Pagina arată „simulare locală”** deși serverul merge: deschideți pagina de la `http://localhost:8000`, nu ca fișier.
# porti-iasi
