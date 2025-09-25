from __future__ import annotations

import asyncio
import logging
import secrets
from pathlib import Path

from anyio import Event, move_on_after, sleep
from hypercorn.asyncio import serve
from hypercorn.config import Config as HypercornConfig

from boneio.config import Config
from boneio.manager import Manager
from boneio.webui.app import BoneIOApp, init_app

_LOGGER = logging.getLogger(__name__)


class WebServer:
    def __init__(
        self,
        config: Config,
        config_file_path: Path,
        manager: Manager,
    ) -> None:
        """Initialize the web server."""
        self.config = config
        assert self.config.web is not None, "Web config must be provided"
        self.manager = manager
        self._shutdown_event = asyncio.Event()

        # Get yaml config file path
        self._yaml_config_file_path = config_file_path

        # Set up JWT secret
        self.jwt_secret = self._get_jwt_secret_or_generate()

        # Initialize FastAPI app
        self.app: BoneIOApp = init_app(
            manager=self.manager,
            yaml_config_file=self._yaml_config_file_path,
            jwt_secret=self.jwt_secret,
            config=self.config,
            web_server=self,
        )

        # Configure hypercorn with shared logging config
        self._hypercorn_config = HypercornConfig()
        self._hypercorn_config.bind = [f"0.0.0.0:{self.config.web.port}"]
        self._hypercorn_config.use_reloader = False
        self._hypercorn_config.worker_class = "asyncio"

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
        # self._server = hypercorn.asyncio.serve(self.app, self._hypercorn_config)
        # Override the server's install_signal_handlers to prevent it from handling signals
        # self._server.install_signal_handlers = lambda: None
        # self.manager.event_bus.add_sigterm_listener(self.stop_webserver)

    def _get_jwt_secret_or_generate(self):
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

        webserver_task = asyncio.create_task(run())
        try:
            while not webserver_task.done():
                await sleep(1)

            webserver_exception = webserver_task.exception()
            if webserver_exception is not None:
                raise webserver_exception
        finally:
            if not webserver_task.done():
                with move_on_after(1, shield=True):
                    webserver_task.cancel()
                    try:
                        await webserver_task
                    except asyncio.CancelledError:
                        pass
