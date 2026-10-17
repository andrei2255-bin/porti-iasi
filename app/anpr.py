"""Recunoașterea automată a numerelor de înmatriculare (ANPR) din poza de la barieră.

Două motoare, alese automat (sau cu variabila de mediu PORTI_ANPR=fast-alpr | tesseract):

  fast-alpr  rețele neuronale (detecție YOLO + OCR), mult mai robust pe poze reale.
             Instalare:  pip install -r requirements-anpr.txt
             (la prima folosire descarcă modelele, câțiva zeci de MB)
  tesseract  OpenCV găsește plăcuța, Tesseract citește textul. Merge pe poze clare, din față.
             Necesită programul Tesseract instalat în sistem (vezi README).

Orice ar citi motorul, rezultatul trece prin corecteaza_ocr(): păstrăm doar numere românești
valide și reparăm confuziile tipice (0/O, 1/I, 8/B...).
"""
from __future__ import annotations

import logging
import os
import threading

import numpy as np

from .numere import corecteaza_ocr

log = logging.getLogger("porti.anpr")

LISTA_ALBA = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


class ANPRIndisponibil(RuntimeError):
    pass


# ---------- motorul 1: fast-alpr (rețele neuronale) ----------

class MotorFastALPR:
    nume = "fast-alpr"

    def __init__(self):
        from fast_alpr import ALPR  # pip install fast-alpr[onnx]
        optiuni = {k: v for k, v in (("detector_model", os.getenv("PORTI_ANPR_DETECTOR")),
                                     ("ocr_model", os.getenv("PORTI_ANPR_OCR"))) if v}
        incercari = [optiuni] if optiuni else [
            {},  # modelele implicite ale bibliotecii
            {"detector_model": "yolo-v9-t-384-license-plate-end2end", "ocr_model": "cct-xs-v1-global-model"},
            {"detector_model": "yolo-v9-t-384-license-plate-end2end", "ocr_model": "global-plates-mobile-vit-v2-model"},
        ]
        ultima_eroare = None
        for o in incercari:
            try:
                self.alpr = ALPR(**o)
                return
            except Exception as e:  # versiuni diferite ale bibliotecii au alte nume de modele
                ultima_eroare = e
        raise ANPRIndisponibil(f"fast-alpr nu a putut încărca modelele: {ultima_eroare}")

    def citeste(self, imagine_bgr: np.ndarray) -> list[tuple[str, float | None]]:
        rezultate = []
        for r in self.alpr.predict(imagine_bgr) or []:
            ocr = getattr(r, "ocr", None)
            text = getattr(ocr, "text", None) if ocr is not None else None
            if not text:
                continue
            incredere = getattr(ocr, "confidence", None)
            if isinstance(incredere, (list, tuple, np.ndarray)):
                incredere = float(np.mean(incredere)) if len(incredere) else None
            rezultate.append((str(text), float(incredere) if incredere is not None else None))
        return rezultate


# ---------- motorul 2: OpenCV + Tesseract ----------

