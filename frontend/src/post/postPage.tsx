/**
 * A Featured routes post's page, after the server has drawn it whole (core/route_posts.py, which says what each part
 * is and why). This adds what needs a browser:
 *
 * - the live map of the route in place of the picture, panned and zoomed with two fingers on a phone so the page
 *   still scrolls with one (MapLibre's cooperative gestures);
 * - Plan's own charts of the route's frozen answer: the stress bar, and the elevation chart with the rolling stress
 *   chart under it (ElevationChart.tsx), whose scrub moves a marker on the map as in Plan;
 * - Send to Garmin and Send to Wahoo, as the app's own (GpxPanel.tsx): to the rider's connected account when there is
 *   one, else the FIT course handed to the phone or saved;
 * - a small map under each highlighted section that names its stretch (From mile, To mile in the admin): the whole
 *   route faint, the stretch drawn over it and filling the map, made as the reader scrolls near it and let go once
 *   far past, so a long post never holds more than a few maps;
 * - each photo that knows where it was taken as a dot on the route with its thumbnail beside the route, not over
 *   it: on the route's map opening a pop-out of the photo, and on each section map it falls in (photoPins.ts);
 * - for an instance admin, "Use this map as the link picture": the post's map drawn at 1200 by 630 with its credits,
 *   sent to the server as the link preview's picture, and Add photo, which draws a photo again smaller, with no
 *   date or camera details, and sends it with where it was taken (photos.ts).
 */
import "maplibre-gl/dist/maplibre-gl.css";
import "../styles.css";
import "../fonts/fonts.css";
import "./post.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map as MapLibreMap, PositionAnchor } from "maplibre-gl";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { Protocol } from "pmtiles";
import { layers as protomapsLayers, namedFlavor } from "@protomaps/basemaps";
import type { RouteResponse } from "../lib/api.ts";
import type { LonLat } from "../lib/geo.ts";
import { ACKNOWLEDGEMENTS_LINK, BASEMAP_SOURCE_ID, MAP_CREDITS, buildStyle } from "../lib/mapStyle.ts";
import { mapGlyphRequest } from "../lib/mapGlyphAssets.ts";
import { withClearRoadLabels } from "../stressStyle.js";
import { ElevationChart } from "../ElevationChart.tsx";
import { tripRoute } from "../lib/tripRides.ts";
import { usableProfile } from "../lib/profileChart.ts";
import { segmentClass, segmentStyle, stressSegments } from "../lib/stressBar.ts";
import { stressBarKey, stressBarLabel } from "../lib/quickFigures.ts";
import { ROUTE_BLUE } from "../lib/routeColours.ts";
import { handCourseToWahoo, sendCourseToGarmin, sendCourseToWahoo } from "../GpxPanel.tsx";
import { readWahoo } from "../lib/wahooLink.ts";
import { MINIMAP_LABEL, showMinimaps } from "./minimaps.ts";
import { wireSends } from "./sends.ts";
import { wirePhotos } from "./photos.ts";
import { type PostPhoto, besideOffset, photoPins, photosNear, pinLabel } from "./photoPins.ts";
import { t } from "../lib/i18n.ts";

/** What the server puts in the page (route_posts.page_data). */
export interface PostData {
  slug: string;
  title: string;
  line: number[][];
  answer: RouteResponse;
  points: LonLat[];
  admin: boolean;
  csrf?: string;
  /** The line of each highlighted section's stretch, in page order (route_posts.section_line). */
  sections?: number[][][];
  /** The photos that know where they were taken (route_posts.page_data). */
  photos?: PostPhoto[];
}

export const WAHOO_NOT_CONNECTED =
  "Wahoo isn't connected in RouteMaker's Settings.";
