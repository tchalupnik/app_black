from dataclasses import dataclass
from datetime import timedelta

from .line import Bias, Clock, Direction, Drive, Edge, Value

__all__ = ["LineSettings"]

@dataclass(repr=False)
class LineSettings:
    direction: Direction = Direction.AS_IS
    edge_detection: Edge = Edge.NONE
    bias: Bias = Bias.AS_IS
    drive: Drive = Drive.PUSH_PULL
    active_low: bool = False
    debounce_period: timedelta = timedelta()
    event_clock: Clock = Clock.MONOTONIC
    output_value: Value = Value.INACTIVE
