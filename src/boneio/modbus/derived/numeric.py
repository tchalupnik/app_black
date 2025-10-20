from __future__ import annotations

from dataclasses import dataclass

from boneio.config import ModbusDeviceData
from boneio.modbus.sensor import BaseSensor


@dataclass(kw_only=True)
class ModbusDerivedNumericSensor(BaseSensor):
    formula: str
    context_config: ModbusDeviceData
    decoded_name: str

    def evaluate_state(
        self, source_sensor_value: str | float | None, timestamp: float
    ) -> None:
        code = compile(self.formula, "<string>", "eval")
        context: dict[str, str | float | None] = {
            "X": source_sensor_value,
            **self.context_config,
        }
        value = eval(code, {"__builtins__": {}}, context)
        self.set_state(value, timestamp)
