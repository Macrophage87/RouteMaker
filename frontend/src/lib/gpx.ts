/**
 * GPX in and out, in the browser: nothing here touches the network.
 *
 * Reading is a small hand-written XML scanner rather than DOMParser, for two
 * reasons: it runs in a Web Worker (DOMParser does not exist there), so a
 * 20 MB file does not hold the page, and node --test can run it. It reads only
 * what the planner needs - track, route and waypoint positions and names - and
 * refuses what PLAN.md's import rules refuse (Moderation and abuse limits):
 * anything but well-formed GPX 1.0 or 1.1, a file over 20 MB or 100,000
 * points, and any DOCTYPE, which is where XML entity attacks live (the server
 * side uses defusedxml for the same reason).
 *
 * Writing builds GPX 1.1 from the planned route alone (PLAN.md, Formats and
 * the export cleanliness rules): the application as creator, no author, no
 * timestamp (a signed-out plan has no stored version time and the clock would
 * make the file differ run to run), fixed coordinate precision and a fixed
 * attribute order, so the same route always gives the same bytes. The
 * OpenStreetMap credit sits in metadata/copyright with no year (PLAN.md:42)
 * and the route's full attribution in metadata/desc.
 */
import type { LonLat } from "./geo.ts";

export const GPX_NS_11 = "http://www.topografix.com/GPX/1/1";
export const GPX_NS_10 = "http://www.topografix.com/GPX/1/0";

/** PLAN.md, Moderation and abuse limits: GPX uploads. The same caps apply here. */
export const MAX_GPX_BYTES = 20 * 1024 * 1024;
export const MAX_GPX_POINTS = 100_000;

export interface GpxPoint {
  lon: number;
  lat: number;
  name?: string;
}

export interface GpxTrack {
  name?: string;
  segments: LonLat[][];
}

export interface GpxRoute {
  name?: string;
  type?: string;
  /** rte/cmt: in a RouteMaker export, the sliders the route was planned with (PLAN_DIALS_PREFIX). */
  cmt?: string;
  points: GpxPoint[];
}

export interface GpxFile {
  version: "1.0" | "1.1";
  creator?: string;
  name?: string;
  tracks: GpxTrack[];
  routes: GpxRoute[];
  waypoints: GpxPoint[];
  /** Points dropped for an unusable lat or lon. */
  skipped: number;
}

export class GpxError extends Error {
  readonly code: "not-gpx" | "malformed" | "doctype" | "too-big" | "too-many-points";
  constructor(code: GpxError["code"], message: string) {
    super(message);
    this.code = code;
    this.name = "GpxError";
  }
}

const ENTITIES: Record<string, string> = { lt: "<", gt: ">", amp: "&", quot: '"', apos: "'" };

function decodeEntities(text: string): string {
  if (!text.includes("&")) return text;
  return text.replace(/&(#x[0-9a-fA-F]+|#[0-9]+|[a-zA-Z]+);/g, (whole, ref: string) => {
    if (ref[0] === "#") {
      const code = ref[1] === "x" ? parseInt(ref.slice(2), 16) : parseInt(ref.slice(1), 10);
      return Number.isFinite(code) && code > 0 && code <= 0x10ffff ? String.fromCodePoint(code) : whole;
    }
    const named = ENTITIES[ref];
    if (named === undefined) throw new GpxError("malformed", `Unknown XML entity &${ref};.`);
    return named;
  });
}

const ATTRIBUTE = /([^\s=]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/g;

const NO_ATTRIBUTES: ReadonlyMap<string, string> = new Map();

function parseAttributes(body: string): ReadonlyMap<string, string> {
  if (!body.includes("=")) return NO_ATTRIBUTES;
  const attributes = new Map<string, string>();
  ATTRIBUTE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = ATTRIBUTE.exec(body)) !== null) {
    attributes.set(match[1], decodeEntities(match[2] ?? match[3] ?? ""));
  }
  return attributes;
}

