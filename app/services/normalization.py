from decimal import Decimal


def normalize_spo2(value: Decimal, unit: str) -> Decimal:
    if not value.is_finite():
        raise ValueError("Measurement must be a finite number")
    if unit == "%":
        if not 0 <= value <= 100:
            raise ValueError("SpO2 percentage must be between 0 and 100")
        return value

    if unit == "1":
        if not 0 <= value <= 1:
            raise ValueError("SpO2 fraction must be between 0 and 1")
        return value * Decimal("100")

    raise ValueError("Unsupported SpO2 unit")


def normalize_temperature(value: Decimal, unit: str) -> Decimal:
    if not value.is_finite():
        raise ValueError("Measurement must be a finite number")
    if unit == "Cel":
        celsius = value
    elif unit == "[degF]":
        celsius = (value - Decimal("32")) * Decimal("5") / Decimal("9")
    else:
        raise ValueError("Unsupported temperature unit")

    if not Decimal("25") <= celsius <= Decimal("45"):
        raise ValueError("Temperature is outside the supported range")

    return celsius