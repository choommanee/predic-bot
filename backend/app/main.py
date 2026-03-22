"""
FastAPI application entry point.
- Serves React frontend as static files
- Mounts API routers
- Starts/stops TradingEngine on startup/shutdown
- WebSocket endpoint for real-time data
"""
from __future__ import annotations
import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .config import get_settings
from .database import init_db
from .core.engine import TradingEngine
from .api.auth import router as auth_router
from .api.trading import router as trading_router
from .api.signals import router as signals_router
from .api.websocket import manager
from .notifications.telegram import TelegramNotifier

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(
    title="predic-bot",
    description="Crypto trading bot — Binance Futures, SMC Analysis, Railway deployment",
    version="1.0.0",
)

# CORS (allow React dev server during development)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global engine instance (accessed by routers via app state)
engine: TradingEngine | None = None
telegram: TelegramNotifier | None = None


# ─────────────────── Lifecycle ───────────────────

@app.on_event("startup")
async def on_startup():
    global engine, telegram

    await init_db()
    logger.info("Database initialized")

    telegram = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)

    engine = TradingEngine()

    # Wire broadcast: WebSocket + Telegram
    async def broadcast_to_ws(event: dict):
        await manager.broadcast(event)

    async def broadcast_to_telegram(event: dict):
        if event.get("signals"):
            await telegram.send_signal(event)
        if event.get("type") == "risk_alert":
            await telegram.send_risk_alert(event.get("message", ""))

    engine.add_broadcast_callback(broadcast_to_ws)
    engine.add_broadcast_callback(broadcast_to_telegram)

    await engine.start()
    logger.info("TradingEngine started")


@app.on_event("shutdown")
async def on_shutdown():
    global engine, telegram
    if engine:
        await engine.stop()
    if telegram:
        await telegram.close()


# ─────────────────── API Routers ───────────────────

app.include_router(auth_router)
app.include_router(trading_router)
app.include_router(signals_router)


# ─────────────────── WebSocket ───────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        # Send current status immediately on connect
        if engine:
            await ws.send_json({"type": "status", **engine.get_status()})
        while True:
            # Keep connection alive; clients send pings
            data = await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)


# ─────────────────── Health check ───────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "mode": settings.trading_mode}


# ─────────────────── Serve React frontend ───────────────────

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        index = static_dir / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return {"error": "Frontend not built. Run: cd frontend && npm run build"}
