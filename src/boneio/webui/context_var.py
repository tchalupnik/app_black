from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from boneio.config import Config
from boneio.manager import Manager
from boneio.webui.websocket_manager import WebSocketManager


@dataclass
class State:
    manager: Manager
    config: Config
    yaml_config_file: Path
    websocket_manager: WebSocketManager
    jwt_secret: str


state_var: ContextVar[State] = ContextVar("State")
