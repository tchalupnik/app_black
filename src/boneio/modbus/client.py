from __future__ import annotations

import asyncio
import logging
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import assert_never

import anyio
from pymodbus.client.common import WriteSingleRegisterResponse
from pymodbus.client.sync import BaseModbusClient, ModbusSerialClient
from pymodbus.constants import Endian
from pymodbus.exceptions import ModbusException
from pymodbus.payload import BinaryPayloadDecoder
from pymodbus.pdu import ModbusResponse

from boneio.config import UartConfig
from boneio.modbus.models import RegisterType, ValueType

_LOGGER = logging.getLogger(__name__)


# Maximum number of worker threads for Modbus operations
MAX_WORKERS = 4
# Timeout for Modbus operations in seconds
OPERATION_TIMEOUT = 5


class ModbusUartException(BaseException):
    """Cover configuration exception."""


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

        if self.uart.rx is None:
            raise ModbusUartException
        _LOGGER.debug(
            "Setting UART for modbus communication: %s with baudrate %s, parity %s, stopbits %s, bytesize %s",
            self.uart.model_dump_json(),
            self.baudrate,
            self.parity,
            self.stopbits,
            self.bytesize,
        )

        # generic configuration
        self.client: BaseModbusClient | None = None
        self._loop = asyncio.get_event_loop()
        self._executor = ThreadPoolExecutor(
            max_workers=MAX_WORKERS, thread_name_prefix="modbus_worker"
        )

        try:
            self.client = ModbusSerialClient(
                port=self.uart.id,
                method="rtu",
                baudrate=self.baudrate,
                stopbits=self.stopbits,
                bytesize=self.bytesize,
                parity=self.parity,
                timeout=self.timeout,
            )
        except ModbusException as exception_error:
            _LOGGER.error(exception_error)

    async def async_close(self) -> None:
        """Disconnect client."""
        if self.client:
            try:
                # Run close in the executor
                await self._loop.run_in_executor(self._executor, self.client.close)
            except asyncio.CancelledError:
                _LOGGER.warning("modbus communication closed")
            except ModbusException as exception_error:
                _LOGGER.error(exception_error)
            finally:
                del self.client
                self.client = None
                self._executor.shutdown(wait=False)
                _LOGGER.warning("modbus communication closed")

    def _pymodbus_connect(self) -> bool:
        """Connect client."""
        try:
            return self.client.connect()  # type: ignore[union-attr]
        except ModbusException as exception_error:
            _LOGGER.error("No connection to Modbus: %s", exception_error)
            return False

    async def read_and_decode(
        self,
        unit: int | str,
        address: int,
        payload_type: ValueType,
        count: int = 2,
        method: RegisterType = RegisterType.INPUT,
    ) -> float | None:
        """Call read_registers and decode."""
        result = await self.read_registers(
            unit=unit, address=address, count=count, register_type=method
        )
        if not result or result.isError():
            return None
        decoded_value = self.decode_value(
            payload=result.registers, value_type=payload_type
        )
        return decoded_value

    def read_registers_blocking(
        self,
        unit: int | str,
        address: int,
        count: int = 2,
        register_type: RegisterType = RegisterType.INPUT,
    ) -> ModbusResponse:
        start_time = time.perf_counter()
        result = None

        try:
            # Run connection in the executor
            connected = self._pymodbus_connect()
            if not connected:
                _LOGGER.error("Can't connect to Modbus.")
                return None

            _LOGGER.debug(
                "Reading %s registers from %s with method %s from device %s.",
                count,
                address,
                register_type,
                unit,
            )

            if register_type == RegisterType.INPUT:
                result = self.client.read_input_registers(
                    address=address, count=count, unit=unit
                )
            elif register_type == RegisterType.HOLDING:
                result = self.client.read_holding_registers(
                    address=address, count=count, unit=unit
                )
            elif register_type == RegisterType.COIL:
                result = self.client.read_coils(address=address, count=count, unit=unit)
            else:
                assert_never(register_type)

        except ValueError as exception_error:
            _LOGGER.error("Error reading registers: %s", exception_error)
        except (ModbusException, struct.error) as exception_error:
            _LOGGER.error("Error reading registers: %s", exception_error)
        except asyncio.TimeoutError:
            _LOGGER.error("Timeout reading registers from device %s", unit)
        except asyncio.CancelledError as err:
            _LOGGER.error(
                "Operation cancelled reading registers from device %s with error %s",
                unit,
                err,
            )
        except Exception as e:
            _LOGGER.error(
                "Unexpected error reading registers: %s - %s", type(e).__name__, e
            )
        else:
            end_time = time.perf_counter()
            _LOGGER.debug(
                "Read completed in %.3f seconds: %s",
                end_time - start_time,
                result.registers,
            )
        return result

    def write_register_blocking(
        self, unit: int | str, address: int, value: int | float
    ) -> ModbusResponse:
        """Call async pymodbus."""
        start_time = time.perf_counter()
        result = None
        try:
            # Run connection in the executor
            connected = self._pymodbus_connect()
            if not connected:
                _LOGGER.error("Can't connect to Modbus.")
                return None

            _LOGGER.debug(
                "Writing register %s with value %s to device %s.",
                address,
                value,
                unit,
            )

            # Run the read operation in the executor
            result: WriteSingleRegisterResponse = self.client.write_register(
                address=address, value=value, unit=unit
            )

            if result.isError():
                _LOGGER.error("Operation failed.")
                result = None

        except ValueError as exception_error:
            _LOGGER.error("ValueError: Error writing registers: %s", exception_error)
        except (ModbusException, struct.error) as exception_error:
            _LOGGER.error(
                "ModbusException: Error writing registers: %s", exception_error
            )
        except asyncio.TimeoutError:
            _LOGGER.error("Timeout writing registers to device %s", unit)
        except asyncio.CancelledError as err:
            _LOGGER.error(
                "Operation cancelled writing registers to device %s with error %s",
                unit,
                err,
            )
        except Exception as e:
            _LOGGER.error(
                "Unexpected error writing registers: %s - %s", type(e).__name__, e
            )
        finally:
            end_time = time.perf_counter()
            _LOGGER.debug(
                "Write completed in %.3f seconds.",
                end_time - start_time,
            )
        return result

    async def read_registers(
        self,
        unit: int | str,  # device address
        address: int,  # modbus register address
        count: int = 2,  # number of registers to read
        register_type: RegisterType = RegisterType.INPUT,  # type of register: input, holding, coil
    ) -> ModbusResponse:
        """Call async pymodbus."""
        async with self.lock:
            return await self._loop.run_in_executor(
                self._executor,
                self.read_registers_blocking,
                unit,
                address,
                count,
                register_type,
            )

    def decode_value(self, payload, value_type: ValueType):
        if value_type in [
            ValueType.U_WORD,
            ValueType.S_WORD,
            ValueType.U_DWORD,
            ValueType.S_DWORD,
            ValueType.U_QWORD,
            ValueType.S_QWORD,
            ValueType.FP32,
        ]:
            byteorder = Endian.Big
        elif value_type in [
            ValueType.U_DWORD_R,
            ValueType.S_DWORD_R,
            ValueType.U_QWORD_R,
            ValueType.FP32_R,
        ]:
            byteorder = Endian.Little
        else:
            assert_never(value_type)
        decoder = BinaryPayloadDecoder.fromRegisters(
            registers=payload, byteorder=byteorder
        )
        if value_type == ValueType.U_WORD:
            return decoder.decode_16bit_uint()
        elif value_type == ValueType.S_WORD:
            return decoder.decode_16bit_int()
        elif value_type in [ValueType.U_DWORD, ValueType.U_DWORD_R]:
            return decoder.decode_32bit_uint()
        elif value_type in [ValueType.S_DWORD, ValueType.S_DWORD_R]:
            return decoder.decode_32bit_int()
        elif value_type in [ValueType.U_QWORD, ValueType.U_QWORD_R]:
            return decoder.decode_64bit_uint()
        elif value_type in [ValueType.S_QWORD, ValueType.S_QWORD_R]:
            return decoder.decode_64bit_int()
        elif value_type in [ValueType.FP32, ValueType.FP32_R]:
            return decoder.decode_32bit_float()
        else:
            assert_never(value_type)

    async def write_register(
        self, unit: int | str, address: int, value: int | float
    ) -> ModbusResponse:
        """Call async pymodbus."""
        async with self.lock:
            return await self._loop.run_in_executor(
                self._executor, self.write_register_blocking, unit, address, value
            )
