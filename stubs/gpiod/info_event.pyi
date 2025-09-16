from dataclasses import dataclass
from enum import Enum

from .line_info import LineInfo

__all__ = ["InfoEvent"]

@dataclass(frozen=True, init=False, repr=False)
class InfoEvent:
    class Type(Enum):
        LINE_REQUESTED = "LINE_REQUESTED"
        LINE_RELEASED = "LINE_RELEASED"
        LINE_CONFIG_CHANGED = "LINE_CONFIG_CHANGED"

    event_type: Type
    timestamp_ns: int
    line_info: LineInfo

    def __init__(
        self, event_type: int, timestamp_ns: int, line_info: LineInfo
    ) -> None: ...
