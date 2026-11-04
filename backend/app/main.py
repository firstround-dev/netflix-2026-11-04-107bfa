"""ASGI entrypoint: `uvicorn app.main:app`. Configuration comes from environment variables."""

from __future__ import annotations

import os
from pathlib import Path

from app.api import create_app
from app.translator import build_translator

BACKEND_DIR = Path(__file__).resolve().parent.parent

app = create_app(
    db_path=Path(os.environ.get("TLD_DB_PATH", BACKEND_DIR / "data" / "trivia.db")),
    translator=build_translator(os.environ.get("TLD_TRANSLATOR", "pseudo")),
    cors_origins=os.environ.get("TLD_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","),
    frontend_dist=BACKEND_DIR.parent / "frontend" / "dist",
)