export const PICTURE_MAKING = "Drawing the map…";
export const PICTURE_DONE = "Done. This map is now the link picture. Chat apps may show the old one for a while.";
export const PICTURE_FAILED = "The picture could not be made or sent. Try again.";
/** The credits drawn on the link picture: the map's own sources, briefly. */
export const PICTURE_CREDIT = "© OpenStreetMap contributors · Protomaps · RouteMaker";
const PICTURE = { width: 1200, height: 630 };
const START_COLOUR = "#15803d";
const FINISH_COLOUR = "#b91c1c";
const STOP_COLOUR = "#1f2933";

export function readData(doc: Document = document): PostData | null {
  const text = doc.getElementById("post-data")?.textContent;
  if (!text) return null;
  try {
    const data = JSON.parse(text) as PostData;
    return Array.isArray(data.line) && data.line.length >= 2 ? data : null;
  } catch {
    return null;
  }
}

/** The line's extent as [[west, south], [east, north]]. */
export function extent(line: readonly number[][]): [[number, number], [number, number]] {
  let [west, south, east, north] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const p of line) {
    west = Math.min(west, p[0]);
    east = Math.max(east, p[0]);
    south = Math.min(south, p[1]);
    north = Math.max(north, p[1]);
  }
  return [
    [west, south],
    [east, north],
  ];
}

/** The start, the finish and the stops between, as map points (a loop's finish is its start). */
export function pins(line: readonly number[][], points: readonly LonLat[]) {
  const at = (p: readonly number[], kind: string) => ({ type: "Feature", properties: { kind }, geometry: { type: "Point", coordinates: [p[0], p[1]] } });
  const stops = points.slice(1, -1).map((p) => at(p, "stop"));
  return { type: "FeatureCollection", features: [...stops, at(line[line.length - 1], "finish"), at(line[0], "start")] };
}

let protocolOn = false;
function mapStyle(): maplibregl.StyleSpecification {
  if (!protocolOn) {
    maplibregl.setWorkerUrl(maplibreWorkerUrl);
    maplibregl.addProtocol("pmtiles", new Protocol().tile);
    protocolOn = true;
  }
  const layers = withClearRoadLabels(protomapsLayers(BASEMAP_SOURCE_ID, namedFlavor("light"), { lang: "en" }));
  return buildStyle(window.location.origin, layers) as maplibregl.StyleSpecification;
}

/** The route, its pins and (on the page's map) the charts' scrub marker. */
function addRoute(map: MapLibreMap, data: PostData): void {
  map.addSource("post-route", { type: "geojson", data: { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: data.line.map((p) => [p[0], p[1]]) } } });
  map.addLayer({ id: "post-route-casing", type: "line", source: "post-route", layout: { "line-join": "round", "line-cap": "round" }, paint: { "line-color": "#ffffff", "line-width": 9 } });
  map.addLayer({ id: "post-route-line", type: "line", source: "post-route", layout: { "line-join": "round", "line-cap": "round" }, paint: { "line-color": ROUTE_BLUE, "line-width": 5 } });
  map.addSource("post-pins", { type: "geojson", data: pins(data.line, data.points) as maplibregl.GeoJSONSourceSpecification["data"] });
  map.addLayer({
    id: "post-pins",
    type: "circle",
    source: "post-pins",
    paint: {
      "circle-radius": ["match", ["get", "kind"], "stop", 5, 8],
      "circle-color": ["match", ["get", "kind"], "start", START_COLOUR, "finish", FINISH_COLOUR, STOP_COLOUR],
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 2.5,
    },
  });
}

/** A thumbnail of a photo for a map marker: loaded only when it shows, never in the way of the page. */
function thumbnail(photo: PostPhoto): HTMLImageElement {
  const thumb = document.createElement("img");
  thumb.src = photo.url;
  thumb.alt = "";
  thumb.loading = "lazy";
  thumb.decoding = "async";
  return thumb;
}

/** How far a photo's thumbnail sits from its spot, in pixels, on the route's map and on a section map. */
const BESIDE_PX = 44;
const BESIDE_SMALL_PX = 34;

/**
 * A photo on a map as a small dot at its spot on the route, with its thumbnail beside the route (not over it) and a
 * short line from the dot to it (photoPins.ts besideOffset). The thumbnail moves to the side nearer the map's middle
 * as the map is moved, so it stays in the frame.
 */
