from collections.abc import Iterable

from . import (
    chip,
    chip_info,
    edge_event,
    exception,
    info_event,
    line,
    line_info,
    line_request,
    line_settings,
)
from .chip import Chip
from .chip_info import ChipInfo
from .edge_event import EdgeEvent
from .exception import ChipClosedError, RequestReleasedError
from .info_event import InfoEvent
from .line import Bias, Clock, Direction, Drive, Edge, Value
from .line_info import LineInfo
from .line_request import LineRequest
from .line_settings import LineSettings

# public submodules
__all__ = [
    "chip",
    "chip_info",
    "edge_event",
    "exception",
    "info_event",
    "line",
    "line_info",
    "line_request",
    "line_settings",
    "Chip",
    "ChipClosedError",
    "ChipInfo",
    "RequestReleasedError",
    "InfoEvent",
    "LineInfo",
    "EdgeEvent",
    "LineRequest",
    "LineSettings",
    "Bias",
    "Clock",
    "Direction",
    "Drive",
    "Edge",
    "Value",
    "is_gpiochip_device",
    "request_lines",
]

def is_gpiochip_device(path: str) -> bool: ...
def request_lines(
    path: str,
    config: dict[Iterable[int | str] | int | str, LineSettings | None],
    consumer: str | None = None,
    event_buffer_size: int | None = None,
    output_values: dict[int | str, line.Value] | None = None,
) -> LineRequest: ...
