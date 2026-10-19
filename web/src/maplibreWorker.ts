import { setWorkerUrl } from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'

// MapLibre finds its worker next to its own module file, which bundling renames.
// Vite builds the worker as its own chunk; this points MapLibre at it.
setWorkerUrl(workerUrl)