function photoMark(map: MapLibreMap, data: PostData, photo: PostPhoto, root: HTMLElement, distance: number): void {
  root.classList.add("photo-mark");
  const leader = document.createElement("span");
  leader.className = "photo-leader";
  const dot = document.createElement("span");
  dot.className = "photo-dot";
  const thumb = document.createElement("span");
  thumb.className = "photo-thumb";
  thumb.append(thumbnail(photo));
  root.append(leader, dot, thumb);
  const place = (): void => {
    const spot = map.project([photo.lon, photo.lat]);
    const line = data.line.map((p) => {
      const at = map.project([p[0], p[1]]);
      return [at.x, at.y] as const;
    });
    const canvas = map.getCanvas();
    const middle = [canvas.clientWidth / 2, canvas.clientHeight / 2] as const;
    const { dx, dy } = besideOffset([spot.x, spot.y], line, middle, distance);
    thumb.style.transform = `translate(${dx}px, ${dy}px)`;
    leader.style.width = `${distance}px`;
    leader.style.transform = `rotate(${Math.atan2(dy, dx)}rad)`;
    root.dataset.dx = String(dx);
    root.dataset.dy = String(dy);
  };
  place();
  map.on("moveend", place);
  new maplibregl.Marker({ element: root }).setLngLat([photo.lon, photo.lat]).addTo(map);
}

/** Clear of a thumbnail's middle, in pixels, so a pop-out opens next to the thumbnail, not over it. */
const POPOUT_GAP_PX = 24;

/**
 * Where a photo's pop-out hangs from: its thumbnail, beside the route, pushed out by POPOUT_GAP_PX on whichever side
 * MapLibre anchors it to keep it in the frame, so the pop-out never covers the thumbnail or the spot.
 */
function fromThumb(pin: HTMLElement): Record<PositionAnchor, [number, number]> {
  const dx = Number(pin.dataset.dx) || 0;
  const dy = Number(pin.dataset.dy) || 0;
  const g = POPOUT_GAP_PX;
  return {
    center: [dx, dy],
    top: [dx, dy + g],
    bottom: [dx, dy - g],
    left: [dx + g, dy],
    right: [dx - g, dy],
    "top-left": [dx + g, dy + g],
    "top-right": [dx - g, dy + g],
    "bottom-left": [dx + g, dy - g],
    "bottom-right": [dx - g, dy - g],
  };
}

/**
 * Each photo on the route's map: a dot on the route with its thumbnail beside it, together a button that opens a
 * pop-out of the photo with its caption, from the thumbnail. The button opens it itself (not the marker's own toggle,
 * which a keyboard press opens and its click closes again); Escape or the close button shuts it and hands focus back.
 */
function addPhotoPopouts(map: MapLibreMap, data: PostData, photos: readonly PostPhoto[]): void {
  for (const photo of photos) {
    const pin = document.createElement("button");
    pin.type = "button";
    pin.setAttribute("aria-label", pinLabel(photo));
    pin.setAttribute("aria-haspopup", "dialog");
    pin.setAttribute("aria-expanded", "false");
    photoMark(map, data, photo, pin, BESIDE_PX);
    const card = document.createElement("figure");
    card.className = "photo-popout";
    const big = document.createElement("img");
    big.src = photo.url;
    big.alt = photo.alt;
    card.append(big);
    if (photo.caption) {
      const words = document.createElement("figcaption");
      words.textContent = photo.caption;
      card.append(words);
    }
    const popup = new maplibregl.Popup({ maxWidth: "280px", focusAfterOpen: true }).setDOMContent(card);
    // On the whole pop-out, so Escape works from its close button too (a sibling of the card).
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") popup.remove();
    };
    popup.on("open", () => {
      pin.setAttribute("aria-expanded", "true");
      popup.getElement()?.addEventListener("keydown", onKey);
    });
    popup.on("close", () => {
      pin.setAttribute("aria-expanded", "false");
      pin.focus();
    });
    pin.addEventListener("click", (event) => {
      event.stopPropagation();
      if (popup.isOpen()) {
        popup.remove();
        return;
      }
      popup.setOffset(fromThumb(pin)).setLngLat([photo.lon, photo.lat]).addTo(map);
    });
    // The thumbnail can change sides as the map moves (photoMark's own moveend runs first): the pop-out follows it.
    map.on("moveend", () => {
      if (popup.isOpen()) popup.setOffset(fromThumb(pin));
    });
  }
}

