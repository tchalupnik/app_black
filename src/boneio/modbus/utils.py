from __future__ import annotations

from struct import unpack

from pymodbus.pdu import ModbusResponse

allowed_operations = {"multiply": lambda x, y: x * y if x else x}


def float32(result: ModbusResponse, base: int, addr: int) -> float:
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


def floatsofar(result: ModbusResponse, base: int, addr: int) -> float:
    """Read Float value from register."""
    low = result.getRegister(addr - base)
    high = result.getRegister(addr - base + 1)
    return high + low


def multiply0_1(result: ModbusResponse, base: int, addr: int) -> float:
    low = result.getRegister(addr - base)
    return round(low * 0.1, 4)


def multiply0_01(result: ModbusResponse, base: int, addr: int) -> float:
    low = result.getRegister(addr - base)
    return round(low * 0.01, 4)


def multiply0_001(result: ModbusResponse, base: int, addr: int) -> float:
    low = result.getRegister(addr - base)
    return round(low * 0.001, 4)


def multiply10(result: ModbusResponse, base: int, addr: int) -> float:
    low = result.getRegister(addr - base)
    return round(low * 10, 4)


def multiply100(result: ModbusResponse, base: int, addr: int) -> float:
    low = result.getRegister(addr - base)
    return round(low * 100, 4)


def multiply1000(result: ModbusResponse, base: int, addr: int) -> float:
    low = result.getRegister(addr - base)
    return round(low * 1000, 4)


def regular_result(result: ModbusResponse, base: int, addr: int) -> float:
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
