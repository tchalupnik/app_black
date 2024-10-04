"""GpioInputBinarySensorNew to receive signals."""

import logging
from boneio.const import PRESSED, RELEASED, BOTH
from boneio.helper import GpioBaseClass
import time
from boneio.helper.gpio import add_event_callback, add_event_detect

_LOGGER = logging.getLogger(__name__)

soc
class GpioInputBinarySensorNew(GpioBaseClass):
    """Represent Gpio sensor on input boards."""

    def __init__(self, **kwargs) -> None:
        """Setup GPIO Input Button"""
        super().__init__(**kwargs)
        self._state = self.is_pressed
        self.button_pressed_time = 0.0
        self._click_type = (
            (RELEASED, PRESSED)
            if kwargs.get("inverted", False)
            else (PRESSED, RELEASED)
        )
        self._initial_send = kwargs.get("initial_send", False)
        _LOGGER.debug("Configured sensor pin %s", self._pin)
        add_event_detect(pin=self._pin, edge=BOTH)
        add_event_callback(pin=self._pin, callback=self.check_state)
        self._loop.call_soon_threadsafe(self.check_state, self._initial_send)

    def check_state(self, initial_send: bool = False) -> None:
        """Check if state has changed."""
        time_now = time.time()
        state = self.is_pressed
        if (time_now - self.button_pressed_time <= self._bounce_time) or (
            not initial_send and state == self._state
        ):
            return
        self._state = state
        click_type = self._click_type[0] if state else self._click_type[1]
        _LOGGER.debug(
            "Binary sensor: %s event on pin %s - %s",
            click_type,
            self._pin,
            self.name,
        )
        self.press_callback(click_type=click_type, duration=None)
