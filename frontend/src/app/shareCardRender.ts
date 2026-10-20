// Share as image (lib/shareCard.ts): drawing the card. The map is a second MapLibre map, made offscreen at the
// card's own map size with pixelRatio 1 and preserveDrawingBuffer, holding only the base map and the route line,
// fitted to the line; once it is idle its canvas is copied into a 2D canvas and the map removed. Not a capture of
// the page's own map: that one would need preserveDrawingBuffer on all the time (slower on phones), is the
// screen's shape rather than the card's, and shows the stress overlay, the rider's markers and Home. The base map
// is this site's own (pmtiles under /basemap/), so the canvas is never tainted and toBlob works.
import * as maplibregl from "maplibre-gl";
import qrcode from "qrcode-generator";
import { layers as protomapsLayers, namedFlavor } from "@protomaps/basemaps";
import type { RouteProfile } from "../lib/api.ts";
import type { LonLat } from "../lib/geo.ts";
import { BASEMAP_SOURCE_ID, buildStyle } from "../lib/mapStyle.ts";
import { mapGlyphRequest } from "../lib/mapGlyphAssets.ts";
import {
  BRAND,
  cardAttribution,
  cardLayout,
  profileStrip,
  qrFit,
  qrModules,
  statsLine,
  type CardRoute,
  type CardSize,
  type ProfilePlace,
  type ProfileStrip,
  type Rect,
} from "../lib/shareCard.ts";

export interface CardInput {
  size: CardSize;
  route: CardRoute;
  name: string | null;
  distanceM: number;
  climbM: number | null;
  profile: RouteProfile | null;
  profilePlace: ProfilePlace;
  qrLink: string | null;
}

const INK = "#111827";
const MUTED = "#374151";
const LINE = "#1d4ed8";
const START = "#15803d";
const FINISH = "#b91c1c";
const STOP = "#374151";
const FONT = '"Atkinson Hyperlegible", system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans", sans-serif';
/** The longest the offscreen map may take to draw its tiles. */
const MAP_TIMEOUT_MS = 20_000;

/** The offscreen map, fitted to the line, drawn and copied; the pins' places on it. */
async function drawMap(w: number, h: number, route: CardRoute, padding: { top: number; bottom: number; left: number; right: number }) {
  const div = document.createElement("div");
  div.setAttribute("aria-hidden", "true");
  div.style.cssText = `position:fixed;left:${-w - 100}px;top:0;width:${w}px;height:${h}px;pointer-events:none;`;
  document.body.appendChild(div);
  const style = buildStyle(window.location.origin, protomapsLayers(BASEMAP_SOURCE_ID, namedFlavor("light"), { lang: "en" }));
  const line = { type: "Feature" as const, properties: {}, geometry: { type: "MultiLineString" as const, coordinates: route.pieces } };
  style.sources.card = { type: "geojson", data: line };
  const u = Math.min(w, h) / 1000;
  style.layers.push(
    { id: "card-casing", type: "line", source: "card", layout: { "line-join": "round", "line-cap": "butt" }, paint: { "line-color": "#ffffff", "line-width": Math.max(8, 16 * u) } },
    { id: "card-line", type: "line", source: "card", layout: { "line-join": "round", "line-cap": "butt" }, paint: { "line-color": LINE, "line-width": Math.max(5, 9 * u) } },
  );
  const lons = route.pieces.flat().map((p) => p[0]);
  const lats = route.pieces.flat().map((p) => p[1]);
  let map: maplibregl.Map | null = null;
  try {
    map = new maplibregl.Map({
      container: div,
      style: style as maplibregl.StyleSpecification,
      bounds: [
        [Math.min(...lons), Math.min(...lats)],
        [Math.max(...lons), Math.max(...lats)],
      ],
      fitBoundsOptions: { padding, maxZoom: 16 },
      interactive: false,
      attributionControl: false,
      pixelRatio: 1,
      fadeDuration: 0,
      canvasContextAttributes: { preserveDrawingBuffer: true, antialias: true },
      // The labels in the app map's font (lib/mapGlyphAssets.ts).
      transformRequest: mapGlyphRequest,
    });
    const made = map;
    made.setMissingStyleImageResolver((id) => {
      if (!made.hasImage(id)) made.addImage(id, { width: 1, height: 1, data: new Uint8Array(4) });
    });
    await new Promise<void>((resolve, reject) => {
      const timer = window.setTimeout(() => reject(new Error("map timed out")), MAP_TIMEOUT_MS);
      made.once("idle", () => {
        window.clearTimeout(timer);
        resolve();
      });
    });
    const copy = document.createElement("canvas");
    copy.width = w;
    copy.height = h;
    copy.getContext("2d")!.drawImage(made.getCanvas(), 0, 0, w, h);
    const at = (p: LonLat | null) => (p ? made.project(p as [number, number]) : null);
    return { canvas: copy, start: at(route.start), finish: at(route.finish), stops: route.stops.map((p) => made.project(p as [number, number])) };
  } finally {
    map?.remove();
    div.remove();
  }
}