/** The index of the `>` closing a tag that starts at `from`, skipping quoted values. */
function tagEnd(text: string, from: number): number {
  const first = text.indexOf(">", from);
  if (first < 0) return -1;
  // Nearly every tag has no quote before its first ">", or balanced ones.
  let quotes = 0;
  let mixed = false;
  for (let i = from; i < first; i += 1) {
    const c = text.charCodeAt(i);
    if (c === 34) quotes += 1;
    else if (c === 39) mixed = true;
  }
  if (!mixed && quotes % 2 === 0) return first;
  let quote = "";
  for (let i = from; i < text.length; i += 1) {
    const c = text[i];
    if (quote) {
      if (c === quote) quote = "";
    } else if (c === '"' || c === "'") {
      quote = c;
    } else if (c === ">") {
      return i;
    }
  }
  return -1;
}

function coordinate(value: string | undefined, limit: number): number | null {
  if (value === undefined || value.trim() === "") return null;
  const n = Number(value);
  return Number.isFinite(n) && Math.abs(n) <= limit ? n : null;
}

interface Open {
  qname: string;
  /** The element's GPX local name, or null for an element from another namespace. */
  gpx: string | null;
  scope: Map<string, string>;
}

/** Elements whose text the reader keeps. */
const TEXT_ELEMENTS = new Set(["name", "type", "cmt"]);

/**
 * Read a GPX document. Throws GpxError for anything that is not well-formed
 * GPX 1.0 or 1.1 within the caps.
 */
