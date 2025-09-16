from dataclasses import dataclass
from datetime import timedelta

from .line import Bias, Clock, Direction, Drive, Edge

__all__ = ["LineInfo"]

@dataclass(frozen=True, init=False, repr=False)
class LineInfo:
    offset: int
    name: str
    used: bool
    consumer: str
    direction: Direction
    active_low: bool
    bias: Bias
    drive: Drive
    edge_detection: Edge
    event_clock: Clock
    debounced: bool
    debounce_period: timedelta

    def __init__(
        self,
        offset: int,
        name: str,
        used: bool,
        consumer: str,
        direction: int,
        active_low: bool,
        bias: int,
        drive: int,
        edge_detection: int,
        event_clock: int,
        debounced: bool,
        debounce_period_us: int,
    ) -> None: ...
