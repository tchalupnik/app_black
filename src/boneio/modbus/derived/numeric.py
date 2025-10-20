from __future__ import annotations

import logging
from dataclasses import dataclass

from boneio.config import ModbusDeviceData
from boneio.modbus.sensor.base import BaseSensor

_LOGGER = logging.getLogger(__name__)


@dataclass(kw_only=True)
class ModbusDerivedNumericSensor(BaseSensor):
    formula: str
    context_config: ModbusDeviceData
    decoded_name: str

    def evaluate_state(
        self, source_sensor_value: int | float, timestamp: float
    ) -> None:
        code = compile(self.formula, "<string>", "eval")
        context: dict[str, str | float | int] = {
            "X": source_sensor_value,
            **self.context_config,
        }
        value = eval(code, {"__builtins__": {}}, context)
        self.set_state(value, timestamp)
