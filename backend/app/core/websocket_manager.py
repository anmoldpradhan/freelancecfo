"""
Manages active WebSocket connections per user.
Uses Redis pub/sub so it works across multiple app instances.

Flow:
  1. Browser connects to /ws/payments?token=<jwt>
  2. Manager registers connection under user_id
  3. Webhook handler publishes event to Redis channel
  4. Manager receives from Redis → forwards to browser WebSocket
"""
import json
import logging
import asyncio
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    def __init__(self):
        # user_id → list of active WebSocket connections
        # (a user might have multiple browser tabs open)
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        if user_id not in self._connections:
            self._connections[user_id] = []
        self._connections[user_id].append(websocket)
        logger.info("WebSocket connected | user=%s total=%d",
                    user_id, len(self._connections[user_id]))

    def disconnect(self, websocket: WebSocket, user_id: str):
        if user_id in self._connections:
            self._connections[user_id].discard(websocket) \
                if hasattr(self._connections[user_id], 'discard') \
                else self._connections[user_id].remove(websocket)
            if not self._connections[user_id]:
                del self._connections[user_id]
        logger.info("WebSocket disconnected | user=%s", user_id)

    async def send_to_user(self, user_id: str, message: dict):
        """Sends a JSON message to all active connections for a user."""
        connections = self._connections.get(user_id, [])
        dead = []
        for ws in connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        # Clean up dead connections
        for ws in dead:
            self._connections[user_id].remove(ws)

    async def broadcast_from_redis(self):
        """
        Subscribes to Redis 'payments' channel.
        Runs forever — started as a background task on app startup.
        Forwards any published message to the correct user's WebSocket.
        """
        import redis.asyncio as aioredis
        from app.core.config import settings

        redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        pubsub = redis.pubsub()
        await pubsub.subscribe("payments")

        logger.info("Redis pub/sub listener started on 'payments' channel")

        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            try:
                data = json.loads(message["data"])
                user_id = data.get("user_id")
                if user_id:
                    await self.send_to_user(user_id, data)
            except Exception as e:
                logger.error("Redis pub/sub error: %s", e)


# Single instance shared across the app
ws_manager = WebSocketManager()