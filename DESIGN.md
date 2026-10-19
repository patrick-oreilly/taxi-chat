---
name: Taxi Chat
description: A night-city map that lights up the zones each answer names, with the reasoning streamed beside it.
colors:
  ground: "#07090d"
  glass: "rgb(9 12 18 / 0.74)"
  glass-edge: "rgb(170 190 230 / 0.11)"
  glass-edge-strong: "rgb(170 190 230 / 0.2)"
  ink: "#e8ecf3"
  ink-2: "#a9b2c3"
  ink-3: "#7d879d"
  taxi: "#f6b800"
  taxi-ink: "#ffcc33"
  cool: "#cedcff"
  pass: "#7fd3a6"
  fail: "#ff8f73"
typography:
  wordmark:
    fontFamily: "Geist Variable, system-ui, sans-serif"
    fontSize: "19px"
    fontWeight: 620
    letterSpacing: "-0.02em"
  figure:
    fontFamily: "Geist Variable, system-ui, sans-serif"
    fontSize: "40px"
    fontWeight: 540
    lineHeight: 1
    letterSpacing: "-0.04em"
  answer:
    fontFamily: "Geist Variable, system-ui, sans-serif"
    fontSize: "17px"
    lineHeight: 1.5
    letterSpacing: "-0.01em"
  body:
    fontFamily: "Geist Variable, system-ui, sans-serif"
    fontSize: "15px"
    lineHeight: 1.5
  label:
    fontFamily: "Geist Variable, system-ui, sans-serif"
    fontSize: "12.5px"
  code:
    fontFamily: "Geist Mono Variable, ui-monospace, monospace"
    fontSize: "11.5px"
rounded:
  pill: "999px"
  panel: "14px"
  control: "10px"
  code: "8px"
spacing:
  gap: "20px"
  panel-x: "24px"
  rail-left: "432px"
  rail-right: "404px"
components:
  panel:
    backgroundColor: "{colors.glass}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
  ask-button:
    backgroundColor: "{colors.taxi}"
    textColor: "#1a1300"
    rounded: "{rounded.control}"
    size: "44px"
  ask-input:
    backgroundColor: "rgb(0 0 0 / 0.35)"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "11px 14px"
  suggestion:
    backgroundColor: "rgb(170 190 230 / 0.05)"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "11px 14px"
  suggestion-hover:
    backgroundColor: "rgb(246 184 0 / 0.1)"
  tag:
    textColor: "{colors.ink-2}"
    rounded: "{rounded.pill}"
    padding: "2px 9px"
---

## Overview

New York at night, seen from above with the avenues standing upright (the map
is turned 29° to match Manhattan's grid). The city is a near-black field of
faint zone outlines; the only lit colour is taxi yellow, and it means one
thing: this is what the answer is about. Everything that explains the answer
sits on dark smoked glass over the map: the conversation on the left, the
"How I got this" trace on the right, the rows-scanned figure between them.

The signature move is the rise: the zones an answer names extrude into lit
blocks, tallest for the largest value, staggered by rank, like a skyline
switching its lights on. A declined question drains the colour from the whole
city instead.

## Colors

- **Ground** `#07090d` and a basemap dimmed to 72% brightness: night, not grey.
- **Taxi** `#f6b800` is the only lit colour: highlighted zones, rank 1, the
  trip count, the trend line, buckets below a threshold, the ask button, done
  steps. Never decoration. `taxi-ink` `#ffcc33` is its text form on glass.
- **Cool** `#cedcff` is the second side of a comparison, and only that.
- **Ink** three steps for text; `ink-3` is the floor for readable text on glass.
- **Pass / fail** appear only on checks and low-confidence readings (< 0.6).
  A decline is not an error: it uses ink and greyscale, not red.

## Typography

Geist for language and figures (tabular numerals for every number people
compare), Geist Mono only for SQL, confidences and timings, things that are
measurements of the machinery rather than answers. Big figures stay in Geist:
mono commas open up into "22 , 646 , 999".

## Layout

A full-bleed map with two glass rails inset 20px: conversation 432px on the
left, trace 404px on the right. Floating map readouts (rows scanned, decline
banner) centre on the gap between the rails. The camera fits whatever the
answer lit, padded so nothing hides under a rail, and never zooms past 12.6
(11.9 for a single zone). Below 1100px the map becomes a 52vh block on top and
the rails stack beneath it.

## Elevation & Depth

Two layers only: the map, and glass over it (blur 20px, saturate 1.25, a
hairline edge, a long soft shadow). Depth inside the map is literal: extruded
zones lit by deck.gl's material, with a flat halo on their outlines.

## Shapes

Rounded but firm: 14px panels, 10px controls, 8px code blocks, pills for tags
and check names. The favicon and the roof light in the wordmark are the
taxi's roof sign.

## Components

- **Trace steps**: a dotted timeline. Done is a lit yellow dot, active pulses,
  waiting is dimmed, a decline or failure is a solid grey dot. Each step shows
  its arrival time in mono.
- **Confidence**: a 44px bar plus the value in mono; below 0.6 it turns `fail`.
- **Answer figures**: ranked list (rank 1 in taxi ink), trend chart (partial
  edge steps hollow on a dashed line, peak labelled), comparison bars (taxi vs
  cool), histogram (buckets below the threshold lit).
- **Readout**: the rows-scanned figure counts up with an exponential ease-out,
  slower and in taxi ink for raw-trip scans; "running the query…" while one runs.

## Do's and Don'ts

- Do keep yellow scarce: if something is yellow, it is part of the answer.
- Do show declines as clearly as answers, in greyscale, with the reason.
- Don't add neon, glow or glass beyond these uses; the city carries the mood.
- Don't put mono on prose or big figures.
- Don't light zones 264/265 (Unknown, Outside of NYC); they have no shape.
