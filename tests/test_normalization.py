from decimal import Decimal

import pytest

from app.services.normalization import normalize_spo2
from app.services.normalization import normalize_spo2, normalize_temperature


def test_spo2_percentage():
    assert normalize_spo2(Decimal("97"), "%") == Decimal("97")


def test_spo2_fraction():
    assert normalize_spo2(Decimal("0.97"), "1") == Decimal("97")


def test_spo2_invalid_fraction():
    with pytest.raises(ValueError):
        normalize_spo2(Decimal("97"), "1")


def test_temperature_celsius():
    assert normalize_temperature(
        Decimal("37"), "Cel"
    ) == Decimal("37")


def test_temperature_fahrenheit():
    assert normalize_temperature(
        Decimal("98.6"), "[degF]"
    ) == Decimal("37")


def test_temperature_out_of_range():
    with pytest.raises(ValueError):
        normalize_temperature(Decimal("150"), "[degF]")


def test_spo2_nan_is_rejected():
    with pytest.raises(ValueError):
        normalize_spo2(Decimal("NaN"), "%")


def test_temperature_infinity_is_rejected():
    with pytest.raises(ValueError):
        normalize_temperature(Decimal("Infinity"), "Cel")