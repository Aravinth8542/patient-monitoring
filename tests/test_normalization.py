from decimal import Decimal

import pytest

from app.services.normalization import normalize_spo2
from app.services.normalization import normalize_spo2, normalize_temperature


def test_spo2_percentage():
    """
    An SpO2 value of 97 with unit '%' is already in canonical percentage form. Normalization
    must return Decimal('97') without scaling it.
    """
    assert normalize_spo2(Decimal("97"), "%") == Decimal("97")


def test_spo2_fraction():
    """
    An SpO2 value of 0.97 with dimensionless unit '1' represents a 97% saturation.
    Normalization must multiply by 100 and return Decimal('97').
    """
    assert normalize_spo2(Decimal("0.97"), "1") == Decimal("97")


def test_spo2_invalid_fraction():
    """
    The value 97 supplied with fractional unit '1' is not a valid 0-to-1 fraction.
    Normalization must raise ValueError rather than incorrectly convert it to 9700%.
    """
    with pytest.raises(ValueError):
        normalize_spo2(Decimal("97"), "1")


def test_temperature_celsius():
    """
    A temperature of 37 with UCUM unit 'Cel' is already Celsius. Normalization must preserve
    Decimal('37').
    """
    assert normalize_temperature(
        Decimal("37"), "Cel"
    ) == Decimal("37")


def test_temperature_fahrenheit():
    """
    A temperature of 98.6 with UCUM unit '[degF]' is equivalent to 37 Celsius. Normalization
    must convert it to Decimal('37').
    """
    assert normalize_temperature(
        Decimal("98.6"), "[degF]"
    ) == Decimal("37")


def test_temperature_out_of_range():
    """
    The supplied Fahrenheit value 150 is outside the accepted physiological range after
    conversion. Normalization must raise ValueError instead of storing the implausible
    reading.
    """
    with pytest.raises(ValueError):
        normalize_temperature(Decimal("150"), "[degF]")


def test_spo2_nan_is_rejected():
    """
    NaN is not an ordered numeric saturation value and cannot safely participate in
    threshold comparisons. The SpO2 normalizer must reject Decimal('NaN') with ValueError.
    """
    with pytest.raises(ValueError):
        normalize_spo2(Decimal("NaN"), "%")


def test_temperature_infinity_is_rejected():
    """
    Infinity is not a finite clinical temperature and would corrupt aggregate statistics.
    The temperature normalizer must reject Decimal('Infinity') with ValueError.
    """
    with pytest.raises(ValueError):
        normalize_temperature(Decimal("Infinity"), "Cel")