function pin(ctx: CanvasRenderingContext2D, x: number, y: number, r: number, fill: string, text: string, square = false) {
  ctx.beginPath();
  if (square) ctx.rect(x - r, y - r, r * 2, r * 2);
  else ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fillStyle = fill;
  ctx.fill();
  ctx.lineWidth = Math.max(3, r / 4);
  ctx.strokeStyle = "#ffffff";
  ctx.stroke();
  ctx.fillStyle = "#ffffff";
  ctx.font = `700 ${Math.round(r * 1.1)}px ${FONT}`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, x, y + 1);
}

function roundRect(ctx: CanvasRenderingContext2D, r: Rect, radius: number) {
  ctx.beginPath();
  ctx.roundRect(r.x, r.y, r.w, r.h, radius);
}

/** The words cut to fit `width`, with an ellipsis. */
function fit(ctx: CanvasRenderingContext2D, text: string, width: number): string {
  if (ctx.measureText(text).width <= width) return text;
  let t = text;
  while (t.length > 1 && ctx.measureText(`${t}…`).width > width) t = t.slice(0, -1);
  return `${t.trimEnd()}…`;
}

/** The words over as many lines as `width` needs, at most `max`. */
function wrap(ctx: CanvasRenderingContext2D, text: string, width: number, max: number): string[] {
  const lines: string[] = [];
  let line = "";
  for (const word of text.split(" ")) {
    const next = line ? `${line} ${word}` : word;
    if (ctx.measureText(next).width <= width || !line) line = next;
    else {
      lines.push(line);
      line = word;
    }
  }
  if (line) lines.push(line);
  return lines.length > max ? [...lines.slice(0, max - 1), fit(ctx, lines.slice(max - 1).join(" "), width)] : lines;
}

function drawProfile(ctx: CanvasRenderingContext2D, box: Rect, profile: RouteProfile, route: CardRoute, fontPx: number, overMap: boolean): ProfileStrip | null {
  if (overMap) {
    ctx.fillStyle = "rgba(255, 255, 255, 0.85)";
    roundRect(ctx, box, fontPx / 2);
    ctx.fill();
  } else {
    ctx.fillStyle = "#f3f4f6";
    ctx.fillRect(box.x, box.y, box.w, box.h);
  }
  const inset = Math.round(fontPx * 0.6);
  const labelH = Math.round(fontPx * 1.3);
  const plot = { x: box.x + inset, y: box.y + inset + labelH, w: box.w - inset * 2, h: box.h - inset * 2 - labelH * 2 };
  const strip = profileStrip(profile, plot, route.visible);
  if (!strip) return null;
  const bottom = plot.y + plot.h;
  for (const run of strip.runs) {
    ctx.beginPath();
    ctx.moveTo(run[0][0], bottom);
    for (const [x, y] of run) ctx.lineTo(x, y);
    ctx.lineTo(run[run.length - 1][0], bottom);
    ctx.closePath();
    ctx.fillStyle = "rgba(29, 78, 216, 0.22)";
    ctx.fill();
    ctx.beginPath();
    run.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    ctx.strokeStyle = LINE;
    ctx.lineWidth = Math.max(2, fontPx / 8);
    ctx.lineJoin = "round";
    ctx.stroke();
  }
  ctx.fillStyle = INK;
  ctx.font = `400 ${fontPx}px ${FONT}`;
  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  ctx.fillText(`High ${strip.maxLabel}`, box.x + inset, box.y + inset);
  ctx.textBaseline = "bottom";
  ctx.fillText(`Low ${strip.minLabel}`, box.x + inset, box.y + box.h - inset);
  return strip;
}

