"""Typed models for Modbus device configurations using Pydantic."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, RootModel, field_validator


class ValueType(str, Enum):
    U_WORD = "U_WORD"  # (unsigned 16 bit integer from 1 register = 16bit)
    S_WORD = "S_WORD"  # (signed 16 bit integer from 1 register = 16bit)
    U_DWORD = "U_DWORD"  # (unsigned 32 bit integer from 2 registers = 32bit)
    S_DWORD = "S_DWORD"  # (signed 32 bit integer from 2 registers = 32bit)
    U_DWORD_R = "U_DWORD_R"  # (unsigned 32 bit integer from 2 registers low word first)
    S_DWORD_R = "S_DWORD_R"  # (signed 32 bit integer from 2 registers low word first)
    U_QWORD = "U_QWORD"  # (unsigned 64 bit integer from 4 registers = 64bit)
    S_QWORD = "S_QWORD"  # (signed 64 bit integer from 4 registers = 64bit)
    U_QWORD_R = "U_QWORD_R"  # (unsigned 64 bit integer from 4 registers low word first)
    S_QWORD_R = "S_QWORD_R"  # (signed 64 bit integer from 4 registers low word first)
    FP32 = "FP32"  # (32 bit IEEE 754 floating point from 2 registers)
    FP32_R = (
        "FP32_R"  # (32 bit IEEE 754 floating point - same as FP32 but low word first)
    )


class RegisterType(str, Enum):
    """Supported register types."""

    INPUT = "input"
    HOLDING = "holding"
    COIL = "coil"


class AdditionalSensorBase(BaseModel):
    """Represents an additional sensor configuration."""

    entity_type: Literal["text_sensor", "sensor", "select", "switch"]
    name: str
    source: str
    x_mapping: dict[str, str] = Field(default_factory=dict, description="Value mapping")
    config_keys: list[str] = Field(
        default_factory=list, description="Configuration keys needed"
    )


class NumericAdditionalSensor(AdditionalSensorBase):
    entity_type: Literal["sensor"] = "sensor"
    unit_of_measurement: str = Field("m3", description="Unit of measurement")
    state_class: str = Field(
        "measurement", description="State class for Home Assistant"
    )
    device_class: str = Field("volume", description="Device class for Home Assistant")
    formula: str = Field("", description="Formula for calculations")
    config_keys: list[str] = Field(
        default_factory=list, description="Configuration keys needed"
    )


class SwitchAdditionalSensor(AdditionalSensorBase):
    entity_type: Literal["switch"] = "switch"
    payload_off: str = Field("OFF", description="Payload for OFF state")
    payload_on: str = Field("ON", description="Payload for ON state")


class SelectAdditionalSensor(AdditionalSensorBase):
    entity_type: Literal["select"] = "select"


class TextAdditionalSensor(AdditionalSensorBase):
    entity_type: Literal["text_sensor"] = "text_sensor"


AdditionalSensors = (
    NumericAdditionalSensor
    | SwitchAdditionalSensor
    | SelectAdditionalSensor
    | TextAdditionalSensor
)


class AdditionalSensor(RootModel[AdditionalSensors]):
    """Union type for additional sensors."""

    root: AdditionalSensors = Field(discriminator="entity_type")


class Filter(BaseModel):
    """Represents a filter operation to apply to a register value."""

    multiply: float | None = None
    divide: float | None = None
    add: float | None = None
    subtract: float | None = None

    @field_validator("multiply", "divide", "add", "subtract", mode="before")
    @classmethod
    def validate_numeric_fields(cls, v: Any) -> Any:
        """Ensure all numeric fields are valid numbers."""
        if v is not None and not isinstance(v, (int, float)):
            raise ValueError("Filter values must be numeric")
        return v


class Register(BaseModel):
    """Represents a Modbus register configuration."""

    name: str = Field(description="Register name")
    address: int = Field(ge=0, le=65535, description="Register address")
    state_class: Literal["measurement", "total_increasing", "total"] = Field(
        "measurement", description="State class for Home Assistant"
    )
    unit_of_measurement: str | None = Field(None, description="Unit of measurement")
    device_class: str | None = Field(
        None, description="Device class for Home Assistant"
    )
    value_type: ValueType = Field(ValueType.FP32, description="Value type")
    return_type: str = Field(
        "regular", description="Return type for backward compatibility"
    )
    filters: list[Filter] = Field(
        default_factory=list, description="List of filters to apply"
    )
    entity_type: Literal[
        "sensor",
        "text_sensor",
        "binary_sensor",
        "writeable_sensor",
        "writeable_sensor_discrete",
        "writeable_binary_sensor_discrete",
    ] = Field("sensor", description="Entity type")
    write_address: int | None = Field(
        None, ge=0, le=65535, description="Write address for writeable registers"
    )
    write_filters: list[dict[str, Any]] = Field(
        default_factory=list, description="Write filters"
    )
    ha_filter: str = Field("round(2)", description="Home Assistant filter")
    payload_off: str = Field("OFF", description="Payload for OFF state")
    payload_on: str = Field("ON", description="Payload for ON state")
    x_mapping: dict[str, str] = Field(default_factory=dict, description="Value mapping")


class RegistersBase(BaseModel):
    """Represents a base register configuration with a set of registers."""

    base: int = Field(ge=0, le=65535, description="Base address")
    length: int = Field(gt=0, le=1000, description="Length of register block")
    registers: list[Register]
    register_type: RegisterType = RegisterType.HOLDING

    @field_validator("registers")
    @classmethod
    def validate_registers_within_base(cls, v: list[Register], info) -> list[Register]:
        """Validate all register addresses are within the base range."""
        if info.data and "base" in info.data and "length" in info.data:
            base: int = info.data["base"]
            length: int = info.data["length"]
            max_address: int = base + length - 1

            for reg in v:
                if not (base <= reg.address <= max_address):
                    raise ValueError(
                        f"Register '{reg.name}' address {reg.address} is outside base range "
                        f"{base}-{max_address}"
                    )
        return v

    @field_validator("registers")
    @classmethod
    def validate_unique_register_names(cls, v: list[Register]) -> list[Register]:
        """Validate all register names are unique."""
        names: list[str] = [reg.name for reg in v]
        if len(names) != len(set(names)):
            duplicates: list[str] = [name for name in names if names.count(name) > 1]
            raise ValueError(f"Duplicate register names found: {set(duplicates)}")
        return v

    @field_validator("registers")
    @classmethod
    def validate_unique_register_addresses(cls, v: list[Register]) -> list[Register]:
        """Validate all register addresses are unique."""
        addresses: list[int] = [reg.address for reg in v]
        if len(addresses) != len(set(addresses)):
            duplicates: list[int] = [
                addr for addr in addresses if addresses.count(addr) > 1
            ]
            raise ValueError(f"Duplicate register addresses found: {set(duplicates)}")
        return v


class BaudrateConfig(BaseModel):
    """Configuration for setting device baudrate."""

    address: int = Field(9600, ge=0, le=65535, description="Baudrate register address")
    possible_baudrates: dict[str, int] = Field(
        default_factory=dict, description="Mapping of baudrate strings to values"
    )

    @field_validator("possible_baudrates")
    @classmethod
    def validate_baudrates(cls, v: dict[str, int]) -> dict[str, int]:
        """Validate baudrate values are reasonable."""
        for baudrate_str, baudrate_val in v.items():
            if not isinstance(baudrate_val, int) or baudrate_val < 0:
                raise ValueError(f"Invalid baudrate value: {baudrate_val}")
            try:
                # Parse the string to check if it's a valid baudrate
                int(baudrate_str)
            except ValueError:
                raise ValueError(f"Invalid baudrate string: {baudrate_str}")
        return v


class SetBase(BaseModel):
    """Configuration for device setting operations."""

    set_address: int = Field(ge=0, le=65535, description="Address register address")
    set_baudrate: BaudrateConfig = Field(description="Baudrate configuration")


class ModbusDevice(BaseModel):
    """Complete configuration for a Modbus device."""

    model: str = Field(min_length=1, description="Device model name")
    registers_base: list[RegistersBase] = Field(
        min_length=1, description="List of register bases"
    )
    set_base: SetBase | None = Field(None, description="Optional setting configuration")
    additional_sensors: list[AdditionalSensor] = Field(
        default_factory=list, description="Additional sensor configurations"
    )

    @field_validator("registers_base")
    @classmethod
    def validate_no_overlapping_bases(
        cls, v: list[RegistersBase]
    ) -> list[RegistersBase]:
        """Validate register bases don't overlap."""
        bases: list[tuple[int, int, RegistersBase]] = []
        for rb in v:
            start: int = rb.base
            end: int = rb.base + rb.length - 1
            bases.append((start, end, rb))

        # Sort by start address
        bases.sort(key=lambda x: x[0])

        # Check for overlaps
        for i in range(len(bases) - 1):
            current_end: int = bases[i][1]
            next_start: int = bases[i + 1][0]
            if current_end >= next_start:
                raise ValueError(
                    f"Register bases overlap: {bases[i][2].base}-{current_end} "
                    f"and {next_start}-{bases[i + 1][1]}"
                )
        return v


# Registry to store all device configurations
DEVICE_CONFIGS: dict[str, ModbusDevice] = {}