export function parseGpx(text: string): GpxFile {
  if (text.length > MAX_GPX_BYTES) {
    throw new GpxError("too-big", "The file is larger than 20 MB.");
  }
  const stack: Open[] = [];
  let file = null as GpxFile | null;
  let rootClosed = false;
  let points = 0;
  let track: GpxTrack | null = null;
  let segment: LonLat[] | null = null;
  let route: GpxRoute | null = null;
  let point: GpxPoint | null = null;
  // Set inside the helpers below, so declared without narrowing to null.
  let capture = null as string | null;

  const countPoint = () => {
    points += 1;
    if (points > MAX_GPX_POINTS) {
      throw new GpxError("too-many-points", `The file has more than ${MAX_GPX_POINTS.toLocaleString("en-US")} points.`);
    }
  };

  const parentGpx = () => (stack.length ? stack[stack.length - 1].gpx : null);

  const outsideRoot = (chunk: string) => {
    if (chunk.trim() && (file === null || rootClosed)) {
      throw new GpxError("malformed", "The file has text outside its GPX element.");
    }
  };

  const open = (qname: string, attributes: ReadonlyMap<string, string>): Open => {
    const outer = stack.length ? stack[stack.length - 1].scope : new Map<string, string>();
    let scope = outer;
    for (const [key, value] of attributes) {
      if (key === "xmlns" || key.startsWith("xmlns:")) {
        if (scope === outer) scope = new Map(outer);
        scope.set(key === "xmlns" ? "" : key.slice(6), value);
      }
    }
    const colon = qname.indexOf(":");
    const prefix = colon < 0 ? "" : qname.slice(0, colon);
    const local = colon < 0 ? qname : qname.slice(colon + 1);
    const ns = scope.get(prefix);
    const gpx = ns === GPX_NS_11 || ns === GPX_NS_10 ? local : null;
    return { qname, gpx, scope };
  };

  const start = (element: Open, attributes: ReadonlyMap<string, string>) => {
    const parent = parentGpx();
    if (stack.length === 0) {
      if (file !== null || rootClosed) throw new GpxError("malformed", "The file has more than one root element.");
      const version = attributes.get("version");
      if (element.gpx !== "gpx" || (version !== "1.0" && version !== "1.1")) {
        throw new GpxError("not-gpx", "This is not a GPX 1.0 or 1.1 file.");
      }
      const expected = version === "1.1" ? GPX_NS_11 : GPX_NS_10;
      if (element.scope.get(element.qname.includes(":") ? element.qname.split(":")[0] : "") !== expected) {
        throw new GpxError("not-gpx", "This is not a GPX 1.0 or 1.1 file.");
      }
      file = { version, creator: attributes.get("creator"), tracks: [], routes: [], waypoints: [], skipped: 0 };
      return;
    }
    const current = file as GpxFile | null;
    if (!current || element.gpx === null) return;
    const name = element.gpx;
    if (name === "trk" && parent === "gpx") {
      track = { segments: [] };
      current.tracks.push(track);
    } else if (name === "trkseg" && parent === "trk" && track) {
      segment = [];
      track.segments.push(segment);
    } else if (name === "rte" && parent === "gpx") {
      route = { points: [] };
      current.routes.push(route);
    } else if (
      (name === "trkpt" && parent === "trkseg") ||
      (name === "rtept" && parent === "rte") ||
      (name === "wpt" && parent === "gpx")
    ) {
      countPoint();
      const lat = coordinate(attributes.get("lat"), 90);
      const lon = coordinate(attributes.get("lon"), 180);
      if (lat === null || lon === null) {
        current.skipped += 1;
        point = null;
        return;
      }
      if (name === "trkpt") {
        segment?.push([lon, lat]);
      } else {
        point = { lon, lat };
        if (name === "rtept") route?.points.push(point);
        else current.waypoints.push(point);
      }
    } else if (TEXT_ELEMENTS.has(name)) {
      capture = "";
    }
  };

  const end = (element: Open) => {
    const current = file as GpxFile | null;
    const name = element.gpx;
    if (stack.length === 0) {
      rootClosed = true;
      return;
    }
    if (!current || name === null) return;
    const parent = parentGpx();
    if (TEXT_ELEMENTS.has(name) && capture !== null) {
      const value = capture.trim();
      capture = null;
      if (!value) return;
      if (name === "name") {
        if ((parent === "metadata" && stack.length === 2) || (parent === "gpx" && stack.length === 1)) current.name ??= value;
        else if (parent === "trk" && track) track.name = value;
        else if (parent === "rte" && route) route.name = value;
        else if ((parent === "rtept" || parent === "wpt") && point) point.name = value;
      } else if (name === "type" && parent === "rte" && route) {
        route.type = value;
      } else if (name === "cmt" && parent === "rte" && route) {
        route.cmt = value;
      }
      return;
    }
    if (name === "trk") track = null;
    else if (name === "trkseg") segment = null;
    else if (name === "rte") route = null;
    else if (name === "rtept" || name === "wpt") point = null;
  };

  let i = 0;
  const n = text.length;
  if (text.charCodeAt(0) === 0xfeff) i = 1;
  while (i < n) {
    const lt = text.indexOf("<", i);
    const chunk = text.slice(i, lt < 0 ? n : lt);
    if (chunk) {
      if (stack.length === 0) outsideRoot(chunk);
      else if (capture !== null) capture += decodeEntities(chunk);
      else if (chunk.includes("&")) decodeEntities(chunk);
    }
    if (lt < 0) break;
    if (text.startsWith("<!--", lt)) {
      const close = text.indexOf("-->", lt + 4);
      if (close < 0) throw new GpxError("malformed", "The file ends inside a comment.");
      i = close + 3;
      continue;
    }
    if (text.startsWith("<![CDATA[", lt)) {
      const close = text.indexOf("]]>", lt + 9);
      if (close < 0 || stack.length === 0) throw new GpxError("malformed", "The file has a broken CDATA section.");
      if (capture !== null) capture += text.slice(lt + 9, close);
      i = close + 3;
      continue;
    }
    if (text.startsWith("<!", lt)) {
      // DOCTYPE, ENTITY and the rest of the DTD: refused, never expanded.
      throw new GpxError("doctype", "GPX files with a DOCTYPE are not accepted.");
    }
    if (text.startsWith("<?", lt)) {
      const close = text.indexOf("?>", lt + 2);
      if (close < 0) throw new GpxError("malformed", "The file ends inside a processing instruction.");
      i = close + 2;
      continue;
    }
    const gt = tagEnd(text, lt + 1);
    if (gt < 0) throw new GpxError("malformed", "The file ends inside a tag.");
    const body = text.slice(lt + 1, gt);
    i = gt + 1;
    if (body[0] === "/") {
      const qname = body.slice(1).trim();
      const top = stack.pop();
      if (!top || top.qname !== qname) throw new GpxError("malformed", "The file's tags do not match up.");
      end(top);
      continue;
    }
    const selfClosing = body.endsWith("/");
    const inner = selfClosing ? body.slice(0, -1) : body;
    const nameEnd = inner.search(/[\s]/);
    const qname = nameEnd < 0 ? inner : inner.slice(0, nameEnd);
    if (!qname || !/^[A-Za-z_][\w.:-]*$/.test(qname)) throw new GpxError("malformed", "The file has a broken tag.");
    const attributes = parseAttributes(nameEnd < 0 ? "" : inner.slice(nameEnd));
    const element = open(qname, attributes);
    start(element, attributes);
    if (selfClosing) {
      end(element);
    } else {
      stack.push(element);
    }
  }
  if (stack.length || !file) {
    throw new GpxError(file ? "malformed" : "not-gpx", file ? "The file ends before its GPX element does." : "This is not a GPX file.");
  }
  return file;
}

