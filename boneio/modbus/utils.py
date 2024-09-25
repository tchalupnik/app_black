from __future__ import annotations
from struct import unpack


allowed_operations = {"multiply": lambda x, y: x * y}


def float32(result, base, addr):
    """Read Float value from register."""
    low = result.getRegister(addr - base)
    high = result.getRegister(addr - base + 1)
    data = bytearray(4)
    data[0] = high & 0xFF
    data[1] = high >> 8
    data[2] = low & 0xFF
    data[3] = low >> 8
    val = unpack("f", bytes(data))
    return val[0]


def floatsofar(result, base, addr):
    """Read Float value from register."""
    low = result.getRegister(addr - base)
    high = result.getRegister(addr - base + 1)
    return high + low


def multiply0_1(result, base, addr):
    low = result.getRegister(addr - base)
    return round(low * 0.1, 4)


def multiply0_01(result, base, addr):
    low = result.getRegister(addr - base)
    return round(low * 0.01, 4)


def multiply0_001(result, base, addr):
    low = result.getRegister(addr - base)
    return round(low * 0.001, 4)


def multiply10(result, base, addr):
    low = result.getRegister(addr - base)
    return round(low * 10, 4)


def multiply100(result, base, addr):
    low = result.getRegister(addr - base)
    return round(low * 100, 4)


def multiply1000(result, base, addr):
    low = result.getRegister(addr - base)
    return round(low * 1000, 4)


def regular_result(result, base, addr):
    return result.getRegister(addr - base)


CONVERT_METHODS = {
    "float32": float32,
    "multiply0_1": multiply0_1,
    "multiply0_01": multiply0_01,
    "multiply0_001": multiply0_001,
    "floatsofar": floatsofar,
    "multiply10": multiply10,
    "multiply100": multiply100,
    "multiply1000": multiply1000,
    "regular": regular_result,
}
REGISTERS_BASE = "registers_base"