function drawQr(ctx: CanvasRenderingContext2D, box: Rect, link: string) {
  // Level L: the fewest modules for the link, so each is as large as the square allows (a camera reads a card off a
  // screen, where damage is not the trouble).
  const qr = qrcode(0, "L");
  qr.addData(link);
  qr.make();
  const modules = qrModules(qr);
  const { cell, offset } = qrFit(modules.length, box.w);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(box.x, box.y, box.w, box.h);
  ctx.strokeStyle = "#d1d5db";
  ctx.lineWidth = 2;
  ctx.strokeRect(box.x + 1, box.y + 1, box.w - 2, box.h - 2);
  ctx.fillStyle = "#000000";
  modules.forEach((row, r) => row.forEach((dark, c) => dark && ctx.fillRect(box.x + offset + c * cell, box.y + offset + r * cell, cell, cell)));
}

/** The card as a PNG, and the profile strip it drew (for the text alternative). */
export async function renderCard(input: CardInput): Promise<{ blob: Blob; strip: ProfileStrip | null }> {
  const profilePlace = input.profile ? input.profilePlace : "off";
  const layout = cardLayout(input.size, { name: input.name !== null, qr: input.qrLink !== null, profile: profilePlace });
  const { map, footer, text, font, pad } = layout;
  await document.fonts?.load(`700 ${font.name}px "Atkinson Hyperlegible"`).catch(() => undefined);
  const overMap = profilePlace === "map" && layout.profile ? layout.profile.h + pad : 0;
  const drawn = await drawMap(map.w, map.h, input.route, { top: pad * 2, left: pad * 2, right: pad * 2, bottom: pad * 2 + overMap });
  const canvas = document.createElement("canvas");
  canvas.width = layout.width;
  canvas.height = layout.height;
  const ctx = canvas.getContext("2d")!;
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, layout.width, layout.height);
  ctx.drawImage(drawn.canvas, map.x, map.y);
  // Start, stops and finish: no names, only S, a number, F (and a circle, a square for the finish).
  const r = Math.round(22 * (Math.min(layout.width, layout.height) / 1080)) + 6;
  drawn.stops.forEach((p, i) => pin(ctx, p.x, p.y, r * 0.85, STOP, String(i + 1)));
  if (drawn.start) pin(ctx, drawn.start.x, drawn.start.y, r, START, "S");
  if (drawn.finish) pin(ctx, drawn.finish.x, drawn.finish.y, r, FINISH, "F", true);
  const strip = layout.profile && input.profile ? drawProfile(ctx, layout.profile, input.profile, input.route, font.profile, profilePlace === "map") : null;
  // The footer.
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(footer.x, footer.y, footer.w, footer.h);
  ctx.fillStyle = "#e5e7eb";
  ctx.fillRect(footer.x, footer.y, footer.w, 2);
  let y = text.y;
  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  const write = (words: string, px: number, weight: number, colour: string) => {
    ctx.font = `${weight} ${px}px ${FONT}`;
    ctx.fillStyle = colour;
    ctx.fillText(fit(ctx, words, text.w), text.x, y);
    y += Math.round(px * 1.3);
  };
  if (input.name) write(input.name, font.name, 700, INK);
  write(statsLine(input.distanceM, input.climbM), font.stats, 400, INK);
  write(BRAND, font.brand, 700, LINE);
  ctx.font = `400 ${font.credit}px ${FONT}`;
  ctx.fillStyle = MUTED;
  for (const line of wrap(ctx, cardAttribution(strip !== null), text.w, 2)) {
    ctx.fillText(line, text.x, y);
    y += Math.round(font.credit * 1.3);
  }
  if (layout.qr && input.qrLink) drawQr(ctx, layout.qr, input.qrLink);
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
  if (!blob) throw new Error("no image");
  return { blob, strip };
}