// ---------------------------------------------------------------------------
// Writing

/** The credit GPX 1.1 metadata/copyright carries (PLAN.md:41-42). */
export const COPYRIGHT_AUTHOR = "OpenStreetMap contributors";
export const COPYRIGHT_LICENSE = "https://opendatacommons.org/licenses/odbl/1-0/";
export const OSM_COPYRIGHT_PAGE = "https://www.openstreetmap.org/copyright";
export const CREATOR = "RouteMaker";
/** rte/type of an exported plan, so the file reopens with its ride type. */
export const PLAN_TYPE_PREFIX = "routemaker:";
/**
 * rte/cmt of an exported plan: the sliders it was planned with, as
 * "routemaker:stress=50;hills=-50;when=weekend", so the file reopens with them.
 */
export const PLAN_DIALS_PREFIX = "routemaker:";

/** The sliders an export carries (dials.ts, Dials; `when` as the route was planned). */
export interface ExportDials {
  stress: number;
  hills: number;
  when?: string | null;
  carrying?: string | null;
  assist?: boolean;
}

export function dialsComment(dials: ExportDials): string {
  const parts = [`stress=${Math.round(dials.stress)}`, `hills=${Math.round(dials.hills)}`];
  if (dials.when) parts.push(`when=${dials.when}`);
  if (dials.carrying) parts.push(`carrying=${dials.carrying}`);
  if (dials.assist) parts.push("assist=1");
  return PLAN_DIALS_PREFIX + parts.join(";");
}

/** The fields of a dials comment, or null for any other comment. Values are checked by the caller (dials.ts). */
export function parseDialsComment(cmt: string | undefined): Record<string, string> | null {
  if (!cmt || !cmt.startsWith(PLAN_DIALS_PREFIX)) return null;
  const fields: Record<string, string> = {};
  for (const part of cmt.slice(PLAN_DIALS_PREFIX.length).split(";")) {
    const eq = part.indexOf("=");
    if (eq > 0) fields[part.slice(0, eq).trim()] = part.slice(eq + 1).trim();
  }
  return "stress" in fields || "hills" in fields ? fields : null;
}

