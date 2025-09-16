from enum import Enum

__all__ = ["EdgeEvent"]

class EdgeEvent:
    class Type(Enum):
        RISING_EDGE = "RISING_EDGE"
        FALLING_EDGE = "FALLING_EDGE"

    event_type: Type
    timestamp_ns: int
    line_offset: int
    global_seqno: int
    line_seqno: int

    def __init__(
        self,
        event_type: int,
        timestamp_ns: int,
        line_offset: int,
        global_seqno: int,
        line_seqno: int,
    ) -> None: ...