/** On a section map: each photo's dot on the route with a small thumbnail beside it. */
function addPhotoPointers(map: MapLibreMap, data: PostData, photos: readonly PostPhoto[]): void {
  for (const photo of photos) {
    const tag = document.createElement("span");
    tag.classList.add("photo-small");
    tag.setAttribute("role", "img");
    tag.setAttribute("aria-label", pinLabel(photo));
    photoMark(map, data, photo, tag, BESIDE_SMALL_PX);
  }
}

const SCRUB_SOURCE = "post-scrub";

function showMap(host: HTMLElement, data: PostData): MapLibreMap {
  const box = document.createElement("div");
  box.className = "map";
  host.append(box);
  const map = new maplibregl.Map({
    container: box,
    style: mapStyle(),
    bounds: extent(data.line),
    fitBoundsOptions: { padding: 40 },
    attributionControl: false,
    cooperativeGestures: true,
    transformRequest: mapGlyphRequest,
  });
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: false, showCompass: false }), "top-right");
  // One short line (the base map's own credit, OpenStreetMap first), with the full credits a link away: the app's
  // credits panel (lib/mapInfo.ts) would cover a map this small.
  map.addControl(new maplibregl.AttributionControl({ compact: false, customAttribution: `${MAP_CREDITS[0]} | ${ACKNOWLEDGEMENTS_LINK}` }), "bottom-right");
  map.getCanvas().setAttribute("aria-label", host.querySelector("img")?.alt ?? "Map of the route");
  map.on("load", () => {
    addRoute(map, data);
    addPhotoPopouts(map, data, photoPins(data.photos));
    map.addSource(SCRUB_SOURCE, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    map.addLayer({ id: SCRUB_SOURCE, type: "circle", source: SCRUB_SOURCE, paint: { "circle-radius": 7, "circle-color": "#ffffff", "circle-stroke-color": "#1f2933", "circle-stroke-width": 3 } });
    // The picture stays under the map until the map can stand in for it.
    host.classList.add("map-ready");
  });
  return map;
}

function scrubber(map: MapLibreMap | null) {
  return (point: LonLat | null) => {
    const source = map?.getSource(SCRUB_SOURCE) as GeoJSONSource | undefined;
    source?.setData(point ? { type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [point[0], point[1]] } } : { type: "FeatureCollection", features: [] });
  };
}

const WHOLE_ROUTE_COLOUR = "#64748b";

/** One section's small map: the whole route faint, the stretch over it, fitted to the stretch. Still, so the page
 * scrolls past it; the main map above is the one to explore. Returns what lets it go. */
