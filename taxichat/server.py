"""Local web server: streams each pipeline stage to the page as it completes.

    uv run --env-file .env uvicorn taxichat.server:app --reload

Without DEEPSEEK_API_KEY the replies come from the fixed templates.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse

from .classify import JEV_URL, JevClassifier
from .pipeline import answer
from .queries import Database
from .transport import HttpTransport
from .writer import DEEPSEEK_URL, DeepSeekWriter

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).parent / "static"

app = FastAPI()
classifier = JevClassifier(HttpTransport(JEV_URL, os.environ.get("TYPESAFE_API_KEY", "")))
writer = DeepSeekWriter(HttpTransport(DEEPSEEK_URL, key)) if (key := os.environ.get("DEEPSEEK_API_KEY")) else None
db = Database(ROOT / "data")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/ask")
def ask(q: str) -> StreamingResponse:
    def events():
        try:
            for event in answer(q, datetime.now(), classifier=classifier, writer=writer, db=db):
                yield f"data: {json.dumps(event, default=str)}\n\n"
        except Exception as error:  # surface failures to the page instead of a silent hang
            yield f"data: {json.dumps({'stage': 'error', 'message': str(error)})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")
