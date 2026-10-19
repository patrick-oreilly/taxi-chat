import { FlyToInterpolator, WebMercatorViewport, type MapViewState, type PickingInfo } from '@deck.gl/core'
import { GeoJsonLayer } from '@deck.gl/layers'
import DeckGL from '@deck.gl/react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Map } from 'react-map-gl/maplibre'

import type { Highlight, LitZone } from './types'

type ZoneFeature = GeoJSON.Feature<GeoJSON.Polygon | GeoJSON.MultiPolygon, { LocationID: number; zone: string; borough: string }>
type RGBA = [number, number, number, number]

const BASEMAP = 'https://basemaps.cartocdn.com/gl/dark-matter-nolabels-gl-style/style.json'

// Manhattan's street grid runs about 29° east of north; turning the map by the
// same angle stands the avenues upright, the way the city is read from above.
const HOME: MapViewState = { longitude: -73.935, latitude: 40.705, zoom: 10.25, pitch: 48, bearing: 29 }

// Leaves room for the conversation (left) and trace (right) panels.
const PANEL_PADDING = { left: 460, right: 440, top: 140, bottom: 140 }

const TAXI: RGBA = [246, 184, 0, 255]
const COOL: RGBA = [206, 220, 255, 255]
const STREET_LINE: RGBA = [148, 170, 210, 46]
const STREET_FILL: RGBA = [120, 140, 180, 7]
const MAX_ELEVATION = 1500 // metres at the tallest answer, when only a few zones are lit
const RISE = 0.7 // share of the timeline one block takes to rise
const STAGGER = 0.11 // delay between successive ranks

function easeOutExpo(x: number) {
  return x >= 1 ? 1 : 1 - Math.pow(2, -10 * x)
}

function boundsOf(features: ZoneFeature[]): [[number, number], [number, number]] | null {
  let [minX, minY, maxX, maxY] = [Infinity, Infinity, -Infinity, -Infinity]
  for (const f of features) {
    const rings = f.geometry.type === 'Polygon' ? f.geometry.coordinates : f.geometry.coordinates.flat()
    for (const ring of rings) for (const [x, y] of ring) {
      minX = Math.min(minX, x); minY = Math.min(minY, y); maxX = Math.max(maxX, x); maxY = Math.max(maxY, y)
    }
  }
  return Number.isFinite(minX) ? [[minX, minY], [maxX, maxY]] : null
}

