from __future__ import annotations

from .base import BaseSensor


class ModbusNumericSensor(BaseSensor):
    @property
    def state(self) -> float:
        """Give rounded value of temperature."""
        return self.value or 0.0
