"""Local web server: streams each pipeline stage to the page as it completes.

    uv run --env-file .env uvicorn taxichat.server:app --reload

Serves the built interface from web/dist when it exists (`npm run build` in
web/), and the bare fallback page otherwise. TAXI_DATA_DIR points at the data
directory, defaulting to the repo's data/. Without DEEPSEEK_API_KEY the
replies come from the fixed templates.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .classify import JEV_URL, JevClassifier
from .pipeline import answer
from .places import all_places
from .queries import Database
from .transport import HttpTransport
from .writer import DEEPSEEK_URL, DeepSeekWriter

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).parent / "static"
WEB_DIST = ROOT / "web" / "dist"
DATA = Path(os.environ.get("TAXI_DATA_DIR", ROOT / "data"))

# Every month the finished dataset should contain; TLC never published rideshare January 2019.
EXPECTED_MONTHS = {"yellow": 84, "green": 84, "fhvhv": 83}

app = FastAPI()
classifier = JevClassifier(HttpTransport(JEV_URL, os.environ.get("TYPESAFE_API_KEY", "")))
writer = DeepSeekWriter(HttpTransport(DEEPSEEK_URL, key)) if (key := os.environ.get("DEEPSEEK_API_KEY")) else None
db = Database(DATA)


def highlight(trace: dict) -> dict:
    """Which zones the map should light, and how, for a finished trace."""
    if trace.get("declined"):
        return {"mode": "declined", "zones": []}
    places = all_places()
    result = trace.get("result") or {}
    if "rows" in result:
        zones = []
        for row in result["rows"]:
            ids = [row["id"]] if result.get("rank_unit") == "zones" else list(places[f"borough:{row['name'].lower()}"].zone_ids)
            zones += [{"id": int(i), "rank": row["rank"], "value": row["value"], "label": row["name"]} for i in ids]
        return {"mode": "ranking", "zones": zones}
    place = ((trace.get("details") or {}).get("place") or {}).get("value")
    if place and place in places:
        p = places[place]
        return {"mode": "place", "zones": [{"id": i, "rank": None, "value": result.get("value"), "label": p.label} for i in p.zone_ids]}
    return {"mode": "city", "zones": []}


@app.get("/api/ask")
def ask(q: str) -> StreamingResponse:
    def events():
        try:
            for event in answer(q, datetime.now(), classifier=classifier, writer=writer, db=db):
                if event["stage"] == "done":
                    event = {**event, "highlight": highlight(event["trace"])}
                yield f"data: {json.dumps(event, default=str)}\n\n"
        except Exception as error:  # surface failures to the page instead of a silent hang
            yield f"data: {json.dumps({'stage': 'error', 'message': str(error)})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@app.get("/api/stats")
def stats() -> dict:
    """The exact trip count, straight from the normalise stage's manifests."""
    manifests = [json.loads(p.read_text()) for p in (DATA / "manifests").glob("*/*.json")]
    months = {service: sum(m["service"] == service for m in manifests) for service in EXPECTED_MONTHS}
    return {
        "trips": sum(m["rows_out"] for m in manifests),
        "months_loaded": sum(months.values()),
        "months_expected": sum(EXPECTED_MONTHS.values()),
        "complete": all(months[s] >= n for s, n in EXPECTED_MONTHS.items()),
    }


if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
else:

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")
