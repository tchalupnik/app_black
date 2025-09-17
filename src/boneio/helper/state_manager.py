"""State files manager."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from pydantic import BaseModel, Field

_LOGGER = logging.getLogger(__name__)


class CoverStateEntry(BaseModel):
    position: float
    tilt: float | None = None


class State(BaseModel):
    relay: dict[str, bool] = Field(default_factory=dict)
    cover: dict[str, CoverStateEntry] = Field(default_factory=dict)


class StateManager:
    """StateManager to load and save states to file."""

    def __init__(self, state_file_path: Path) -> None:
        """Initialize disk StateManager."""
        self._loop = asyncio.get_event_loop()
        self._lock = asyncio.Lock()
        self._file_path = state_file_path
        self.state: State = self._load_states()
        _LOGGER.info("Loaded state file from %s", str(self._file_path))
        self._save_attributes_callback = None

    def _load_states(self) -> State:
        """Load state file."""
        try:
            text = self._file_path.read_text()
        except FileNotFoundError:
            return State()
        return State.model_validate_json(text)

    def remove_relay_from_state(self, relay_id: str) -> None:
        """Delete attribute"""
        if relay_id in self.state.relay:
            del self.state.relay[relay_id]

    def save(self) -> None:
        """Save single attribute to file."""
        if self._save_attributes_callback is not None:
            self._save_attributes_callback.cancel()
            self._save_attributes_callback = None
        self._save_attributes_callback = self._loop.call_later(
            1, lambda: self._loop.create_task(self._save_state())
        )

    def _save_to_file(self) -> None:
        with Path(self._file_path).open("w+") as f:
            f.write(self.state.model_dump_json())

    async def _save_state(self) -> None:
        """Async save state."""
        if self._lock.locked():
            # Let's not save state if something happens same time.
            return
        async with self._lock:
            await self._loop.run_in_executor(None, self._save_to_file)
