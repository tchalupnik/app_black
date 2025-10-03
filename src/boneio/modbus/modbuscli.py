from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from boneio.config import UartsConfig
from boneio.modbus.models import ModbusDevice

from .client import Modbus
from .utils import allowed_operations

_LOGGER = logging.getLogger(__name__)


@dataclass
class ModbusHelper:
    """Modbus Helper."""

    device: str
    uart: str
    address: int
    baudrate: int
    model: dict
    check_record: dict
    check_record_method: str
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
        name = self.check_record.get("name")
        address = self.check_record.get("address", 1)
        value_type = self.check_record.get("value_type")
        _LOGGER.info("Checking connection %s, address %s.", self.address, address)
        count = 1 if value_type == "S_WORD" or value_type == "U_WORD" else 2
        value = await self.modbus.read_registers(
            unit=self.address,
            address=address,
            count=count,
            method=self.check_record_method,
        )
        if not value:
            _LOGGER.error("No returned value.")
            return False
        payload = value.registers[0:count]
        try:
            decoded_value = self.modbus.decode_value(payload, value_type)
        except Exception as e:
            _LOGGER.error("Decoding error during checking connection %s", e)
            decoded_value = None
        for filter in self.check_record.get("filters", []):
            for key, value in filter.items():
                if key in allowed_operations:
                    lamda_function = allowed_operations[key]
                    decoded_value = lamda_function(decoded_value, value)
        _LOGGER.info(
            "Checked %s with address %s and value %s", name, address, decoded_value
        )
        if not decoded_value:
            return False
        return True

    def set_connection_speed(self, new_baudrate: int) -> int:
        baudrate_model = self.model["set_baudrate"]
        ind = baudrate_model["possible_baudrates"].get(str(new_baudrate))
        if ind:
            result = self.modbus.client.write_register(
                address=baudrate_model["address"],
                value=ind,
                unit=self.address,
            )
        if result.isError():
            _LOGGER.error("Operation failed.")
            return 1
        else:
            _LOGGER.info("Operation succeeded. Now restart device by disconnecting it.")
            return 0

    def set_new_address(self, new_address: int) -> None:
        if 0 < new_address < 253:
            _LOGGER.debug("New address register is %s", self.model["set_address"])
            result = self.modbus.client.write_register(
                address=self.model["set_address"],
                value=new_address,
                unit=self.address,
            )
            if result.isError():
                _LOGGER.error("Operation failed.")
            else:
                _LOGGER.info(
                    "Operation succeeded. Now restart device by disconnecting it."
                )
        else:
            _LOGGER.error("Invalid new address.")

    def set_custom_command(self, register_address: int, value: int | float) -> None:
        result = self.modbus.client.write_register(
            address=register_address,
            value=value,
            unit=self.address,
        )
        if result.isError():
            _LOGGER.error("Operation failed.")
        else:
            _LOGGER.info("Operation succeeded. Now restart device by disconnecting it.")


async def async_run_modbus_set(
    device: str,
    uart: str,
    address: int,
    baudrate: int,
    new_baudrate: int,
    new_address: int,
    custom_address: int,
    custom_value: int,
    stopbits: int = 1,
    bytesize: int = 8,
    parity: str = "N",
) -> Literal[0, 1]:
    """Run Modbus Set Function."""
    if new_address and new_baudrate:
        _LOGGER.error("Can't set both methods new_address and new_baudrate.")
    custom_cmd = True if device == "custom" else False
    set_base = {}
    if not custom_cmd:
        config = ModbusDevice.model_validate_json(Path(device).read_text())
        set_base = config.set_base or {}

        # Get first register base and convert to dict format for compatibility
        first_reg_base_obj = config.registers_base[0] if config.registers_base else None
        if not first_reg_base_obj:
            return False

        first_reg_base = {
            "register_type": first_reg_base_obj.register_type.value,
            "registers": [],
        }

        # Convert first register to dict format for compatibility
        first_register = (
            first_reg_base_obj.registers[0] if first_reg_base_obj.registers else None
        )
        if first_register:
            first_record = {
                "name": first_register.name,
                "address": first_register.address,
                "value_type": first_register.value_type.value,
                "filters": [
                    filter_dict.model_dump() for filter_dict in first_register.filters
                ]
                if first_register.filters
                else [],
            }
        else:
            first_record = {}
        _LOGGER.debug(
            "Connecting with params uart: %s, baudrate: %s, stopbits: %s, bytesize: %s, parity: %s.",
            uart,
            baudrate,
            stopbits,
            bytesize,
            parity,
        )
    else:
        first_record = {}
        first_reg_base = {}
    modbus_helper = ModbusHelper(
        device=device,
        uart=uart,
        address=address,
        baudrate=baudrate,
        model=set_base,
        check_record=first_record,
        check_record_method=first_reg_base.get("register_type", "input"),
        stopbits=stopbits,
        bytesize=bytesize,
        parity=parity,
    )

    async def default_action():
        if not await modbus_helper.check_connection():
            _LOGGER.error("Can't connect with sensor. Exiting")
            return 1
        if new_baudrate:
            return modbus_helper.set_connection_speed(new_baudrate=new_baudrate)
        if new_address:
            modbus_helper.set_new_address(new_address=new_address)
            return 0

    if not custom_cmd:
        _LOGGER.debug("Invoking default action.")
        return await default_action()
    elif custom_address is not None and custom_value is not None:
        _LOGGER.debug("Invoking custom command action.")
        modbus_helper.set_custom_command(
            register_address=custom_address, value=custom_value
        )
    return 1


async def async_run_modbus_search(
    uart: str,
    baudrate: int,
    register_address: int,
    register_type: str = "holding",
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
            method=register_type,
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
    uart: str,
    device_address: int,
    register_address: int,
    register_type: str,
    baudrate: int,
    value_type: str,
    register_range: str | None = None,
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

    value_size = 1 if value_type in ["S_WORD", "U_WORD"] else 2

    if register_range:
        try:
            start, stop = map(int, register_range.split("-"))
            if not (0 <= start <= stop <= 65535):
                raise ValueError("Invalid register range")

            success = False
            for addr in range(start, stop + 1):
                try:
                    value = await _modbus.read_registers(
                        unit=device_address,
                        address=addr,
                        count=value_size,
                        method=register_type,
                    )
                    if value:
                        payload = value.registers[0:value_size]
                        decoded_value = _modbus.decode_value(payload, value_type)
                        _LOGGER.info("Register %s: %s", addr, decoded_value)
                        success = True
                except Exception as e:
                    _LOGGER.error("Error reading register %s: %s", addr, str(e))

            return 0 if success else 1

        except ValueError:
            _LOGGER.error(
                "Invalid register range format: %s. Use format 'start-stop' (e.g., '1-230')",
                register_range,
            )
            return 1
    else:
        value = await _modbus.read_registers(
            unit=device_address,
            address=register_address,
            count=value_size,
            method=register_type,
        )
        if value:
            payload = value.registers[0:value_size]
            decoded_value = _modbus.decode_value(payload, value_type)
            _LOGGER.info("Value: %s", decoded_value)
            return 0
        _LOGGER.error("No returned value.")
        return 1