function showMinimap(host: HTMLElement, data: PostData, stretch: number[][]): () => void {
  const box = document.createElement("div");
  box.className = "minimap";
  host.prepend(box);
  let map: MapLibreMap;
  try {
    map = new maplibregl.Map({
      container: box,
      style: mapStyle(),
      bounds: extent(stretch),
      fitBoundsOptions: { padding: 24, maxZoom: 16 },
      interactive: false,
      attributionControl: false,
      transformRequest: mapGlyphRequest,
    });
  } catch (error) {
    // No WebGL: no empty box, the caption on its own.
    box.remove();
    throw error;
  }
  map.addControl(new maplibregl.AttributionControl({ compact: false, customAttribution: MAP_CREDITS[0] }), "bottom-right");
  // The figure's caption says where the stretch is; the label only says what the picture is.
  map.getCanvas().setAttribute("role", "img");
  map.getCanvas().setAttribute("aria-label", MINIMAP_LABEL);
  const lineOf = (line: number[][]) => ({ type: "Feature" as const, properties: {}, geometry: { type: "LineString" as const, coordinates: line.map((p) => [p[0], p[1]]) } });
  map.on("load", () => {
    map.addSource("post-whole", { type: "geojson", data: lineOf(data.line) });
    map.addLayer({ id: "post-whole", type: "line", source: "post-whole", layout: { "line-join": "round", "line-cap": "round" }, paint: { "line-color": WHOLE_ROUTE_COLOUR, "line-width": 3, "line-opacity": 0.6 } });
    map.addSource("post-stretch", { type: "geojson", data: lineOf(stretch) });
    map.addLayer({ id: "post-stretch-casing", type: "line", source: "post-stretch", layout: { "line-join": "round", "line-cap": "round" }, paint: { "line-color": "#ffffff", "line-width": 9 } });
    map.addLayer({ id: "post-stretch", type: "line", source: "post-stretch", layout: { "line-join": "round", "line-cap": "round" }, paint: { "line-color": ROUTE_BLUE, "line-width": 5 } });
    const ends = { type: "FeatureCollection" as const, features: [stretch[0], stretch[stretch.length - 1]].map((p, i) => ({ type: "Feature" as const, properties: { kind: i ? "finish" : "start" }, geometry: { type: "Point" as const, coordinates: [p[0], p[1]] } })) };
    map.addSource("post-stretch-ends", { type: "geojson", data: ends });
    map.addLayer({ id: "post-stretch-ends", type: "circle", source: "post-stretch-ends", paint: { "circle-radius": 6, "circle-color": ["match", ["get", "kind"], "start", START_COLOUR, FINISH_COLOUR], "circle-stroke-color": "#ffffff", "circle-stroke-width": 2 } });
    // Only those the fitted map shows, so none sits clipped at its edge.
    const shown = map.getBounds();
    addPhotoPointers(map, data, photosNear(stretch, photoPins(data.photos)).filter((photo) => shown.contains([photo.lon, photo.lat])));
  });
  return () => {
    map.remove();
    box.remove();
  };
}

/** The stress bar (as RoutePanel.tsx's StressFigure) and Plan's elevation and stress chart. */
export function PostCharts({ answer, onScrub }: { answer: RouteResponse; onScrub?: (point: LonLat | null) => void }) {
  const trip = tripRoute(answer);
  const profile = usableProfile(trip);
  // The frozen answer's sections where it has them, so a half step is its own colour, as on the route line.
  const segments = answer.stress_m ? stressSegments(answer.stress_m, answer.stress_spans) : [];
  return (
    <>
      {segments.length > 0 && (
        <figure className="stress stress-main" aria-labelledby="post-stress-caption">
          <figcaption id="post-stress-caption" className="visually-hidden">
            {t("Traffic stress along the route")}
          </figcaption>
          <div className="stress-bar" role="img" aria-label={stressBarLabel(segments)}>
            {segments
              .filter((s) => s.fraction > 0)
              .map((s) => (
                <span
                  key={s.key}
                  className={`stress-seg ${segmentClass(s)}`}
                  style={{ width: `${s.fraction * 100}%`, ...segmentStyle(s) }}
                  title={`${s.short}: ${s.percent}%`}
                />
              ))}
          </div>
          <p className="stress-key" aria-hidden="true">
            {stressBarKey(segments)}
          </p>
        </figure>
      )}
      {profile && <ElevationChart route={trip} profile={profile} onScrub={onScrub} />}
    </>
  );
}

function showCharts(host: HTMLElement, data: PostData, map: MapLibreMap | null): void {
  const fallback = host.querySelector(".chart-text");
  const box = document.createElement("div");
  box.className = "post-charts";
  host.append(box);
  createRoot(box).render(
    <StrictMode>
      <PostCharts answer={data.answer} onScrub={scrubber(map)} />
    </StrictMode>,
  );
  fallback?.remove();
}

