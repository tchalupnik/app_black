from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from boneio.config import BoneIOInput

__all__ = [
    "InputState",
    "InputsResponse",
    "OutputState",
    "CoverDirection",
    "CoverStateState",
    "CoverStateOperation",
    "CoverState",
    "SensorState",
    "HostSensorState",
    "OutputsResponse",
    "CoverResponse",
    "StateUpdate",
]


class InputState(BaseModel):
    """Input state model."""

    name: str
    state: str
    type: str
    pin: str
    timestamp: float
    boneio_input: BoneIOInput | None = None


class InputsResponse(BaseModel):
    """Inputs response model."""

    inputs: list[InputState]


class OutputState(BaseModel):
    """Output state model."""

    id: str
    name: str
    state: str
    type: str
    expander_id: str | None
    pin: int
    timestamp: float | None = None


class CoverDirection(Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"


class CoverStateState(Enum):
    OPEN = "OPEN"
    OPENING = "OPENING"
    CLOSED = "CLOSED"
    CLOSING = "CLOSING"


class CoverStateOperation(Enum):
    """Cover state states."""

    OPENING = "OPENING"
    CLOSING = "CLOSING"
    IDLE = "IDLE"
    STOP = "STOP"


class CoverState(BaseModel):
    """Cover state model."""

    id: str
    name: str
    state: CoverStateState
    position: int
    current_operation: CoverStateOperation
    timestamp: float | None = None
    tilt: int = 0  # Tilt position (0-100)


class SensorState(BaseModel):
    """Sensor state model."""

    id: str
    name: str
    state: float | str | None
    unit: str | None
    timestamp: float | None


class HostSensorState(BaseModel):
    """Host Sensor state model."""

    id: str
    name: str
    state: str
    timestamp: float | None = None


class OutputsResponse(BaseModel):
    """Outputs response model."""

    outputs: list[OutputState]


class CoverResponse(BaseModel):
    """Cover response model."""

    covers: list[CoverState]


class StateUpdate(BaseModel):
    """State update model for WebSocket messages."""

    type: str  # 'input' or 'output' or 'cover'
    data: InputState | OutputState | SensorState | CoverState
