from __future__ import annotations
import logging
import os
from ..helper.util import open_json
from boneio.const import UARTS, REGISTERS
from .client import Modbus
from .utils import REGISTERS_BASE, allowed_operations

_LOGGER = logging.getLogger(__name__)
SET_BASE = "set_base"
SET_ADDRESS = "set_address_address"
SET_BAUDRATE = "set_baudrate_address"


class ModbusHelper:
    """Modbus Helper."""

    baud_rates = [2400, 4800, 9600, 19200]

    def __init__(
        self,
        device: str,
        uart: str,
        address: int,
        baudrate: int,
        model: dict,
        check_record: dict,
        check_record_method: str,
        stopbits: int = 1,
        bytesize: int = 8,
        parity: str = "N",
    ) -> None:
        """Initialize Modbus Helper."""
        self._modbus = Modbus(
            uart=UARTS[uart],
            baudrate=baudrate,
            stopbits=stopbits,
            bytesize=bytesize,
            parity=parity,
        )
        self._model = model
        self._device = device
        self._device_address = address
        self._check_record = check_record
        self._check_record_method = check_record_method

    async def check_connection(self) -> bool:
        """Check Modbus connection."""
        name = self._check_record.get("name")
        address = self._check_record.get("address", 1)
        value_type = self._check_record.get("value_type")
        _LOGGER.info(
            f"Checking connection {self._device_address}, address {address}."
        )
        count = 1 if value_type == "S_WORD" or value_type == "U_WORD" else 2
        value = await self._modbus.read_multiple_registers(
            unit=self._device_address,
            address=address,
            count=count,
            method=self._check_record_method,
        )
        if not value:
            _LOGGER.error("No returned value.")
            return False
        payload = value.registers[0:count]
        decoded_value = self._modbus.decode_value(payload, value_type)
        for filter in self._check_record.get("filters", []):
            for key, value in filter.items():
                if key in allowed_operations:
                    lamda_function = allowed_operations[key]
                    decoded_value = lamda_function(decoded_value, value)
        _LOGGER.info(
            f"Checked {name} with address {address} and value {decoded_value}"
        )
        if not decoded_value:
            return False
        return True

    def set_connection_speed(self, new_baudrate: int):
        ind = self.baud_rates.index(new_baudrate)
        if ind:
            result = self._modbus.client.write_register(
                address=self._model[SET_BAUDRATE],
                value=ind,
                unit=self._device_address,
            )
        if result.isError():
            _LOGGER.error("Operation failed.")
        else:
            _LOGGER.info(
                "Operation succeeded. Now restart device by disconnecting it."
            )

    def set_new_address(self, new_address: int):
        if 0 < new_address < 253:
            result = self._modbus.client.write_register(
                address=self._model[SET_ADDRESS],
                value=new_address,
                unit=self._device_address,
            )
            if result.isError():
                _LOGGER.error("Operation failed.")
            else:
                _LOGGER.info(
                    "Operation succeeded. Now restart device by disconnecting it."
                )
        else:
            _LOGGER.error("Invalid new address.")


async def async_run_modbus_set(
    device: str,
    uart: str,
    address: int,
    baudrate: int,
    new_baudrate: int,
    new_address: int,
    stopbits: int = 1,
    bytesize: int = 8,
    parity: str = "N",
):
    """Run Modbus Set Function."""
    if new_address and new_baudrate:
        _LOGGER.error("Can't set both methods new_address and new_baudrate.")
    _db = open_json(path=os.path.dirname(__file__), model=device)
    set_base = _db.get(SET_BASE, {})
    first_reg_base = _db.get(REGISTERS_BASE, [])[0]
    if not first_reg_base:
        return False
    first_record = first_reg_base.get(REGISTERS, [])[0]
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
    if not await modbus_helper.check_connection():
        _LOGGER.error("Can't connect with sensor. Exiting")
        return 1
    if new_baudrate:
        modbus_helper.set_connection_speed(new_baudrate=new_baudrate)
        return 0
    if new_address:
        modbus_helper.set_new_address(new_address=new_address)
        return 0
    return 1


async def async_run_modbus_get(
    uart: str,
    device_address: int,
    register_address: int,
    register_type: str,
    baudrate: int,
    value_type: str,
    stopbits: int = 1,
    bytesize: int = 8,
    parity: str = "N",
):
    """Run Modbus Get Function."""
    _modbus = Modbus(
        uart=UARTS[uart],
        baudrate=baudrate,
        stopbits=stopbits,
        bytesize=bytesize,
        parity=parity,
    )
    count = 1 if value_type == "S_WORD" or value_type == "U_WORD" else 2
    value = await _modbus.read_multiple_registers(
        unit=device_address,
        address=register_address,
        count=count,
        method=register_type,
    )
    if value:
        payload = value.registers[0:count]
        decoded_value = _modbus.decode_value(payload, value_type)
        _LOGGER.info("Value: %s", decoded_value)
        return 0
    _LOGGER.error("No returned value.")
    return 1
