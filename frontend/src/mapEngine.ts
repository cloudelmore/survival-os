import { layers, namedFlavor } from "@protomaps/basemaps";
import * as maplibre from "maplibre-gl";
import { addProtocol, AttributionControl, Map as GlMap, NavigationControl, ScaleControl,
  setWorkerUrl, type GeoJSONSource, type LayerSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import mlcontour from "maplibre-contour";
import { Protocol } from "pmtiles";
import type { MapInfo, NavigationData } from "./api";

const ATTRIBUTION = "Map data © OpenStreetMap contributors. Rendering by Protomaps and MapLibre.";
const TILE_SOURCE = "basemap";
const OVERZOOM = 3;
const FLY_ZOOM = 14;
const WAYPOINT_COLOR = "#d6249f";
const ROUTE_COLOR = "#d6249f";

const FEET_PER_METER = 3.28084;
const CONTOUR_COLOR = "#7a4a1e";
// Spacing in feet: [minor, major] lines, by zoom.
const CONTOUR_FEET: Record<number, number[]> = {
  9: [500, 2500], 11: [200, 1000], 12: [100, 500], 14: [40, 200], 15: [20, 100],
};
const CONTOUR_LAYERS = ["hillshade", "contours", "contour-labels"];
const IMAGERY_LAYERS = ["imagery"];

export type Center = { lat: number; lon: number; zoom: number };
export type Overlays = { terrain?: MapInfo; imagery?: MapInfo };
export type MapHandle = {
  center: () => Center;
  show: (overlay: "terrain" | "imagery", visible: boolean) => void;
  flyTo: (lon: number, lat: number) => void;
  setData: (data: NavigationData) => void;
  destroy: () => void;
};

let ready = false;
function prepare() {
  if (ready) return;
  ready = true;
  // The worker ships in the build, so it never loads from a CDN.
  setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");
  addProtocol("pmtiles", new Protocol().tile);
}

const waypointFeatures = (data: NavigationData) => ({
  type: "FeatureCollection" as const,
  features: data.waypoints.map((item) => ({
    type: "Feature" as const,
    properties: { name: item.name },
    geometry: { type: "Point" as const, coordinates: [item.lon, item.lat] },
  })),
});

const routeFeatures = (data: NavigationData) => ({
  type: "FeatureCollection" as const,
  features: data.routes.map((item) => ({
    type: "Feature" as const,
    properties: { name: item.name },
    geometry: { type: "LineString" as const, coordinates: item.points },
  })),
});

function terrainParts(origin: string, info: MapInfo) {
  const dem = new mlcontour.DemSource({
    url: `${origin}/api/maps/${info.id}/tile/{z}/{x}/{y}`,
    encoding: "terrarium",
    maxzoom: info.max_zoom,
    worker: true,
  });
  dem.setupMaplibre(maplibre);
  const sources = {
    dem: { type: "raster-dem" as const, tiles: [dem.sharedDemProtocolUrl], encoding: "terrarium" as const,
      maxzoom: info.max_zoom, tileSize: 512 },
    contours: { type: "vector" as const, maxzoom: 15, attribution: "Terrain: Mapterhorn.", tiles: [dem.contourProtocolUrl({
      multiplier: FEET_PER_METER, thresholds: CONTOUR_FEET, contourLayer: "contours",
      elevationKey: "ele", levelKey: "level", overzoom: 1,
    })] },
  };
  const layout = { visibility: "none" as const };
  const hillshade: LayerSpecification = { id: "hillshade", type: "hillshade", source: "dem", layout,
    paint: { "hillshade-exaggeration": 0.35 } };
  const lines: LayerSpecification[] = [
    { id: "contours", type: "line", source: "contours", "source-layer": "contours", layout,
      paint: { "line-color": CONTOUR_COLOR, "line-opacity": 0.75,
        "line-width": ["case", [">", ["get", "level"], 0], 1.4, 0.6] } },
    { id: "contour-labels", type: "symbol", source: "contours", "source-layer": "contours",
      filter: [">", ["get", "level"], 0],
      layout: { visibility: "none", "symbol-placement": "line", "text-size": 11,
        "text-field": ["concat", ["number-format", ["get", "ele"], {}], " ft"],
        "text-font": ["Noto Sans Regular"] },
      paint: { "text-color": CONTOUR_COLOR, "text-halo-color": "#ffffff", "text-halo-width": 1.5 } },
  ];
  return { sources, hillshade, lines };
}

export function createMap(container: HTMLElement, info: MapInfo, overlays: Overlays,
  onMove: (center: Center) => void, onFailure: () => void): MapHandle {
  prepare();
  const origin = window.location.origin;
  // Photos cover the land drawing but stay under labels. Shading stays under roads.
  const base = layers(TILE_SOURCE, namedFlavor("light"), { lang: "en" }) as LayerSpecification[];
  const firstLabel = base.findIndex((layer) => layer.type === "symbol");
  const firstRoad = base.findIndex((layer) => layer.id.startsWith("roads_tunnels"));
  const terrain = overlays.terrain ? terrainParts(origin, overlays.terrain) : null;
  const photo: LayerSpecification[] = overlays.imagery ? [{ id: "imagery", type: "raster",
    source: "imagery", layout: { visibility: "none" } }] : [];
  const empty: NavigationData = { waypoints: [], routes: [] };
  const map = new GlMap({
    container,
    attributionControl: false,
    bounds: info.bbox as [number, number, number, number],
    maxZoom: info.max_zoom + OVERZOOM,
    style: {
      version: 8,
      glyphs: `${origin}/maps/fonts/{fontstack}/{range}.pbf`,
      sprite: `${origin}/maps/sprites/light`,
      sources: {
        [TILE_SOURCE]: {
          type: "vector",
          url: `pmtiles://${origin}/api/maps/${info.id}/file`,
          attribution: ATTRIBUTION,
        },
        ...(terrain?.sources ?? {}),
        ...(overlays.imagery ? { imagery: { type: "raster" as const, tileSize: 256,
          url: `pmtiles://${origin}/api/maps/${overlays.imagery.id}/file`,
          attribution: "Aerial photos: USDA NAIP, USGS." } } : {}),
        routes: { type: "geojson", data: routeFeatures(empty) },
        waypoints: { type: "geojson", data: waypointFeatures(empty) },
      },
      layers: [
        ...base.slice(0, firstRoad),
        ...(terrain ? [terrain.hillshade] : []),
        ...base.slice(firstRoad, firstLabel),
        ...photo,
        ...(terrain?.lines ?? []),
        ...base.slice(firstLabel),
        { id: "user-routes", type: "line", source: "routes",
          paint: { "line-color": ROUTE_COLOR, "line-width": 3 } },
        { id: "user-waypoints", type: "circle", source: "waypoints",
          paint: { "circle-color": WAYPOINT_COLOR, "circle-radius": 7,
            "circle-stroke-color": "#ffffff", "circle-stroke-width": 2 } },
        { id: "user-waypoint-names", type: "symbol", source: "waypoints",
          layout: { "text-field": ["get", "name"], "text-font": ["Noto Sans Medium"],
            "text-size": 14, "text-offset": [0, 1.1], "text-anchor": "top" },
          paint: { "text-color": "#000000", "text-halo-color": "#ffffff", "text-halo-width": 2 } },
      ],
    },
  });
  map.addControl(new NavigationControl({ showCompass: true }), "top-right");
  map.addControl(new ScaleControl({ unit: "imperial" }), "top-left");
  map.addControl(new AttributionControl({ compact: false }), "bottom-right");

  const center = () => {
    const point = map.getCenter();
    return { lat: point.lat, lon: point.lng, zoom: map.getZoom() };
  };
  let waiting: NavigationData | null = null;
  const apply = (data: NavigationData) => {
    (map.getSource("waypoints") as GeoJSONSource).setData(waypointFeatures(data));
    (map.getSource("routes") as GeoJSONSource).setData(routeFeatures(data));
  };
  map.on("move", () => onMove(center()));
  map.on("load", () => {
    onMove(center());
    if (waiting) apply(waiting);
    waiting = null;
  });
  map.on("error", (event) => {
    // Overlays end at their edges, and a glyph range outside the bundled Latin set only blanks
    // those labels. Neither stops the map.
    const source = (event as { sourceId?: string }).sourceId;
    if ((!source || source === TILE_SOURCE) && !/\.pbf/.test(String(event.error?.message))) onFailure();
  });

  const show = (overlay: "terrain" | "imagery", visible: boolean) => {
    const names = overlay === "terrain" ? CONTOUR_LAYERS : IMAGERY_LAYERS;
    for (const name of names) {
      if (map.getLayer(name)) map.setLayoutProperty(name, "visibility", visible ? "visible" : "none");
    }
  };

  return {
    center,
    show,
    flyTo: (lon, lat) => map.flyTo({ center: [lon, lat], zoom: Math.max(map.getZoom(), FLY_ZOOM) }),
    setData: (data) => { if (map.isStyleLoaded()) apply(data); else waiting = data; },
    destroy: () => map.remove(),
  };
}
