"""State files manager."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

import anyio
import anyio.abc
from pydantic import BaseModel, Field

_LOGGER = logging.getLogger(__name__)


class CoverStateEntry(BaseModel):
    position: int
    tilt: int | None = None


class State(BaseModel):
    relay: dict[str, bool] = Field(default_factory=dict)
    cover: dict[str, CoverStateEntry] = Field(default_factory=dict)


@dataclass
class StateManager:
    """StateManager to load and save states to file."""

    state_file_path: Path
    state: State
    tg: anyio.abc.TaskGroup
    lock: anyio.Lock = field(default_factory=anyio.Lock)

    @classmethod
    @asynccontextmanager
    async def create(cls, state_file_path: Path) -> AsyncGenerator[StateManager]:
        async with anyio.create_task_group() as tg:
            try:
                with state_file_path.open("r") as f:
                    text = f.read()
            except FileNotFoundError:
                _LOGGER.warning("State file not found, creating new one.")
                state = State()
            else:
                _LOGGER.warning("State file found, loading state.")
                state = State.model_validate_json(text)
            try:
                yield cls(state_file_path, state, tg)
            except BaseException:
                tg.cancel_scope.cancel()
                raise

    def remove_relay_from_state(self, relay_id: str) -> None:
        """Delete attribute"""
        if relay_id in self.state.relay:
            del self.state.relay[relay_id]

    def save(self) -> None:
        """Save single attribute to file."""
        self.tg.start_soon(self._save_state)

    async def _save_state(self) -> None:
        """Async save state."""
        if self.lock.locked():
            # Let's not save state if something happens same time.
            _LOGGER.info("State file is locked, skipping save.")
            return
        async with self.lock:
            with Path(self.state_file_path).open("w+") as f:
                f.write(self.state.model_dump_json())
