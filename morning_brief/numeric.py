import math


def finite_float(value):
    if isinstance(value, bool):
        raise ValueError("boolean is not a numeric market value")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("market value is not finite")
    return result
