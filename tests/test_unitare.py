"""Teste pentru piesele mici: numere de înmatriculare și calendar."""
from datetime import date

from app.numere import corecteaza_ocr, normalizeaza
from app.surse.calendar_ro import e_vacanta, paste_ortodox, tip_zi


def test_normalizare_numere():
    assert normalizeaza("is23okc") == "IS 23 OKC"
    assert normalizeaza("IS-23-OKC") == "IS 23 OKC"
    assert normalizeaza("b 123 abc") == "B 123 ABC"
    assert normalizeaza("B 12 ABC") == "B 12 ABC"
    assert normalizeaza("XX 12 ABC") is None      # județ inexistent
    assert normalizeaza("IS 123 ABC") is None     # 3 cifre doar la București


def test_corectare_ocr():
    assert corecteaza_ocr("IS23 0KC") == "IS 23 OKC"
    assert corecteaza_ocr("1S 23 OKC") == "IS 23 OKC"
    assert corecteaza_ocr("IS 2E OKC") is None
    assert corecteaza_ocr("B12BABC") == "B 128 ABC"
    assert corecteaza_ocr("RO IS 23 OKC") == "IS 23 OKC"   # banda albastră „RO” citită și ea
    assert corecteaza_ocr("") is None


def test_calendar():
    assert paste_ortodox(2026) == date(2026, 4, 12)
    assert paste_ortodox(2027) == date(2027, 5, 2)
    assert tip_zi(date(2026, 10, 19)) == 0     # luni
    assert tip_zi(date(2026, 10, 17)) == 1     # sâmbătă
    assert tip_zi(date(2026, 12, 1)) == 2      # Ziua Națională
    assert tip_zi(date(2026, 4, 13)) == 2      # a doua zi de Paște
    assert e_vacanta(date(2026, 7, 15)) and not e_vacanta(date(2026, 10, 19))
