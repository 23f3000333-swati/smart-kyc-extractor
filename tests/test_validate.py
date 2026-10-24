"""Unit tests for src/validate.py (run: pytest -q)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.validate import (mrz_check_digit, mrz_line2_checks, normalize,  # noqa: E402
                          normalize_date, strip_relation_prefix, validate,
                          validate_document, verhoeff_ok, words_to_number)


def test_verhoeff():
    assert verhoeff_ok("2363")          # textbook example
    assert not verhoeff_ok("2364")


def test_aadhaar_sample_reports_but_passes_format():
    ok, msgs = validate("aadhaar", "123456789012")
    assert ok is True
    assert any("0/1" in m for m in msgs)


def test_pan_and_tin():
    assert validate("pan", "BPQPD3051R")[0]
    assert not validate("pan", "BPQPD305IR")[0]
    value, corr = normalize("pan", "BPQPD3O5IR")   # O in digit slot, I in digit slot
    assert value == "BPQPD3051R" and len(corr) == 2


def test_ifsc_format_and_bank_prefix():
    assert validate("ifsc", "SBIN0227112", {"bank_name": "State Bank of India"})[0]
    assert not validate("ifsc", "SBIN0227112", {"bank_name": "HDFC Bank"})[0]
    assert not validate("ifsc", "SBIN1227112")[0]
    value, corr = normalize("ifsc", "SBINO227112")
    assert value == "SBIN0227112" and corr == ["pos 4: 'O'->'0'"]


def test_account_number():
    assert validate("account", "31004258912")[0]
    assert not validate("account", "1234")[0]
    assert normalize("account", "3100 4258 9I2")[0] == "31004258912"


def test_mrz_check_digits():
    assert mrz_check_digit("X1234567<") == 7
    assert mrz_check_digit("791218") == 2
    line = "X1234567<7IND7912185M3001010" + "<" * 14 + "08"
    assert len(line) == 44
    problems = mrz_line2_checks(line)
    assert any("date of birth" in p for p in problems)   # sample has wrong digits
    assert not any("document number" in p for p in problems)


def test_dates():
    assert normalize_date("26/04/26")[0] == "26/04/2026"
    assert normalize_date("18-12-79")[0] == "18/12/1979"
    assert normalize_date("26/O4/2026")[0] == "26/04/2026"
    assert normalize_date("26042026")[0] == "26/04/2026"
    assert normalize_date("2610412026")[0] == "26/04/2026"   # '/' read as '1'
    assert validate("date", "31/02/2026")[0] is False
    assert validate_document({"date_of_issue": "15/06/2021", "valid_till": "14/06/2041"}) == {}
    assert validate_document({"date_of_issue": "15/06/2041", "valid_till": "14/06/2021"})


def test_amount_words():
    assert words_to_number("Fifty thousand Only") == 50000
    assert words_to_number("two lakh fifty thousand") == 250000
    assert normalize("amount", "₹ 50,000")[0] == "50000"
    assert validate("amount", "50000", {"amount_words": "Fifty thousand only"})[0]
    assert not validate("amount", "5000", {"amount_words": "Fifty thousand only"})[0]


def test_father_prefix_and_bank():
    assert strip_relation_prefix("S/O KUMAR") == "KUMAR"
    assert strip_relation_prefix("Arjun Das Kumar") == "Arjun Das Kumar"
    assert normalize("bank", "State Bank of Indla")[0] == "State Bank of India"


def test_text_kinds():
    assert validate("place", "West Bihar")[0]
    assert validate("relation", "Nephew")[0]
    assert validate("nationality", normalize("nationality", "Indian")[0])[0]
    assert validate("choice", "Financial Planning", {"options": ["Financial Planning"]})[0]
