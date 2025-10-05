from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from boneio.config import Uarts, UartsConfig
from boneio.modbus.models import ModbusDevice, RegisterType, ValueType

from .client import Modbus

_LOGGER = logging.getLogger(__name__)


@dataclass
class ModbusHelper:
    """Modbus Helper."""

    device: str
    uart: str
    address: int
    baudrate: int
    modbus_device: ModbusDevice | None = None
    stopbits: int = 1
    bytesize: int = 8
    parity: str = "N"
    modbus: Modbus = field(init=False)

    baud_rates = [2400, 4800, 9600, 19200]

    def __post_init__(self) -> None:
        """Initialize Modbus instance."""
        self.modbus = Modbus(
            uart=UartsConfig[self.uart],
            baudrate=self.baudrate,
            stopbits=self.stopbits,
            bytesize=self.bytesize,
            parity=self.parity,
        )

    async def check_connection(self) -> bool:
        """Check Modbus connection."""
        if self.modbus_device is None:
            return False

        if not self.modbus_device.registers_base:
            return False

        base = self.modbus_device.registers_base[0]
        if not base.registers:
            return False

        first_register = base.registers[0]

        _LOGGER.info(
            "Checking connection %s, address %s.", self.address, first_register.address
        )
        count = (
            1
            if first_register.value_type in (ValueType.S_WORD, ValueType.U_WORD)
            else 2
        )
        value = await self.modbus.read_registers(
            unit=self.address,
            address=first_register.address,
            count=count,
            register_type=base.register_type,
        )
        if not value:
            _LOGGER.error("No returned value.")
            return False
        payload = value.registers[0:count]
        decoded_value = self.modbus.decode_value(payload, first_register.value_type)
        _LOGGER.info(
            "Checked %s with address %s and value %s",
            first_register.name,
            first_register.address,
            decoded_value,
        )
        return True

    async def set_connection_speed(self, new_baudrate: int) -> Literal[0, 1]:
        if self.modbus_device is None or self.modbus_device.set_base is None:
            _LOGGER.error("No set_base defined in device configuration.")
            return 1
        baudrate_model = self.modbus_device.set_base.set_baudrate
        ind = baudrate_model.possible_baudrates.get(str(new_baudrate))
        if ind is not None:
            result = await self.modbus.client.write_register(
                address=baudrate_model.address,
                value=ind,
                device_id=self.address,
            )
            if not result.isError():
                _LOGGER.info(
                    "Operation succeeded. Now restart device by disconnecting it."
                )
                return 0
        _LOGGER.error("Operation failed.")
        return 1

    async def set_new_address(self, new_address: int) -> None:
        if self.modbus_device is None or self.modbus_device.set_base is None:
            _LOGGER.error("No set_base defined in device configuration.")
            return 1
        if 0 < new_address < 253:
            _LOGGER.debug(
                "New address register is %s", self.modbus_device.set_base.set_address
            )
            result = await self.modbus.client.write_register(
                address=self.modbus_device.set_base.set_address,
                value=new_address,
                device_id=self.address,
            )
            if result.isError():
                _LOGGER.error("Operation failed.")
            else:
                _LOGGER.info(
                    "Operation succeeded. Now restart device by disconnecting it."
                )
        else:
            _LOGGER.error("Invalid new address.")

    async def set_custom_command(
        self, register_address: int, value: int | float
    ) -> None:
        result = await self.modbus.client.write_register(
            address=register_address,
            value=value,
            device_id=self.address,
        )
        if result.isError():
            _LOGGER.error("Operation failed.")
        else:
            _LOGGER.info("Operation succeeded. Now restart device by disconnecting it.")


