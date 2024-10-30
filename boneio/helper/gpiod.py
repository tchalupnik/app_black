from __future__ import annotations
import asyncio
import logging
from boneio.const import PINS
import gpiod
from gpiod.line import Direction, Bias, Edge, Value
from gpiod.line_settings import LineSettings
from datetime import timedelta
_LOGGER = logging.getLogger(__name__)



def _get_device(pin: str):
    pin = PINS.get(pin, "P9_22")
    return f"/dev/gpiochip{pin["chip"]}"

def _configure_line(device, port, **kwargs):
    return gpiod.request_lines(
        device, 
        consumer="gpio", 
        config={port: LineSettings(**kwargs)})

def setup_input(device, line, pull_mode):
    """Set up a GPIO as input."""
    _LOGGER.debug("Requesting input %s:%s", device, line)
    return _configure_line(
        device,
        line, 
        direction=Direction.INPUT,
        bias=(Bias.PULL_UP if pull_mode == "gpio_pu" else Bias.PULL_DOWN))

def enable_edge_detect(req, detect_edges, debounce_ms):
    """Add detection for RISING and FALLING events."""
    _LOGGER.debug("Detecting %s edges on %s:%s", detect_edges, req.chip_name, req.lines)
    req.reconfigure_lines(
        {port: LineSettings(edge_detection=getattr(Edge, detect_edges),
                            debounce_period=timedelta(milliseconds=debounce_ms))
         for port in req.lines})

class GpioD:

    def __init__(self, pin: str, pull_mode: str = "gpio"):
        self._pin = pin
        self._gpiod_pin = PINS.get(pin, {"chip": 0, "line": 2})
        self._chip = self._gpiod_pin["chip"]
        self._line = self._gpiod_pin["line"]
        self._device = _get_device(self._pin)
        self._line = setup_input(self._device, self._line, pull_mode)

    def edge_detect(self, callback, bounce=0, edge=Edge.RISING):
        enable_edge_detect(self._line, edge=Edge.BOTH, debounce_ms=bounce)

    

    