/** The post's map drawn at the link picture's size, with its credits, as a JPEG. */
async function drawPicture(data: PostData): Promise<Blob> {
  const box = document.createElement("div");
  // Off screen, at half size: drawn at twice the pixels, as a phone's screen would.
  box.style.cssText = `position:fixed;left:-10000px;top:0;width:${PICTURE.width / 2}px;height:${PICTURE.height / 2}px`;
  document.body.append(box);
  const map = new maplibregl.Map({
    container: box,
    style: mapStyle(),
    bounds: extent(data.line),
    fitBoundsOptions: { padding: 24 },
    pixelRatio: 2,
    interactive: false,
    attributionControl: false,
    fadeDuration: 0,
    canvasContextAttributes: { preserveDrawingBuffer: true },
    transformRequest: mapGlyphRequest,
  });
  try {
    await map.once("load");
    addRoute(map, data);
    await map.once("idle");
    const canvas = document.createElement("canvas");
    canvas.width = PICTURE.width;
    canvas.height = PICTURE.height;
    const g = canvas.getContext("2d");
    if (!g) throw new Error("no canvas");
    g.drawImage(map.getCanvas(), 0, 0, PICTURE.width, PICTURE.height);
    g.font = '600 18px "Atkinson Hyperlegible", system-ui, sans-serif';
    const width = g.measureText(PICTURE_CREDIT).width;
    g.fillStyle = "rgba(255,255,255,0.85)";
    g.fillRect(PICTURE.width - width - 20, PICTURE.height - 32, width + 20, 32);
    g.fillStyle = "#1f2933";
    g.textBaseline = "middle";
    g.fillText(PICTURE_CREDIT, PICTURE.width - width - 10, PICTURE.height - 16);
    return await new Promise<Blob>((resolve, reject) => canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("no picture"))), "image/jpeg", 0.88));
  } finally {
    map.remove();
    box.remove();
  }
}

function wirePicture(data: PostData): void {
  const button = document.getElementById("make-thumbnail") as HTMLButtonElement | null;
  const said = document.getElementById("thumbnail-said");
  if (!button || !data.admin) return;
  const say = (words: string) => {
    if (said) said.textContent = words;
  };
  button.disabled = false;
  button.addEventListener("click", async () => {
    button.disabled = true;
    say(PICTURE_MAKING);
    try {
      const picture = await drawPicture(data);
      const response = await fetch(`/routes/${encodeURIComponent(data.slug)}/thumbnail`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "image/jpeg", ...(data.csrf ? { "X-CSRFToken": data.csrf } : {}) },
        body: picture,
      });
      say(response.ok ? PICTURE_DONE : PICTURE_FAILED);
    } catch {
      say(PICTURE_FAILED);
    } finally {
      button.disabled = false;
    }
  });
}

export function start(doc: Document = document): void {
  const data = readData(doc);
  if (!data) return;
  const mapHost = doc.getElementById("post-map");
  let map: MapLibreMap | null = null;
  try {
    map = mapHost ? showMap(mapHost, data) : null;
  } catch {
    // No WebGL: the picture stays.
    map = null;
  }
  const charts = doc.getElementById("post-charts");
  if (charts && data.answer) showCharts(charts, data, map);
  showMinimaps(doc, data.sections ?? [], (host, line) => showMinimap(host, data, line));
  wireSends(doc, doc.getElementById("send-said"), {
    garmin: () => sendCourseToGarmin(data.answer, data.points),
    wahoo: async () => {
      const state = await readWahoo(window.location.origin);
      if (state?.connected) return sendCourseToWahoo(data.answer, data.points);
      return `${WAHOO_NOT_CONNECTED} ${await handCourseToWahoo(data.answer, data.points)}`;
    },
  });
  wirePicture(data);
  if (data.admin) wirePhotos(doc, data.slug, data.csrf);
}
