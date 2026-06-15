"""Sensmos — rodziny jednostek, konwersja, dopasowanie encji HA."""
from __future__ import annotations

# Rodzina: {jednostka: mnożnik do jednostki bazowej}
_FAMILIES: dict[str, dict[str, float]] = {
    "power":       {"W": 1, "kW": 1000, "MW": 1e6, "mW": 0.001},
    "voltage":     {"V": 1, "mV": 0.001, "kV": 1000},
    "current":     {"A": 1, "mA": 0.001},
    "energy":      {"Wh": 1, "kWh": 1000, "MWh": 1e6},
    "frequency":   {"Hz": 1, "kHz": 1000, "MHz": 1e6},
    "percent":     {"%": 1},
    "pressure":    {"hPa": 1, "mbar": 1, "kPa": 10, "Pa": 0.01, "bar": 1000, "mmHg": 1.333},
    "signal":      {"dBm": 1, "dB": 1},
    "distance":    {"m": 1, "km": 1000, "cm": 0.01, "mm": 0.001},
    "speed":       {"m/s": 1, "km/h": 0.2778, "mph": 0.447},
    "mass":        {"g": 1, "kg": 1000, "mg": 0.001},
    "duration":    {"s": 1, "min": 60, "h": 3600, "ms": 0.001},
    "illuminance": {"lx": 1},
    "co2":         {"ppm": 1, "ppb": 0.001},
}

_TEMP = ("°C", "°F", "K", "C", "F")

# Rodzina → device_class HA (do filtrowania pickera encji)
FAMILY_DEVICE_CLASSES: dict[str, list[str]] = {
    "power":       ["power"],
    "voltage":     ["voltage"],
    "current":     ["current"],
    "energy":      ["energy"],
    "frequency":   ["frequency"],
    "percent":     ["battery", "humidity", "moisture", "power_factor"],
    "pressure":    ["pressure", "atmospheric_pressure"],
    "signal":      ["signal_strength"],
    "distance":    ["distance"],
    "speed":       ["speed", "wind_speed"],
    "mass":        ["weight"],
    "duration":    ["duration"],
    "illuminance": ["illuminance"],
    "co2":         ["carbon_dioxide"],
    "temperature": ["temperature"],
}


def family_of(unit: str | None) -> str | None:
    """Zwraca nazwę rodziny jednostki albo None."""
    if not unit:
        return None
    if unit in _TEMP:
        return "temperature"
    for fam, units in _FAMILIES.items():
        if unit in units:
            return fam
    return None


def compatible(unit_a: str | None, unit_b: str | None) -> bool:
    """Czy jednostki są wzajemnie przeliczalne."""
    fa, fb = family_of(unit_a), family_of(unit_b)
    if fa is None or fb is None:
        return (unit_a or "") == (unit_b or "")
    return fa == fb


def _to_celsius(value: float, unit: str) -> float:
    if unit in ("°C", "C"):
        return value
    if unit in ("°F", "F"):
        return (value - 32) * 5 / 9
    return value - 273.15  # K


def _from_celsius(value: float, unit: str) -> float:
    if unit in ("°C", "C"):
        return value
    if unit in ("°F", "F"):
        return value * 9 / 5 + 32
    return value + 273.15  # K


def convert(value: float, from_unit: str | None, to_unit: str | None) -> float | None:
    """Przelicz wartość między jednostkami. None gdy niekompatybilne."""
    if not from_unit or not to_unit or from_unit == to_unit:
        return value
    fa, fb = family_of(from_unit), family_of(to_unit)
    if fa is None or fb is None or fa != fb:
        return None
    if fa == "temperature":
        return _from_celsius(_to_celsius(value, from_unit), to_unit)
    a = _FAMILIES[fa][from_unit]
    b = _FAMILIES[fa][to_unit]
    return value * a / b


def device_classes_for_unit(unit: str | None) -> list[str]:
    """device_class HA pasujące do jednostki (filtr pickera)."""
    fam = family_of(unit)
    if fam is None:
        return []
    return FAMILY_DEVICE_CLASSES.get(fam, [])
