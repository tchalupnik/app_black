"""Tests for validation of Modbus device configurations against Pydantic models."""

from pathlib import Path
from typing import get_args

import pytest

from boneio.config import ModbusModels
from boneio.modbus.models import ModbusDevice


@pytest.fixture(scope="class")
def devices_dir() -> Path:
    """Path to the directory containing device configurations."""
    return Path("modbus_devices").resolve()


@pytest.fixture(scope="class")
def device_config_files(devices_dir: Path) -> list[Path]:
    """List of all device configuration files."""
    return list(devices_dir.glob("*.json"))


@pytest.fixture
def device_config_data(device_config_files: list[Path]) -> dict[str, str]:
    """Dictionary with device configuration JSON strings."""
    configs = {}
    for config_file in device_config_files:
        with config_file.open("r", encoding="utf-8") as f:
            configs[config_file.stem] = f.read()
    return configs


def test_device_config_files_exist(device_config_files: list[Path]) -> None:
    """Test checking if device configuration files exist."""
    assert len(device_config_files) > 0, "No device configuration files found"

    # Check if all files are JSON files
    for config_file in device_config_files:
        assert config_file.suffix == ".json", (
            f"File {config_file.name} is not a JSON file"
        )
        assert config_file.is_file(), (
            f"File {config_file} does not exist or is not a file"
        )


def test_device_config_files_are_valid_json(device_config_data: dict[str, str]) -> None:
    """Test checking if all configuration files are valid JSON."""
    for device_name, json_content in device_config_data.items():
        try:
            ModbusDevice.model_validate_json(json_content)
        except Exception as e:
            # This will catch both JSON decode errors and validation errors
            # We only want to fail here for JSON syntax errors
            if "JSON" in str(type(e).__name__) or "decode" in str(e).lower():
                pytest.fail(f"File {device_name}.json is not valid JSON: {e}")


@pytest.mark.parametrize("device_name", get_args(ModbusModels))
def test_individual_device_config_validation(
    device_config_data: dict[str, str], device_name: str
) -> None:
    """Parametrized test for individual validation of each device."""
    if device_name not in device_config_data:
        pytest.skip(f"Configuration for device {device_name} not found")

    json_content = device_config_data[device_name]

    device = ModbusDevice.model_validate_json(json_content)
    # Additional checks for correctly validated devices
    assert device.model, f"Device {device_name} model cannot be empty"
    assert len(device.registers_base) > 0, (
        f"Device {device_name} must have at least one register base"
    )

    # Check if all registers have unique names
    all_register_names = []
    for base in device.registers_base:
        for register in base.registers:
            all_register_names.append(register.name)

    assert len(all_register_names) == len(set(all_register_names)), (
        f"Device {device_name} has duplicate register names"
    )
