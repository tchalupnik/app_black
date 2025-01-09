from __future__ import annotations

import asyncio
import logging
import os
import secrets
from pathlib import Path

import uvicorn

from boneio.helper.logger import configure_uvicorn_logging
from boneio.manager import Manager
from boneio.webui.app import BoneIOApp, init_app

_LOGGER = logging.getLogger(__name__)

class WebServer:
    def __init__(self, config_file: str, manager: Manager, port: int = 8080, auth: dict = {}, logger: dict = {}, debug_level: int = 0) -> None:
        """Initialize the web server."""
        self.config_file = config_file
        self.manager = manager
        self._shutdown_event = asyncio.Event()
        
        # Get yaml config file path
        self._yaml_config_file = os.path.abspath(os.path.join(os.path.split(self.config_file)[0], "config.yaml"))
        
        # Set up JWT secret
        self.jwt_secret = self._get_jwt_secret_or_generate()
        
        
        # Initialize FastAPI app
        self.app: BoneIOApp = init_app(
            manager=self.manager, 
            yaml_config_file=self._yaml_config_file, 
            auth_config=auth, 
            jwt_secret=self.jwt_secret,
            web_server=self
        )
        
        # Configure uvicorn with shared logging config
        self._uvicorn_config = uvicorn.Config(
            app=self.app,
            host="0.0.0.0",
            port=port,
            log_config=configure_uvicorn_logging(
                debug_level=debug_level,
                log_config=logger,
            ),
            lifespan="on",
        )
        self._server = uvicorn.Server(self._uvicorn_config)
        # Override the server's install_signal_handlers to prevent it from handling signals
        self._server.install_signal_handlers = lambda: None
        self._server_running = False
        # self.manager.event_bus.add_sigterm_listener(self.stop_webserver)

    def _get_jwt_secret_or_generate(self):
        config_dir = Path(self._yaml_config_file).parent
        jwt_secret_file = config_dir / "jwt_secret"
        
        try:
            if jwt_secret_file.exists():
                # Read existing secret
                with open(jwt_secret_file, 'r') as f:
                    jwt_secret = f.read().strip()
                    if jwt_secret:  # Verify it's not empty
                        return jwt_secret
            
            # Generate new secret if file doesn't exist or is empty
            jwt_secret = secrets.token_hex(32)  # 256-bit random secret
            
            # Save the secret
            with open(jwt_secret_file, 'w') as f:
                f.write(jwt_secret)
            
            # Secure the file permissions (read/write only for owner)
            os.chmod(jwt_secret_file, 0o600)
            
        except Exception as e:
            # If we can't persist the secret, generate a temporary one
            _LOGGER.error(f"Failed to handle JWT secret file: {e}")
            jwt_secret = secrets.token_hex(32)
        return jwt_secret

    async def start_webserver2(self) -> None:
        """Start the web server."""
        _LOGGER.info("Starting UVICORN web server...")
        self._server_running = True
        await self._server.serve()

    async def start_webserver(self) -> None:
        """Start the web server."""
        _LOGGER.info("Starting UVICORN web server...")
        self._server_running = True
        
        shutdown_task = asyncio.create_task(self._wait_shutdown())
        server_task = asyncio.create_task(self._server.serve())
        
        await asyncio.wait(
            [shutdown_task, server_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        if not server_task.done():
            server_task.cancel()
            await server_task

    async def _wait_shutdown(self):
        self._server.should_exit = True
        await self._shutdown_event.wait()
        _LOGGER.info("Shutdown signal received")

    async def stop_webserver(self) -> None:
        """Stop the web server."""
        if not self._server_running:
            return
        _LOGGER.info("Shutting down UVICORN web server...")
        self._server_running = False
        self._shutdown_event.set()

    async def stop_webserver2(self) -> None:
        """Stop the web server."""
        _LOGGER.info("Shutting down UVICORN web server...")
        self._server_running = False
        # await self.app.shutdown_handler()
        self._server.should_exit = True