export interface GpxExport {
  /** The route's name, e.g. "Group Ride route, 7.6 mi (12.3 km)". */
  name: string;
  /** One line about the ride: type, distance, climb. */
  description: string;
  /** The route answer's attribution strings. */
  attribution: readonly string[];
  /** The ride type's id, written into rte/type. */
  preset: string;
  /** The sliders the route was planned with, written into rte/cmt; left out when unknown. */
  dials?: ExportDials;
  /** The ride type and sliders in words, written into rte/desc. */
  rideText?: string;
  /** The route description (plain text, a line to an entry), written into rte/desc after rideText. */
  routeText?: string;
  /** The plan's own points: start, vias, end. */
  planPoints: readonly LonLat[];
  /** The route line. */
  geometry: readonly LonLat[];
}

function escapeXml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    // Characters XML 1.0 cannot carry at all.
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f￾￿]/g, "");
}

function position([lon, lat]: LonLat): string {
  return `lat="${lat.toFixed(6)}" lon="${lon.toFixed(6)}"`;
}

export function planPointName(index: number, count: number): string {
  if (index === 0) return "Start";
  if (index === count - 1) return "End";
  return `Stop ${index}`;
}

/**
 * The GPX 1.1 document for a planned route. Children are in the order the
 * GPX 1.1 schema's sequences require (metadata, wpt, rte, trk; name, desc,
 * copyright, link, keywords in metadata).
 */
export function writeGpx(input: GpxExport): string {
  const lines: string[] = [];
  const credit = input.attribution.length ? input.attribution.join("; ") : `© ${COPYRIGHT_AUTHOR}, ODbL`;
  lines.push('<?xml version="1.0" encoding="UTF-8"?>');
  lines.push(
    `<gpx xmlns="${GPX_NS_11}" version="1.1" creator="${CREATOR}"` +
      ` xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"` +
      ` xsi:schemaLocation="${GPX_NS_11} http://www.topografix.com/GPX/1/1/gpx.xsd">`,
  );
  lines.push("  <metadata>");
  lines.push(`    <name>${escapeXml(input.name)}</name>`);
  lines.push(`    <desc>${escapeXml(`Route data: ${credit}.`)}</desc>`);
  lines.push(`    <copyright author="${escapeXml(COPYRIGHT_AUTHOR)}">`);
  lines.push(`      <license>${COPYRIGHT_LICENSE}</license>`);
  lines.push("    </copyright>");
  lines.push(`    <link href="${OSM_COPYRIGHT_PAGE}">`);
  lines.push(`      <text>© ${escapeXml(COPYRIGHT_AUTHOR)}</text>`);
  lines.push("    </link>");
  lines.push("  </metadata>");
  if (input.planPoints.length >= 2) {
    lines.push("  <rte>");
    lines.push(`    <name>${escapeXml(input.name)}</name>`);
    if (input.dials) lines.push(`    <cmt>${escapeXml(dialsComment(input.dials))}</cmt>`);
    const routeDesc = [input.rideText, input.routeText].filter((part) => part).join("\n\n");
    if (routeDesc) lines.push(`    <desc>${escapeXml(routeDesc)}</desc>`);
    lines.push(`    <type>${escapeXml(PLAN_TYPE_PREFIX + input.preset)}</type>`);
    input.planPoints.forEach((p, index) => {
      lines.push(`    <rtept ${position(p)}>`);
      lines.push(`      <name>${planPointName(index, input.planPoints.length)}</name>`);
      lines.push("    </rtept>");
    });
    lines.push("  </rte>");
  }
  lines.push("  <trk>");
  lines.push(`    <name>${escapeXml(input.name)}</name>`);
  lines.push(`    <desc>${escapeXml(input.description)}</desc>`);
  lines.push("    <type>cycling</type>");
  lines.push("    <trkseg>");
  for (const p of input.geometry) lines.push(`      <trkpt ${position(p)}/>`);
  lines.push("    </trkseg>");
  lines.push("  </trk>");
  lines.push("</gpx>");
  return `${lines.join("\n")}\n`;
}
