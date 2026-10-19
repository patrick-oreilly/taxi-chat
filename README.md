# Taxi Chat

A chatbot that answers questions about every NYC taxi and rideshare trip from
2019 to 2025 (roughly 1.9 billion rows) and backs every number with a query you
can inspect. Questions are routed by [Jev](https://docs.typesafe.ai), a
calibrated classification model, and anything the bot isn't confident it can
answer correctly is declined rather than guessed.

Work in progress. The data pipeline is being built first.

## Data

Trip records are published by the NYC Taxi & Limousine Commission. Nothing is
committed here; the pipeline downloads and rebuilds it:

```sh
uv run python -m pipeline.download --from 2019-01 --to 2025-12
uv run python -m pipeline.normalise --from 2019-01 --to 2025-12
```

## Running the interface

Keys go in `.env` (`TYPESAFE_API_KEY`, and `DEEPSEEK_API_KEY` for phrased
replies; without it replies come from fixed templates).

```sh
cd web && npm install && npm run build && cd ..
uv run --env-file .env uvicorn taxichat.server:app   # http://127.0.0.1:8000
```

FastAPI serves the built page from `web/dist`. For work on the interface, run
the API as above and `npm run dev` in `web/`; Vite proxies `/api` to port 8000.
`TAXI_DATA_DIR` points the server at a data directory other than `data/`.

The zone shapes in `web/public/zones.geojson` are NYC TLC's taxi zone
boundaries (NYC Open Data), reprojected to WGS84 and simplified with
mapshaper. The basemap is CARTO's Dark Matter (© CARTO, © OpenStreetMap
contributors).

## Licence

MIT. See [LICENSE](LICENSE).