class MotorTesseract:
    nume = "tesseract"

    def __init__(self):
        import cv2  # noqa: F401
        import pytesseract
        try:
            pytesseract.get_tesseract_version()
        except Exception as e:
            raise ANPRIndisponibil(f"Programul Tesseract nu e instalat sau nu e în PATH ({e}).")
        self.tess = pytesseract

    @staticmethod
    def _candidati(gri: np.ndarray) -> list[tuple[int, int, int, int]]:
        """Dreptunghiuri care ar putea fi plăcuțe (lățime de 2–7 ori înălțimea)."""
        import cv2
        h, w = gri.shape
        cutii = []

        def adauga(contururi, maxim):
            for c in sorted(contururi, key=cv2.contourArea, reverse=True)[:maxim]:
                x, y, cw, ch = cv2.boundingRect(c)
                if ch > 0 and 2.0 <= cw / ch <= 7.0 and cw * ch >= 0.002 * w * h and cw < 0.95 * w:
                    cutii.append((x, y, cw, ch))

        # a) contururi pe muchii (rama plăcuței)
        muchii = cv2.Canny(cv2.bilateralFilter(gri, 11, 17, 17), 30, 200)
        adauga(cv2.findContours(muchii, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[0], 40)
        # b) zone cu text închis pe fundal deschis (morfologie „blackhat”)
        nucleu = cv2.getStructuringElement(cv2.MORPH_RECT, (17, 5))
        bh = cv2.morphologyEx(gri, cv2.MORPH_BLACKHAT, nucleu)
        grad = np.abs(cv2.Sobel(bh, cv2.CV_32F, 1, 0, ksize=-1))
        grad = (255 * (grad - grad.min()) / max(1e-6, grad.max() - grad.min())).astype("uint8")
        grad = cv2.morphologyEx(cv2.GaussianBlur(grad, (5, 5), 0), cv2.MORPH_CLOSE, nucleu)
        prag = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
        prag = cv2.dilate(cv2.erode(prag, None, iterations=2), None, iterations=2)
        adauga(cv2.findContours(prag, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0], 20)

        unice = []   # scoatem dreptunghiurile aproape identice
        for c in cutii:
            if all(_suprapunere(c, u) < 0.7 for u in unice):
                unice.append(c)
        return unice[:15]

    def _ocr(self, bucata: np.ndarray) -> list[str]:
        """Citește o bucată de imagine (gri) cu mai multe binarizări, până iese un număr valid."""
        import cv2
        scara = 110 / max(1, bucata.shape[0])
        img = cv2.resize(bucata, None, fx=scara, fy=scara, interpolation=cv2.INTER_CUBIC)
        # îndreptăm plăcuța dacă e înclinată (după linia pe care stau caracterele)
        proba = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
        unghi = _unghi_text(proba if proba.mean() >= 127 else 255 - proba)
        if abs(unghi) > 0.7:
            centru = (img.shape[1] / 2, img.shape[0] / 2)
            img = cv2.warpAffine(img, cv2.getRotationMatrix2D(centru, unghi, 1.0), (img.shape[1], img.shape[0]),
                                 flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        binarizari = (
            lambda: cv2.threshold(img, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1],
            lambda: cv2.threshold(cv2.GaussianBlur(img, (3, 3), 0), 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1],
            lambda: cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10),
        )
        texte = []
        for binarizeaza in binarizari:
            binar = binarizeaza()
            if binar.mean() < 127:      # vrem text negru pe fundal alb
                binar = 255 - binar
            binar = cv2.copyMakeBorder(_doar_caractere(binar), 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
            text = self.tess.image_to_string(binar, config=f"--psm 7 -c tessedit_char_whitelist={LISTA_ALBA}")
            text = text.strip()
            if text:
                texte.append(text)
                if corecteaza_ocr(text):
                    break
        return texte

    def citeste(self, imagine_bgr: np.ndarray) -> list[tuple[str, float | None]]:
        import cv2
        gri = cv2.cvtColor(imagine_bgr, cv2.COLOR_BGR2GRAY)
        # banda albastră UE („RO”) încurcă citirea: o albim înainte de OCR
        b, g, r = (imagine_bgr[..., i].astype(np.int16) for i in range(3))
        fara_banda = imagine_bgr.copy()
        fara_banda[(b > r + 40) & (b > g + 10)] = 255
        gri_ocr = cv2.cvtColor(fara_banda, cv2.COLOR_BGR2GRAY)
        rezultate: list[tuple[str, float | None]] = []
        for x, y, w, h in self._candidati(gri):
            m = int(0.08 * h)
            texte = self._ocr(gri_ocr[max(0, y - m): y + h + m, max(0, x - m): x + w + m])
            rezultate += [(t, None) for t in texte]
            if any(corecteaza_ocr(t) for t in texte):
                break      # am găsit un număr valid
        if not any(corecteaza_ocr(t) for t, _ in rezultate):   # ultima încercare: toată poza
            text = self.tess.image_to_string(gri_ocr, config=f"--psm 11 -c tessedit_char_whitelist={LISTA_ALBA}")
            rezultate += [(rand, None) for rand in text.splitlines() if rand.strip()]
        valide = [(t, c) for t, c in rezultate if corecteaza_ocr(t)]
        return valide + [(t, c) for t, c in rezultate if (t, c) not in valide]


def _unghi_text(binar: np.ndarray) -> float:
    """Înclinarea rândului de caractere, în grade (0 dacă nu se poate estima)."""
    import cv2
    h, w = binar.shape
    n, _, stat, centre = cv2.connectedComponentsWithStats(255 - binar, connectivity=8)
    puncte = [centre[i] for i in range(1, n)
              if 0.3 * h <= stat[i][3] <= 0.95 * h and stat[i][2] <= 0.25 * w and stat[i][4] >= 30]
    if len(puncte) < 4:
        return 0.0
    xs, ys = np.array(puncte).T
    return float(np.degrees(np.arctan(np.polyfit(xs, ys, 1)[0])))


def _doar_caractere(binar: np.ndarray) -> np.ndarray:
    """Păstrează doar formele de mărimea unui caracter (scoate rama plăcuței, șuruburile, zgomotul)."""
    import cv2
    h, w = binar.shape
    negru = 255 - binar
    # liniile lungi orizontale/verticale sunt rama plăcuței: le scoatem, ca să nu se lipească de litere
    linii = cv2.morphologyEx(negru, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, w // 5), 1)))
    linii |= cv2.morphologyEx(negru, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, int(h * 0.6)))))
    negru = cv2.subtract(negru, linii)
    n, etichete, stat, _ = cv2.connectedComponentsWithStats(negru, connectivity=8)
    candidati = []
    for i in range(1, n):
        x, y, cw, ch, aria = stat[i]
        atinge_marginea = x == 0 or y == 0 or x + cw >= w or y + ch >= h
        if 0.2 * h <= ch <= 0.95 * h and cw <= 0.25 * w and not atinge_marginea and aria >= 30:
            candidati.append((i, ch))
    if not candidati:
        return binar
    mediana = float(np.median([ch for _, ch in candidati]))    # caracterele au aceeași înălțime
    curat = np.full_like(binar, 255)
    for i, ch in candidati:
        if abs(ch - mediana) <= 0.3 * mediana:
            curat[etichete == i] = 0
    return curat