async def async_run_modbus_set(
    device: str,
    uart: Uarts,
    address: int,
    baudrate: int,
    new_baudrate: int | None,
    new_address: int | None,
    custom_address: int | None,
    custom_value: int | None,
    stopbits: int = 1,
    bytesize: int = 8,
    parity: str = "N",
) -> Literal[0, 1]:
    """Run Modbus Set Function."""
    if new_address is not None and new_baudrate is not None:
        raise ValueError("Can't set both methods new_address and new_baudrate.")
    custom_cmd = bool(device == "custom")
    modbus_device: ModbusDevice | None = None
    if not custom_cmd:
        modbus_device = ModbusDevice.model_validate_json(
            (Path("modbus_devices") / f"{device}.json").read_text()
        )
        _LOGGER.debug(
            "Connecting with params uart: %s, baudrate: %s, stopbits: %s, bytesize: %s, parity: %s.",
            uart,
            baudrate,
            stopbits,
            bytesize,
            parity,
        )
    modbus_helper = ModbusHelper(
        device=device,
        uart=uart,
        address=address,
        baudrate=baudrate,
        modbus_device=modbus_device,
        stopbits=stopbits,
        bytesize=bytesize,
        parity=parity,
    )

    async def default_action() -> Literal[0, 1]:
        if not await modbus_helper.check_connection():
            _LOGGER.error("Can't connect with sensor. Exiting")
            return 1
        if new_baudrate is not None:
            return await modbus_helper.set_connection_speed(new_baudrate=new_baudrate)
        if new_address is not None:
            await modbus_helper.set_new_address(new_address=new_address)
            return 0
        raise ValueError("It should not happen.")

    if not custom_cmd:
        _LOGGER.debug("Invoking default action.")
        return await default_action()
    elif custom_address is not None and custom_value is not None:
        _LOGGER.debug("Invoking custom command action.")
        await modbus_helper.set_custom_command(
            register_address=custom_address, value=custom_value
        )
    return 1


async def async_run_modbus_search(
    uart: Uarts,
    baudrate: int,
    register_address: int,
    register_type: RegisterType = RegisterType.HOLDING,
    stopbits: int = 1,
    bytesize: int = 8,
    parity: str = "N",
) -> Literal[0]:
    """Run Modbus Search Function."""
    _modbus = Modbus(
        uart=UartsConfig[uart],
        baudrate=baudrate,
        stopbits=stopbits,
        bytesize=bytesize,
        parity=parity,
        timeout=0.1,
    )
    units_found = []
    for unit_id in range(1, 248):  # Modbus RTU address range is 1 to 247
        _LOGGER.debug("Searching device at address %s.", unit_id)
        value = await _modbus.read_registers(
            unit=unit_id,
            address=register_address,
            count=2,
            register_type=register_type,
        )
        if value:
            units_found.append(unit_id)
            _LOGGER.info("Found device at address %s.", unit_id)
        else:
            _LOGGER.debug("No device found at address %s.", unit_id)
    if units_found:
        _LOGGER.info("Found devices: [%s]", ", ".join(str(x) for x in units_found))
    else:
        _LOGGER.info("No devices found.")
    return 0


async def async_run_modbus_get(
    uart: Uarts,
    device_address: int,
    register_range: str,
    register_type: RegisterType,
    baudrate: int,
    value_type: ValueType,
    stopbits: int = 1,
    bytesize: int = 8,
    parity: str = "N",
) -> Literal[0, 1]:
    """Run Modbus Get Function."""
    _LOGGER.debug(
        "Connecting with params uart: %s, baudrate: %s, stopbits: %s, bytesize: %s, parity: %s.",
        uart,
        baudrate,
        stopbits,
        bytesize,
        parity,
    )
    _modbus = Modbus(
        uart=UartsConfig[uart],
        baudrate=baudrate,
        stopbits=stopbits,
        bytesize=bytesize,
        parity=parity,
    )

    value_size = 1 if value_type in [ValueType.S_WORD, ValueType.U_WORD] else 2

    try:
        start, stop = map(int, register_range.split("-"))
        if not (0 <= start <= stop <= 65535):
            raise ValueError("Invalid register range")

        for addr in range(start, stop + 1):
            try:
                value = await _modbus.read_registers(
                    unit=device_address,
                    address=addr,
                    count=value_size,
                    register_type=register_type,
                )
                if value:
                    payload = value.registers[0:value_size]
                    decoded_value = _modbus.decode_value(payload, value_type)
                    _LOGGER.info("Register %s: %s", addr, decoded_value)
                    return 0
            except Exception as e:
                _LOGGER.error("Error reading register %s: %s", addr, str(e))

        return 1

    except ValueError:
        _LOGGER.error(
            "Invalid register range format: %s. Use format 'start-stop' (e.g., '1-230')",
            register_range,
        )
        return 1
