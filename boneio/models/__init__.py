from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel


class InputState(BaseModel):
    """Input state model."""
    name: str
    state: str
    type: str
    pin: str
    timestamp: float
    boneio_input: str

class InputsResponse(BaseModel):
    """Inputs response model."""
    inputs: List[InputState]

class OutputState(BaseModel):
    """Output state model."""
    id: str
    name: str
    state: str
    type: str
    expander_id: Union[str, None]
    pin: int
    timestamp: Union[float, None] = None

class SensorState(BaseModel):
    """Sensor state model."""
    id: str
    name: str
    state: Union[float, None]
    unit: Union[str, None]
    timestamp: Union[float, None]

class HostSensorState(BaseModel):
    """Host Sensor state model."""
    id: str
    name: str
    state: str
    timestamp: Optional[float] = None

class OutputsResponse(BaseModel):
    """Outputs response model."""
    outputs: List[OutputState]

class StateUpdate(BaseModel):
    """State update model for WebSocket messages."""
    type: str  # 'input' or 'output'
    data: Union[InputState, OutputState, SensorState]