def _suprapunere(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    return inter / float(aw * ah + bw * bh - inter)


# ---------- alegerea motorului și funcția folosită de API ----------

_motor = None
_eroare_motor: str | None = None
_lacat = threading.Lock()


def motor():
    """Încarcă (o singură dată) primul motor disponibil."""
    global _motor, _eroare_motor
    with _lacat:
        if _motor is not None:
            return _motor
        try:
            import cv2  # noqa: F401  (ambele motoare au nevoie de OpenCV pentru a citi poza)
        except ImportError:
            raise ANPRIndisponibil("Lipsește OpenCV. Instalați: pip install -r requirements-anpr.txt")
        dorit = os.getenv("PORTI_ANPR", "auto").lower()
        ordine = {"fast-alpr": [MotorFastALPR], "tesseract": [MotorTesseract]}.get(dorit,
                                                                                    [MotorFastALPR, MotorTesseract])
        erori = []
        for clasa in ordine:
            try:
                _motor = clasa()
                log.info("ANPR: folosesc motorul %s.", clasa.nume)
                return _motor
            except ImportError as e:
                erori.append(f"{clasa.nume}: biblioteca lipsește ({e.name})")
            except Exception as e:
                erori.append(f"{clasa.nume}: {e}")
        _eroare_motor = "; ".join(erori)
        raise ANPRIndisponibil("Niciun motor ANPR disponibil. " + _eroare_motor +
                               ". Instalați: pip install -r requirements-anpr.txt")


def stare_motor() -> dict:
    try:
        return {"disponibil": True, "motor": motor().nume}
    except ANPRIndisponibil as e:
        return {"disponibil": False, "motor": None, "problema": str(e)}


def citeste_numar(octeti: bytes) -> dict:
    """Primește poza (jpg/png) și întoarce numărul citit, dacă e un număr românesc valid."""
    import cv2
    imagine = cv2.imdecode(np.frombuffer(octeti, dtype=np.uint8), cv2.IMREAD_COLOR)
    if imagine is None:
        raise ValueError("Fișierul nu e o imagine validă (folosiți JPG sau PNG).")
    if max(imagine.shape[:2]) > 1600:           # pozele mari de pe telefon: micșorăm, merge mai repede
        f = 1600 / max(imagine.shape[:2])
        imagine = cv2.resize(imagine, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    m = motor()
    citiri = m.citeste(imagine)
    for text, incredere in citiri:
        numar = corecteaza_ocr(text)
        if numar:
            return {"recunoscut": True, "numar": numar, "text_citit": text,
                    "incredere": round(incredere, 3) if incredere is not None else None, "motor": m.nume}
    return {"recunoscut": False, "numar": None, "text_citit": citiri[0][0] if citiri else "",
            "incredere": None, "motor": m.nume}
