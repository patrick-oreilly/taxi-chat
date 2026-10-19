# Product

<!-- impeccable:product-schema 1 -->

> Written without a live interview: this was built by an agent that could not
> put questions to the owner. Every fact below comes from decisions Patrick
> confirmed while planning the project (GitHub issue #1 and its tickets).
> Items marked *(inferred)* are the agent's reading of those decisions.

## Platform

web

## Stack

Python (FastAPI, DuckDB) backend; React + TypeScript + Vite frontend with
deck.gl over a MapLibre basemap. Chosen by the owner during planning.

## Users

- **Patrick**, running the app locally to record a screen demo and take README
  screenshots.
- **Recruiters and engineers** who watch that recording or look at the
  screenshots on GitHub and Patrick's portfolio. They never use the app
  themselves; there is no hosted demo.

## Product Purpose

Taxi Chat answers plain-English questions about every NYC yellow taxi, green
taxi and rideshare trip from 2019 to 2025 (about 1.9 billion trips). Its claim
is answer robustness: every number comes from a query the viewer can inspect,
and the bot declines what it can't answer instead of guessing. Success is a
viewer believing that claim from a one-minute recording.

## Positioning

Jev, a calibrated classification model, routes each question and reports its
confidence; code resolves dates and places and runs a parameterised query;
a language model only phrases the result, and a checker rejects any number it
didn't get from the query. The interface shows that whole chain as it happens.

## Operating Context

- Run locally on Patrick's Mac; recorded at desktop resolution *(inferred:
  1920×1080 and 1440-wide screenshots)*.
- Single-turn questions only; no follow-ups or conversation memory.
- Answers stream stage by stage from the server.

## Capabilities and Constraints

- Answers totals, averages and rankings now; trends, comparisons and
  distributions are being added (#6).
- Places are NYC's 265 TLC taxi zones, groups of zones that share a name, and
  boroughs. Zones 264/265 (Unknown, Outside of NYC) are never highlighted.
- Declines: out of scope, prompt injection, compound questions, uncertain
  intent or detail, periods outside the data, dropoff questions (until #6).
- No hosting, no accounts, no live public use.

## Brand Commitments

- Visual direction confirmed by the owner: a night-city look, near-black map,
  zone outlines that glow taxi-yellow when highlighted, dark glass panels,
  Geist and Geist Mono (shared with his portfolio), "really sophisticated".

## Evidence on Hand

- Real data: TLC trip records 2019–2025 under `data/` (not committed), with an
  exact trip count from the pipeline manifests.
- Zone boundaries: TLC's published taxi zone shapefile.
- No testimonials, users or benchmarks yet; the benchmark is #9/#10. Nothing
  may be invented.

## Product Principles

1. Every number on screen is traceable to a query result.
2. A decline is a feature, shown as clearly as an answer.
3. Show the mechanism, not a claim about it.
4. The data is the visual: the map does the explaining.
