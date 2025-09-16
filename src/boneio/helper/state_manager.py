"""State files manager."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)


class StateManager:
    """StateManager to load and save states to file."""

    def __init__(self, state_file_path: Path) -> None:
        """Initialize disk StateManager."""
        self._loop = asyncio.get_event_loop()
        self._lock = asyncio.Lock()
        self._file_path = state_file_path
        self.state = self.load_states()
        _LOGGER.info("Loaded state file from %s", str(self._file_path))
        self._file_uptodate = False
        self._save_attributes_callback = None

    def load_states(self) -> dict:
        """Load state file."""
        try:
            with self._file_path.open() as state_file:
                datastore = json.load(state_file)
                return datastore
        except FileNotFoundError:
            pass
        return {}

    def del_attribute(self, attr_type: str, attribute: str) -> None:
        """Delete attribute"""
        if attr_type in self.state and attribute in self.state[attr_type]:
            del self.state[attr_type][attribute]

    def save_attribute(self, attr_type: str, attribute: str, value: str) -> None:
        """Save single attribute to file."""
        if attr_type not in self.state:
            self.state[attr_type] = {}
        self.state[attr_type][attribute] = value
        if self._save_attributes_callback is not None:
            self._save_attributes_callback.cancel()
            self._save_attributes_callback = None
        self._save_attributes_callback = self._loop.call_later(
            1, lambda: self._loop.create_task(self.save_state())
        )

    def get(self, attr_type: str, attr: str, default_value: Any = None) -> Any:
        """Retrieve attribute from json."""
        attrs = self.state.get(attr_type)
        if attrs:
            return attrs.get(attr, default_value)
        return default_value

    def _save_state(self) -> None:
        with Path(self._file_path).open("w+", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2)

    async def save_state(self) -> None:
        """Async save state."""
        if self._lock.locked():
            # Let's not save state if something happens same time.
            return
        async with self._lock:
            await self._loop.run_in_executor(None, self._save_state)
