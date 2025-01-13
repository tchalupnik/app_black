import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, List

from jose import jwt
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from boneio.models import InputState, OutputState, SensorState, StateUpdate

_LOGGER = logging.getLogger(__name__)

# JWT settings
JWT_ALGORITHM = "HS256"

class WebSocketDisconnectWithMessage(WebSocketDisconnect):
    def __init__(self, message):
        super().__init__()
        self.message = message

class WebSocketManager:
    def __init__(self, jwt_secret: str = None, auth_required: bool = False):
        self.active_connections: List[WebSocket] = []
        self._lock = asyncio.Lock()
        self._closing = False
        self._cleanup_tasks: List[asyncio.Task] = []
        self._jwt_secret = jwt_secret
        self._auth_required = auth_required

    async def _verify_token(self, websocket: WebSocket) -> bool:
        """Verify WebSocket token."""
        try:
            _LOGGER.debug("Verifying WebSocket token...")
            # Get token from Sec-WebSocket-Protocol header
            protocols = websocket.headers.get("sec-websocket-protocol", "").split(", ")
            token = None
            for protocol in protocols:
                if protocol.startswith("token."):
                    token = protocol[6:]  # Remove "token." prefix
                    break
            
            if not token:
                _LOGGER.debug("No authentication token provided")
                return False

            # Verify the JWT token
            try:
                payload = jwt.decode(token, self._jwt_secret, algorithms=[JWT_ALGORITHM])
                # Check if token has expired
                exp = payload.get("exp")
                if not exp or datetime.fromtimestamp(exp, tz=timezone.utc) < datetime.now(timezone.utc):
                    _LOGGER.debug("Token has expired")
                    return False
                
                _LOGGER.debug("WebSocket token verified successfully")
                return True
                
            except jwt.JWTError:
                _LOGGER.debug("Invalid token")
                return False
        except Exception as e:
            _LOGGER.error(f"WebSocket authentication error: {e}")
            return False

    async def connect(self, websocket: WebSocket) -> bool:
        """Handle WebSocket connection with authentication."""
        if self._closing:
            return False

        try:
            if self._auth_required:
                if not await self._verify_token(websocket):
                    await websocket.close(code=4001, reason="Authentication failed")
                    return False
                await websocket.accept(subprotocol=websocket.headers.get("sec-websocket-protocol"))
            else:
                await websocket.accept()

            async with self._lock:
                self.active_connections.append(websocket)
                _LOGGER.debug("WebSocket connection accepted and added to active connections")
            return True

        except Exception as e:
            _LOGGER.error(f"Failed to establish WebSocket connection: {e}")
            try:
                await websocket.close(code=4000, reason="Connection failed")
            except Exception:
                pass
            return False

    async def disconnect(self, websocket: WebSocket):
        """Remove a websocket from active connections and close it gracefully."""
        try:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
                if websocket.application_state == WebSocketState.CONNECTED:
                    try:
                        await websocket.close(code=1000)
                    except Exception as e:
                        _LOGGER.error(f"Error closing WebSocket: {e}")
        except ValueError:
            pass
        except Exception as e:
            _LOGGER.error(f"Error during WebSocket disconnect: {e}")

    async def close_all(self):
        """Close all active connections."""
        if self._closing:
            return

        self._closing = True
        _LOGGER.info("Closing all WebSocket connections...")

        for websocket in list(self.active_connections):
            try:
                await self.disconnect(websocket)
            except Exception:
                pass
        

    async def broadcast_state(self, state_type: str, data: Any):
        if self._closing:
            return

        dead_connections = []
        async with self._lock:
            for connection in self.active_connections[:]:
                try:
                    if isinstance(data, (InputState, OutputState, SensorState)):
                        update = StateUpdate(type=state_type, data=data)
                        await connection.send_json(update.dict())
                except WebSocketDisconnect:
                    dead_connections.append(connection)
                except Exception as e:
                    _LOGGER.error(f"Error sending message to WebSocket: {e}")
                    dead_connections.append(connection)

            # Clean up dead connections
            for dead in dead_connections:
                if dead in self.active_connections:
                    await self.disconnect(dead)