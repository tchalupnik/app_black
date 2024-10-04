from __future__ import annotations

import asyncio
import logging
import struct
import time
from typing import Any

from pymodbus.client.sync import BaseModbusClient, ModbusSerialClient
from pymodbus.constants import Endian
from pymodbus.exceptions import ModbusException
from pymodbus.payload import BinaryPayloadDecoder
from pymodbus.pdu import ModbusResponse
from pymodbus.register_read_message import ReadInputRegistersResponse

from boneio.const import ID, REGISTERS, RX, TX, UART
from boneio.helper import configure_pin
from boneio.helper.exceptions import ModbusUartException

_LOGGER = logging.getLogger(__name__)

VALUE_TYPES = {
    "U_WORD": {"f": "decode_16bit_uint", "byteorder": Endian.Big},
    "S_WORD": {"f": "decode_16bit_int", "byteorder": Endian.Big},
    "U_DWORD": {"f": "decode_32bit_uint", "byteorder": Endian.Big},
    "S_DWORD": {"f": "decode_32bit_int", "byteorder": Endian.Big},
    "U_DWORD_R": {"f": "decode_32bit_uint", "byteorder": Endian.Little},
    "S_DWORD_R": {"f": "decode_32bit_int", "byteorder": Endian.Little},
    "U_QWORD": {"f": "decode_64bit_uint", "byteorder": Endian.Big},
    "S_QWORD": {"f": "decode_64bit_int", "byteorder": Endian.Big},
    "U_QWORD_R": {"f": "decode_64bit_uint", "byteorder": Endian.Little},
    "FP32": {"f": "decode_32bit_float", "byteorder": Endian.Big},
    "FP32_R": {"f": "decode_32bit_float", "byteorder": Endian.Little},
}


class Modbus:
    """Represent modbus connection over chosen UART."""

    def __init__(
        self,
        uart: dict[str, Any],
        baudrate: int = 9600,
        stopbits: int = 1,
        bytesize: int = 8,
        parity: str = "N",
        timeout: float = 3,
    ) -> None:
        """Initialize the Modbus hub."""
        rx = uart.get(RX)
        tx = uart.get(TX)
        if not tx or not rx:
            raise ModbusUartException
        _LOGGER.debug(
            f"Setting UART for modbus communication: {uart} with baudrate {baudrate}, parity {parity}, stopbits {stopbits}, bytesize {bytesize}",
        )
        configure_pin(pin=rx, mode=UART)
        configure_pin(pin=tx, mode=UART)
        self._uart = uart

        # generic configuration
        self._client: BaseModbusClient | None = None
        self._lock = asyncio.Lock()

        try:
            self._client = ModbusSerialClient(
                port=self._uart[ID],
                method="rtu",
                baudrate=baudrate,
                stopbits=stopbits,
                bytesize=bytesize,
                parity=parity,
                timeout=timeout,
            )
            self._read_methods = {
                "input": self._client.read_input_registers,
                "holding": self._client.read_holding_registers,
            }
        except ModbusException as exception_error:
            _LOGGER.error(exception_error)

    @property
    def client(self) -> ModbusSerialClient | None:
        """Return client."""
        return self._client

    async def async_close(self) -> None:
        """Disconnect client."""
        async with self._lock:
            if self._client:
                try:
                    self._client.close()
                except ModbusException as exception_error:
                    _LOGGER.error(exception_error)
                del self._client
                self._client = None
                _LOGGER.warning("modbus communication closed")

    def _pymodbus_connect(self) -> bool:
        """Connect client."""
        try:
            return self._client.connect()  # type: ignore[union-attr]
        except ModbusException as exception_error:
            _LOGGER.error(exception_error)
            return False

    async def read_and_decode(
        self,
        unit: int | str,
        address: int,
        payload_type: str,
        count: int = 2,
        method: str = "input",
    ) -> float | None:
        """Call read_registers and decode."""
        result = await self.read_registers(
            unit=unit, address=address, count=count, method=method
        )
        if not result or result.isError():
            return None
        decoded_value = self.decode_value(
            payload=result.registers, value_type=payload_type
        )
        return decoded_value

    async def read_registers(
        self,
        unit: int | str,  # device address
        address: int,  # modbus register address
        count: int = 2,  # number of registers to read
        method: str = "input",  # type of register: input, holding
    ) -> ModbusResponse:
        """Call async pymodbus."""
        async with self._lock:
            start_time = time.perf_counter()
            if not self._pymodbus_connect():
                _LOGGER.error("Can't connect to Modbus.")
                return None
            kwargs = {"unit": unit, "count": count} if unit else {}
            try:
                read_method = self._read_methods[method]
                _LOGGER.debug(
                    "Reading %s registers from %s with method %s from device %s.",
                    count,
                    address,
                    method,
                    unit,
                )
                result: ReadInputRegistersResponse = read_method(
                    address, **kwargs
                )
            except (ModbusException, struct.error) as exception_error:
                _LOGGER.error(exception_error)
                return None
            if not hasattr(result, REGISTERS):
                _LOGGER.error(str(result))
                return None
            end_time = time.perf_counter()
            _LOGGER.debug(
                "Time of execution of read_registers: %s ms.",
                round((end_time - start_time) * 1000, 3),
            )
            return result

    def decode_value(self, payload, value_type):
        _payload_type = VALUE_TYPES[value_type]
        decoder = BinaryPayloadDecoder.fromRegisters(
            registers=payload, byteorder=_payload_type["byteorder"]
        )
        try:
            value = getattr(decoder, _payload_type["f"])()
        except Exception as e:
            _LOGGER.error(e)
            pass
        return value
