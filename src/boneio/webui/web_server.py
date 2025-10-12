from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from pathlib import Path

import anyio
from anyio import Event
from hypercorn.asyncio import serve
from hypercorn.config import Config as HypercornConfig

from boneio.config import Config
from boneio.manager import Manager

from .app import init_app
from .context_var import State, state_var
from .websocket_manager import WebSocketManager

_LOGGER = logging.getLogger(__name__)


@dataclass
class WebServer:
    config: Config
    config_file_path: Path
    manager: Manager

    def __post_init__(self) -> None:
        """Initialize the web server."""
        assert self.config.web is not None, "Web config must be provided"

        # Get yaml config file path
        self._yaml_config_file_path = self.config_file_path

        # Set up JWT secret
        jwt_secret = self._get_jwt_secret_or_generate()

        websocket_manager = WebSocketManager(
            jwt_secret=jwt_secret, auth_required=self.config.web.is_auth_required()
        )

        state_var.set(
            State(
                manager=self.manager,
                config=self.config,
                yaml_config_file=self._yaml_config_file_path,
                websocket_manager=websocket_manager,
                jwt_secret=jwt_secret,
            )
        )

        # Initialize FastAPI app
        self.app = init_app(config=self.config)

        # Configure hypercorn with shared logging config
        self._hypercorn_config = HypercornConfig()
        self._hypercorn_config.bind = [f"0.0.0.0:{self.config.web.port}"]
        self._hypercorn_config.use_reloader = False

        # Configure Hypercorn's logging
        hypercorn_logger = logging.getLogger("hypercorn.error")
        hypercorn_logger.handlers = []  # Remove default handlers
        hypercorn_logger.propagate = True  # Use root logger's handlers

        # Configure access log
        hypercorn_access_logger = logging.getLogger("hypercorn.access")
        hypercorn_access_logger.handlers = []  # Remove default handlers
        hypercorn_access_logger.propagate = True  # Use root logger's handlers

        self._hypercorn_config.accesslog = hypercorn_access_logger
        self._hypercorn_config.errorlog = hypercorn_logger

        self._hypercorn_config.graceful_timeout = 5.0

    def _get_jwt_secret_or_generate(self) -> str:
        config_dir = Path(self._yaml_config_file_path).parent
        jwt_secret_file = config_dir / "jwt_secret"

        try:
            if jwt_secret_file.exists():
                # Read existing secret
                with Path.open(jwt_secret_file, "r") as f:
                    jwt_secret = f.read().strip()
                    if jwt_secret:  # Verify it's not empty
                        return jwt_secret

            # Generate new secret if file doesn't exist or is empty
            jwt_secret = secrets.token_hex(32)  # 256-bit random secret

            # Save the secret
            with Path.open(jwt_secret_file, "w") as f:
                f.write(jwt_secret)

            # Secure the file permissions (read/write only for owner)
            Path.chmod(jwt_secret_file, 0o600)

        except Exception as e:
            # If we can't persist the secret, generate a temporary one
            _LOGGER.error("Failed to handle JWT secret file: %s", e)
            jwt_secret = secrets.token_hex(32)
        return jwt_secret

    async def start_webserver(self) -> None:
        """Start the web server."""
        _LOGGER.info("Starting HYPERCORN web server...")

        async def run() -> None:
            try:
                await serve(
                    self.app,
                    self._hypercorn_config,
                    shutdown_trigger=Event().wait,
                )
            finally:
                _LOGGER.info("HTTP server stopped")

        async with anyio.create_task_group() as tg:
            tg.start_soon(run)
            await anyio.sleep_forever()
