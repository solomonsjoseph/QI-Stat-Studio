"""RED: These tests fail until api/middleware/phi_scrubber.py is implemented."""
import pytest
from api.middleware.phi_scrubber import scrub_text


def test_redacts_person_name():
    result, count = scrub_text("Patient John Smith was admitted")
    assert "John Smith" not in result
    assert count >= 1


def test_redacts_mrn_pattern():
    result, count = scrub_text("MRN: 1234567")
    assert "1234567" not in result
    assert count >= 1


def test_redacts_ssn():
    result, count = scrub_text("SSN 123-45-6789")
    assert "123-45-6789" not in result
    assert count >= 1


def test_redacts_email():
    result, count = scrub_text("Contact patient@hospital.org")
    assert "patient@hospital.org" not in result
    assert count >= 1


def test_clean_text_unchanged():
    text = "Mean A1c decreased from 8.2 to 7.4 (p=0.03)"
    result, count = scrub_text(text)
    assert count == 0
    assert result == text
