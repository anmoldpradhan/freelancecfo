from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio

from app.api.v1.auth import router as auth_router
from app.api.v1.transaction import router as transactions_router
from app.api.v1.invoices import router as invoices_router
from app.api.v1.stripe_webhooks import router as stripe_router
from app.core.websocket_manager import ws_manager
from app.core.security import decode_token
from jose import JWTError


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs on startup: launches the Redis pub/sub listener as a background task.
    asynccontextmanager replaces the old @app.on_event("startup") pattern.
    """
    task = asyncio.create_task(ws_manager.broadcast_from_redis())
    yield
    task.cancel()


app = FastAPI(
    title="FreelanceCFO API",
    description="AI-powered financial management for freelancers",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(transactions_router)
app.include_router(invoices_router)
app.include_router(stripe_router)


@app.get("/health", tags=["system"])
async def health_check():
    return {"status": "ok", "service": "freelancecfo-api"}


@app.websocket("/ws/payments")
async def websocket_payments(websocket: WebSocket, token: str = ""):
    """
    WebSocket endpoint for real-time payment notifications.
    Client connects with: ws://localhost:8000/ws/payments?token=<access_token>
    Token is passed as query param because browsers can't set headers on WebSocket.
    """
    # Validate JWT before accepting connection
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            await websocket.close(code=4001)
            return
        user_id = payload.get("sub")
        if not user_id:
            await websocket.close(code=4001)
            return
    except JWTError:
        await websocket.close(code=4001)
        return

    await ws_manager.connect(websocket, user_id)

    try:
        # Keep connection alive — wait for client to disconnect
        while True:
            # Receive any client messages (ping/pong keepalive)
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, user_id)