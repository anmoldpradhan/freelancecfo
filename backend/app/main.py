from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio

from app.api.v1.auth import router as auth_router
from app.api.v1.transaction import router as transactions_router
from app.api.v1.invoices import router as invoices_router
from app.api.v1.stripe_webhooks import router as stripe_router
from app.core.websocket_manager import ws_manager
from app.api.v1.tax import router as tax_router
from app.api.v1.profile import router as profile_router
from app.core.security import decode_token
from jose import JWTError
from app.api.v1.cfo import router as cfo_router
from app.core.config import settings

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
    allow_origins=[settings.frontend_url, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(transactions_router)
app.include_router(invoices_router)
app.include_router(stripe_router)
app.include_router(cfo_router)
app.include_router(tax_router)
app.include_router(profile_router)

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

@app.websocket("/ws/cfo/chat")
async def websocket_cfo_chat(websocket: WebSocket, token: str = ""):
    """
    Streaming CFO chat via WebSocket.

    Protocol:
      Client sends: {"message": "...", "conversation_id": "..."|null}
      Server streams: {"type": "chunk", "content": "..."}  (multiple)
      Server sends:   {"type": "done", "conversation_id": "..."}
      On error:       {"type": "error", "message": "..."}
    """
    # Auth
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            await websocket.close(code=4001)
            return
        user_id = payload.get("sub")
    except JWTError:
        await websocket.close(code=4001)
        return

    await websocket.accept()

    # Get DB session and user
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import select
    from app.models.user import User
    from app.api.v1.cfo import _get_or_create_conversation, _save_messages
    from app.services.ai_cfo import chat_streaming
    from app.services.context_injector import build_financial_context

    try:
        while True:
            # Wait for message from client
            data = await websocket.receive_json()
            user_message = data.get("message", "").strip()
            conversation_id = data.get("conversation_id")

            if not user_message:
                await websocket.send_json(
                    {"type": "error", "message": "Empty message"}
                )
                continue

            async with AsyncSessionLocal() as db:
                # Fetch user
                result = await db.execute(
                    select(User).where(User.id == user_id)
                )
                user = result.scalar_one_or_none()
                if not user:
                    await websocket.send_json(
                        {"type": "error", "message": "User not found"}
                    )
                    break

                schema = user.tenant_schema

                conv_id, history = await _get_or_create_conversation(
                    schema, conversation_id, db
                )
                financial_context = await build_financial_context(schema, db)

                # Stream response chunks to client
                full_response = []
                async for chunk in chat_streaming(
                    user_message=user_message,
                    financial_context=financial_context,
                    conversation_history=history,
                ):
                    await websocket.send_json(
                        {"type": "chunk", "content": chunk}
                    )
                    full_response.append(chunk)

                complete_response = "".join(full_response)

                # Save complete conversation to DB
                await _save_messages(
                    schema, conv_id,
                    user_message, complete_response, db
                )

                await websocket.send_json(
                    {"type": "done", "conversation_id": conv_id}
                )

    except WebSocketDisconnect:
        logger.info("CFO WebSocket disconnected | user=%s", user_id)
    except Exception as e:
        logger.error("CFO WebSocket error: %s", e)
        try:
            await websocket.send_json(
                {"type": "error", "message": "Internal error"}
            )
        except Exception:
            pass