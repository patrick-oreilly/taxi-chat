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

## Licence

MIT. See [LICENSE](LICENSE).