export function CityMap({ highlight, declined, busy }: { highlight?: Highlight; declined: boolean; busy: boolean }) {
  const [zones, setZones] = useState<ZoneFeature[]>([])
  const [viewState, setViewState] = useState<MapViewState>(HOME)
  const [progress, setProgress] = useState(1)
  const frame = useRef(0)

  useEffect(() => {
    fetch('/zones.geojson')
      .then((r) => r.json())
      .then((data: GeoJSON.FeatureCollection) => setZones(data.features as ZoneFeature[]))
  }, [])

  const lit = useMemo(() => {
    const byId = new globalThis.Map<number, LitZone>()
    for (const z of highlight?.zones ?? []) byId.set(z.id, z)
    return byId
  }, [highlight])

  const litFeatures = useMemo(() => zones.filter((f) => lit.has(f.properties.LocationID)), [zones, lit])

  const maxValue = useMemo(() => {
    const values = [...lit.values()].map((z) => z.value ?? 0)
    return Math.max(0, ...values)
  }, [lit])
  const maxRank = useMemo(() => Math.max(1, ...[...lit.values()].map((z) => z.rank ?? 1)), [lit])

  // The rise: one timeline per answer, each rank starting a beat after the last.
  useEffect(() => {
    cancelAnimationFrame(frame.current)
    if (!litFeatures.length) return
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduce) { setProgress(10); return }
    const start = performance.now()
    const total = 1400 + (maxRank - 1) * STAGGER * 1400
    const tick = (now: number) => {
      const t = (now - start) / 1400
      setProgress(t)
      if (now - start < total + 200) frame.current = requestAnimationFrame(tick)
    }
    setProgress(0)
    frame.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame.current)
  }, [litFeatures, maxRank])

  // Fly the camera to whatever the answer lit; home when nothing is lit.
  useEffect(() => {
    const target = litFeatures.length ? boundsOf(litFeatures) : null
    if (!target) {
      if (highlight) setViewState((v) => ({ ...v, ...HOME, transitionDuration: 1400, transitionInterpolator: new FlyToInterpolator({ speed: 1.4 }) }))
      return
    }
    const { innerWidth: width, innerHeight: height } = window
    const viewport = new WebMercatorViewport({ width, height })
    const padding = width > 1100 ? PANEL_PADDING : 40
    const { longitude, latitude, zoom } = viewport.fitBounds(target, { padding })
    setViewState((v) => ({
      ...v,
      longitude,
      latitude,
      zoom: Math.min(zoom - 0.15, litFeatures.length === 1 ? 11.9 : 12.6),
      pitch: HOME.pitch,
      bearing: HOME.bearing,
      transitionDuration: 1700,
      transitionInterpolator: new FlyToInterpolator({ speed: 1.3 }),
    }))
  }, [litFeatures, highlight])

  const rankShade = (zone: LitZone | undefined): RGBA => {
    if (!zone) return TAXI
    if (zone.group === 'b') return COOL
    const step = zone.rank ? (zone.rank - 1) / Math.max(1, maxRank - 1) : 0
    return [TAXI[0], Math.round(TAXI[1] - step * 46), Math.round(TAXI[2] + step * 10), Math.round(240 - step * 110)]
  }

  const rise = (zone: LitZone | undefined) => {
    const delay = zone?.rank ? (zone.rank - 1) * STAGGER : 0
    return easeOutExpo(Math.max(0, Math.min(1, (progress - delay) / RISE)))
  }

  // A whole borough lit at full height reads as a slab, not a skyline, so the
  // more zones an answer lights, the lower the blocks stand.
  // A single lit zone has nothing to stand against, so it stands lower too.
  const crowd = litFeatures.length === 1 ? 0.45 : Math.min(1, Math.sqrt(6 / Math.max(1, litFeatures.length)))
  const height = (zone: LitZone | undefined) => {
    const share = maxValue > 0 && zone?.value ? Math.sqrt(zone.value / maxValue) : 0.6
    return (120 + share * MAX_ELEVATION * crowd) * rise(zone)
  }

  const layers = [
    new GeoJsonLayer<ZoneFeature['properties']>({
      id: 'streets',
      data: zones as never,
      filled: true,
      stroked: true,
      getFillColor: declined ? [110, 110, 110, 6] : STREET_FILL,
      getLineColor: declined ? [120, 120, 120, 34] : busy ? [168, 188, 226, 70] : STREET_LINE,
      lineWidthMinPixels: 0.6,
      pickable: true,
      autoHighlight: !declined,
      highlightColor: [246, 184, 0, 34],
      updateTriggers: { getFillColor: declined, getLineColor: [declined, busy] },
      transitions: { getLineColor: 600, getFillColor: 600 },
    }),
    new GeoJsonLayer<ZoneFeature['properties']>({
      id: 'halo',
      data: litFeatures as never,
      filled: false,
      stroked: true,
      getLineColor: (f) => { const c = rankShade(lit.get(f.properties.LocationID)); return [c[0], c[1], c[2], Math.round(70 * rise(lit.get(f.properties.LocationID)))] },
      lineWidthMinPixels: 6,
      updateTriggers: { getLineColor: [progress, highlight] },
      parameters: { depthWriteEnabled: false },
    }),
    new GeoJsonLayer<ZoneFeature['properties']>({
      id: 'lit',
      data: litFeatures as never,
      extruded: true,
      filled: true,
      wireframe: false,
      getFillColor: (f) => rankShade(lit.get(f.properties.LocationID)),
      getElevation: (f) => height(lit.get(f.properties.LocationID)),
      material: { ambient: 0.55, diffuse: 0.65, shininess: 24, specularColor: [255, 214, 120] },
      updateTriggers: { getElevation: [progress, highlight], getFillColor: highlight },
      pickable: true,
    }),
  ]

  const tooltip = ({ object }: PickingInfo<ZoneFeature>) => {
    if (!object) return null
    const zone = lit.get(object.properties.LocationID)
    const rank = zone?.rank ? `<span class="tip-rank">#${zone.rank}</span>` : ''
    return { html: `${rank}<strong>${object.properties.zone}</strong><span>${object.properties.borough}</span>`, className: 'zone-tip' }
  }

  return (
    <div className={`city${declined ? ' is-declined' : ''}`}>
      <DeckGL
        viewState={viewState}
        onViewStateChange={({ viewState: v }) => setViewState(v as MapViewState)}
        controller={{ dragRotate: true }}
        layers={layers}
        getTooltip={tooltip as never}
      >
        <Map mapStyle={BASEMAP} reuseMaps attributionControl={{ compact: true }} />
      </DeckGL>
    </div>
  )
}
