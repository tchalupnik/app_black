from __future__ import annotations

import asyncio
import logging
import struct
import time
from dataclasses import dataclass, field
from typing import Literal, assert_never

import anyio
from pymodbus.client import AsyncModbusSerialClient
from pymodbus.exceptions import ModbusException
from pymodbus.pdu import ModbusPDU

from boneio.config import UartConfig
from boneio.modbus.models import RegisterType, ValueType

_LOGGER = logging.getLogger(__name__)


@dataclass
class Modbus:
    """Represent modbus connection over chosen UART."""

    uart: UartConfig
    baudrate: int = 9600
    stopbits: int = 1
    bytesize: int = 8
    parity: str = "N"
    timeout: float = 3
    lock: anyio.Lock = field(default_factory=anyio.Lock)

    def __post_init__(self) -> None:
        """Initialize the Modbus hub."""
        _LOGGER.debug(
            "Setting UART for modbus communication: %s with baudrate %s, parity %s, stopbits %s, bytesize %s",
            self.uart.model_dump_json(),
            self.baudrate,
            self.parity,
            self.stopbits,
            self.bytesize,
        )

        self.client = AsyncModbusSerialClient(
            port=self.uart.id,
            baudrate=self.baudrate,
            stopbits=self.stopbits,
            bytesize=self.bytesize,
            parity=self.parity,
            timeout=self.timeout,
        )

    async def _pymodbus_connect(self) -> None:
        """Connect client."""
        try:
            await self.client.connect()
        except ModbusException as exception_error:
            _LOGGER.error("No connection to Modbus: %s", exception_error)
            raise

    async def read_and_decode(
        self,
        unit: int,
        address: int,
        payload_type: ValueType,
        count: int = 2,
        method: RegisterType = RegisterType.INPUT,
    ) -> float | int | str | list[bool] | list[int] | list[float]:
        """Call read_registers and decode."""
        result = await self.read_registers(
            unit=unit, address=address, count=count, register_type=method
        )
        decoded_value = self.decode_value(
            payload=result.registers, value_type=payload_type
        )
        return decoded_value

    async def read_registers(
        self,
        unit: int,  # device address
        address: int,  # modbus register address
        count: int = 2,  # number of registers to read
        register_type: RegisterType = RegisterType.INPUT,  # type of register: input, holding, coil
    ) -> ModbusPDU:
        """Call async pymodbus."""
        async with self.lock:
            start_time = time.perf_counter()

            try:
                await self._pymodbus_connect()
                _LOGGER.debug(
                    "Reading %s registers from %s with method %s from device %s.",
                    count,
                    address,
                    register_type,
                    unit,
                )

                result: ModbusPDU
                if register_type == RegisterType.INPUT:
                    result = await self.client.read_input_registers(
                        address=address, count=count, device_id=unit
                    )
                elif register_type == RegisterType.HOLDING:
                    result = await self.client.read_holding_registers(
                        address=address, count=count, device_id=unit
                    )
                elif register_type == RegisterType.COIL:
                    result = await self.client.read_coils(
                        address=address, count=count, device_id=unit
                    )
                else:
                    assert_never(register_type)

            except ValueError as exception_error:
                _LOGGER.error("Error reading registers: %s", exception_error)
                raise
            except (ModbusException, struct.error) as exception_error:
                _LOGGER.error("Error reading registers: %s", exception_error)
                raise
            except asyncio.TimeoutError:
                _LOGGER.error("Timeout reading registers from device %s", unit)
                raise
            except asyncio.CancelledError as err:
                _LOGGER.error(
                    "Operation cancelled reading registers from device %s with error %s",
                    unit,
                    err,
                )
                raise
            except Exception as e:
                _LOGGER.error(
                    "Unexpected error reading registers: %s - %s", type(e).__name__, e
                )
                raise
            else:
                end_time = time.perf_counter()
                _LOGGER.debug(
                    "Read completed in %.3f seconds: %s",
                    end_time - start_time,
                    result.registers,
                )
            return result

    def decode_value(
        self, payload: list[int], value_type: ValueType
    ) -> float | int | str | list[bool] | list[int] | list[float]:
        byteorder: Literal["big", "little"]
        if value_type in [
            ValueType.U_WORD,
            ValueType.S_WORD,
            ValueType.U_DWORD,
            ValueType.S_DWORD,
            ValueType.U_QWORD,
            ValueType.S_QWORD,
            ValueType.FP32,
        ]:
            byteorder = "big"
        elif value_type in [
            ValueType.U_DWORD_R,
            ValueType.S_DWORD_R,
            ValueType.U_QWORD_R,
            ValueType.FP32_R,
        ]:
            byteorder = "little"
        else:
            raise ValueError(f"Unsupported value type: {value_type}")

        if value_type == ValueType.U_WORD:
            data_type = self.client.DATATYPE.UINT16
        elif value_type == ValueType.S_WORD:
            data_type = self.client.DATATYPE.INT16
        elif value_type in [ValueType.U_DWORD, ValueType.U_DWORD_R]:
            data_type = self.client.DATATYPE.UINT32
        elif value_type in [ValueType.S_DWORD, ValueType.S_DWORD_R]:
            data_type = self.client.DATATYPE.INT32
        elif value_type in [ValueType.U_QWORD, ValueType.U_QWORD_R]:
            data_type = self.client.DATATYPE.UINT64
        elif value_type in [ValueType.S_QWORD, ValueType.S_QWORD_R]:
            data_type = self.client.DATATYPE.INT64
        elif value_type in [ValueType.FP32, ValueType.FP32_R]:
            data_type = self.client.DATATYPE.FLOAT32
        else:
            raise ValueError(f"Unsupported value type: {value_type}")

        return self.client.convert_from_registers(
            registers=payload, data_type=data_type, word_order=byteorder
        )

    async def write_register(
        self, unit: int | str, address: int, value: int
    ) -> ModbusPDU:
        """Call async pymodbus."""
        async with self.lock:
            start_time = time.perf_counter()
            try:
                # Run connection in the executor
                await self._pymodbus_connect()
                _LOGGER.debug(
                    "Writing register %s with value %s to device %s.",
                    address,
                    value,
                    unit,
                )

                # Run the read operation in the executor
                result: ModbusPDU = await self.client.write_register(
                    address=address, value=value, device_id=unit
                )

                if result.isError():
                    _LOGGER.error("Operation failed.")

            except ValueError as exception_error:
                _LOGGER.error(
                    "ValueError: Error writing registers: %s", exception_error
                )
                raise
            except (ModbusException, struct.error) as exception_error:
                _LOGGER.error(
                    "ModbusException: Error writing registers: %s", exception_error
                )
                raise
            except asyncio.TimeoutError:
                _LOGGER.error("Timeout writing registers to device %s", unit)
                raise
            except asyncio.CancelledError as err:
                _LOGGER.error(
                    "Operation cancelled writing registers to device %s with error %s",
                    unit,
                    err,
                )
                raise
            except Exception as e:
                _LOGGER.error(
                    "Unexpected error writing registers: %s - %s", type(e).__name__, e
                )
                raise
            finally:
                end_time = time.perf_counter()
                _LOGGER.debug(
                    "Write completed in %.3f seconds.",
                    end_time - start_time,
                )
            return result
