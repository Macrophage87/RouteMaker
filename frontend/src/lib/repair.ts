/**
 * Bike repair stands and bike shops (v0.7.0, "Bike repair stands in Go"). The owner, 2026-10-14: "Another thing
 * that would be useful to have in GO is for bike repair stands ... They could probably get their own icon too";
 * "If you need some quick work done, have it show the nearest couple repair stands/bike shops"; "just the stands"
 * on the map.
 *
 * Both are in amenity-data/water-restrooms.json (scripts/build_water_restrooms.py: `rs` a public repair stand
 * with its kit, `bs` a bike shop), so the Repair chip works offline once the map has loaded the file. Go's
 * Repair chip (behind More) lists the nearest REPAIR_STANDS stands and REPAIR_SHOPS shops together, nearest
 * first, lettered as the other chips' lists; a stand says what it has ("Pump and tools"), a shop its hours and
 * "Closed now" when its OSM hours say so. Stands are drawn on the map with the Water and restrooms layer (a
 * wrench); shops never are.
 *
 * Plain data in, plain data out, so node --test runs all of it.
 */
import { formatDistance } from "./format.ts";
import { haversineM, type LonLat } from "./geo.ts";
import { hexToRgb, rasterise, type Raster, type Rgb } from "./stationIcons.ts";

export interface RepairPlace {
  /** The OSM element, "n123" or "w456". */
  id: string;
  kind: "stand" | "shop";
  lon: number;
  lat: number;
  name?: string;
  /** A stand's kit: "p" pump, "t" tools, "c" chain tool. */
  kit?: string;
  fee?: "yes" | "no";
  hours?: string;
  website?: string;
}

const text = (value: unknown): string | undefined => (typeof value === "string" && value.trim() ? value.trim() : undefined);

/** The stands and shops in the water file; null if it is not the file's shape. Water and restrooms are skipped. */
export function parseRepair(value: unknown): RepairPlace[] | null {
  const body = value as { points?: unknown } | null;
  if (!body || !Array.isArray(body.points)) return null;
  const out: RepairPlace[] = [];
  for (const raw of body.points as Array<Record<string, unknown>>) {
    if (!raw || typeof raw.id !== "string") continue;
    const { x: lon, y: lat } = raw;
    if (typeof lon !== "number" || typeof lat !== "number" || !Number.isFinite(lon) || !Number.isFinite(lat)) continue;
    const stand = typeof raw.rs === "string";
    const shop = raw.bs === 1;
    if (!stand && !shop) continue;
    const place: RepairPlace = { id: raw.id, kind: stand ? "stand" : "shop", lon, lat };
    const name = text(raw.n);
    if (name) place.name = name;
    if (stand) place.kit = (raw.rs as string).replace(/[^ptc]/g, "");
    if (raw.fee === "yes" || raw.fee === "no") place.fee = raw.fee;
    const hours = text(raw.h);
    if (hours) place.hours = hours;
    const website = text(raw.web);
    if (website && /^https?:\/\//i.test(website)) place.website = website;
    out.push(place);
  }
  return out;
}

/** Fetch and parse the file; null if it cannot be had (an empty list is "none known yet"). */
export async function loadRepair(
  url: string,
  fetcher: (url: string) => Promise<{ ok: boolean; json(): Promise<unknown> }> = (u) => fetch(u),
): Promise<RepairPlace[] | null> {
  try {
    const response = await fetcher(url);
    if (!response.ok) return null;
    return parseRepair(await response.json());
  } catch {
    return null;
  }
}

// --- Opening hours -----------------------------------------------------------

const DAYS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];

function dayList(spec: string): Set<number> | null {
  const out = new Set<number>();
  for (const part of spec.split(",")) {
    const range = /^(Mo|Tu|We|Th|Fr|Sa|Su)(?:-(Mo|Tu|We|Th|Fr|Sa|Su))?$/.exec(part.trim());
    if (!range) return null;
    const from = DAYS.indexOf(range[1]);
    const to = DAYS.indexOf(range[2] ?? range[1]);
    for (let d = from; ; d = (d + 1) % 7) {
      out.add(d);
      if (d === to) break;
    }
  }
  return out;
}

function minutes(hhmm: string): number | null {
  const m = /^(\d{1,2}):(\d{2})$/.exec(hhmm);
  if (!m) return null;
  const v = Number(m[1]) * 60 + Number(m[2]);
  return v <= 24 * 60 ? v : null;
}

/**
 * Whether OSM `opening_hours` says the place is open at `at` (its local clock): true, false, or null when the
 * hours use more than this reads (months, holidays, sunrise, week numbers, comments), so nothing is claimed.
 * Read: "24/7"; rules split on ";", each days ("Mo-Fr", "Sa,Su"; none means every day) and times
 * ("10:00-18:00", several with ","), or "off"/"closed"; a later rule for a day replaces an earlier one, as the
 * OSM wiki's Key:opening_hours specification has it; a time past midnight ("22:00-02:00") runs into the next day.
 */
export function openNow(hours: string, at: Date): boolean | null {
  const spec = hours.trim();
  if (spec === "24/7") return true;
  const byDay: Array<Array<[number, number]> | undefined> = new Array(7).fill(undefined);
  for (const rawRule of spec.split(";")) {
    const rule = rawRule.trim();
    if (!rule) continue;
    const m = /^((?:(?:Mo|Tu|We|Th|Fr|Sa|Su)(?:-(?:Mo|Tu|We|Th|Fr|Sa|Su))?,?)+)?\s*(.*)$/.exec(rule);
    if (!m) return null;
    const days = m[1] ? dayList(m[1].replace(/,$/, "")) : new Set([0, 1, 2, 3, 4, 5, 6]);
    if (!days) return null;
    const times = m[2].trim();
    let spans: Array<[number, number]>;
    if (times === "off" || times === "closed") spans = [];
    else {
      spans = [];
      for (const part of times.split(",")) {
        const t = /^(\d{1,2}:\d{2})-(\d{1,2}:\d{2})$/.exec(part.trim());
        if (!t) return null;
        const from = minutes(t[1]);
        const to = minutes(t[2]);
        if (from === null || to === null) return null;
        spans.push([from, to]);
      }
    }
    for (const d of days) byDay[d] = spans;
  }
  const day = at.getDay();
  const now = at.getHours() * 60 + at.getMinutes();
  const today = byDay[day] ?? [];
  if (today.some(([from, to]) => (to > from ? now >= from && now < to : now >= from))) return true;
  const yesterday = byDay[(day + 6) % 7] ?? [];
  return yesterday.some(([from, to]) => to <= from && now < to);
}

// --- Words -------------------------------------------------------------------

const KIT_WORDS: Record<string, string> = { p: "pump", t: "tools", c: "chain tool" };

/** A stand's kit in words: "Pump and tools", "Pump, tools and chain tool"; "" when none is mapped. */
export function kitWords(kit: string | undefined): string {
  const parts = [...(kit ?? "")].map((k) => KIT_WORDS[k]).filter(Boolean);
  if (parts.length === 0) return "";
  const list = parts.length === 1 ? parts[0] : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
  return list.charAt(0).toUpperCase() + list.slice(1);
}

/** "Repair stand", "Repair stand, Union Station", "Bike shop, Spokes Etc". */
export function repairTitle(p: RepairPlace): string {
  const kind = p.kind === "stand" ? "Repair stand" : "Bike shop";
  return p.name ? `${kind}, ${p.name}` : kind;
}

/** A stand's kit and fee, or a shop's hours (with "Closed now." or "Open now." when its hours can be read). */
export function repairDetails(p: RepairPlace, at: Date): string[] {
  const out: string[] = [];
  if (p.kind === "stand") {
    const kit = kitWords(p.kit);
    out.push(kit ? `${kit}.` : "Tools not listed.");
    if (p.fee === "no") out.push("Free.");
    if (p.fee === "yes") out.push("Fee to use.");
    return out;
  }
  if (!p.hours) return ["Hours not listed."];
  const open = openNow(p.hours, at);
  if (open === false) out.push("Closed now.");
  if (open === true) out.push("Open now.");
  out.push(p.hours === "24/7" ? "Open 24/7." : `Hours: ${p.hours}.`);
  return out;
}

export const REPAIR_STANDS = 2;
export const REPAIR_SHOPS = 2;

export interface RepairNearby {
  place: RepairPlace;
  /** Straight line from where the search was from, metres. */
  metres: number;
}

/** The nearest `stands` repair stands and `shops` bike shops to `from`, together, nearest first. */
export function nearestRepair(from: LonLat, places: readonly RepairPlace[], stands = REPAIR_STANDS, shops = REPAIR_SHOPS): RepairNearby[] {
  const ranked = places.map((place) => ({ place, metres: haversineM(from, [place.lon, place.lat]) })).sort((a, b) => a.metres - b.metres || a.place.id.localeCompare(b.place.id));
  const pick = (kind: RepairPlace["kind"], n: number) => ranked.filter((r) => r.place.kind === kind).slice(0, n);
  return [...pick("stand", stands), ...pick("shop", shops)].sort((a, b) => a.metres - b.metres || a.place.id.localeCompare(b.place.id));
}

/** One line of the list: "Repair stand, Union Station: 0.3 mi (0.5 km) away. Pump and tools. Free." */
export function repairText(item: RepairNearby, at: Date): string {
  return [`${repairTitle(item.place)}: ${formatDistance(item.metres)} away.`, ...repairDetails(item.place, at)].join(" ");
}

export const REPAIR_NONE = "No repair stands or bike shops known yet: they arrive with the next map data update.";
export const REPAIR_UNAVAILABLE = "Repair stands and bike shops are unavailable for now; try again shortly.";
export const REPAIR_NO_ORIGIN = "Your location is not known yet. Press Locate, or move the map to where you are.";
export const REPAIR_NOTE = "Straight-line distances. From OpenStreetMap: check the hours before you count on them.";

/** The status line once the list is in. */
export function repairFoundSaid(items: readonly RepairNearby[], fromHere: boolean): string {
  const from = fromHere ? "you" : "the map's center";
  if (items.length === 0) return REPAIR_NONE;
  return `The ${items.length} nearest repair stands and bike shops to ${from}, nearest first: ${repairTitle(items[0].place)}, ${formatDistance(items[0].metres)} away.`;
}

// --- The map's icon (stands only) ---------------------------------------------

export const REPAIR_SOURCE_ID = "repair-stands";
export const REPAIR_LAYER = "repair-stands";
export const REPAIR_ICON_ID = "repair-stand";
export const REPAIR_COLOUR = "#334155";
export const REPAIR_ICON_PX = 18;

/** Whether (x, y) is on a wrench drawn corner to corner in a box of `size`: a ring head at the top right, a handle. */
function inWrench(x: number, y: number, size: number): boolean {
  const s = size;
  const hx = s * 0.66;
  const hy = s * 0.34;
  const r = s * 0.2;
  const d = Math.hypot(x - hx, y - hy);
  // The head: a ring, open towards the top right (the jaw).
  if (d <= r && d >= r * 0.45 && !(x - hx > 0 && hy - y > 0 && Math.abs(x - hx - (hy - y)) < r * 0.45)) return true;
  // The handle: a bar from the head to the bottom left.
  const ax = s * 0.22;
  const ay = s * 0.78;
  const dx = hx - ax;
  const dy = hy - ay;
  const t = Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)));
  return Math.hypot(x - (ax + t * dx), y - (ay + t * dy)) <= s * 0.075 && t < 0.8;
}

/** The stand's icon: a slate rounded square with a white edge and a white wrench. */
export function repairIcon(pixelRatio = 2, cssSize = REPAIR_ICON_PX): Raster {
  const size = Math.round(cssSize * pixelRatio);
  const edge = 1.5 * pixelRatio;
  const slate = hexToRgb(REPAIR_COLOUR);
  const white = hexToRgb("#ffffff");
  const radius = size * 0.22;
  const inBox = (x: number, y: number, inset: number) => {
    const lo = inset;
    const hi = size - inset;
    if (x < lo || x > hi || y < lo || y > hi) return false;
    const cx = Math.min(Math.max(x, lo + radius), hi - radius);
    const cy = Math.min(Math.max(y, lo + radius), hi - radius);
    return Math.hypot(x - cx, y - cy) <= radius;
  };
  return rasterise(size, pixelRatio, (x, y): Rgb | null => {
    if (!inBox(x, y, 0)) return null;
    if (!inBox(x, y, edge)) return white;
    return inWrench(x, y, size) ? white : slate;
  });
}

export function repairGeoJson(places: readonly RepairPlace[]): object {
  return {
    type: "FeatureCollection",
    features: places
      .filter((p) => p.kind === "stand")
      .map((p) => ({ type: "Feature", properties: { id: p.id }, geometry: { type: "Point", coordinates: [p.lon, p.lat] } })),
  };
}

/** The stands' layer, from the water layer's zoom in. */
export function repairLayer(minzoom: number): Record<string, unknown> {
  return {
    id: REPAIR_LAYER,
    type: "symbol",
    source: REPAIR_SOURCE_ID,
    minzoom,
    layout: {
      "icon-image": REPAIR_ICON_ID,
      "icon-size": ["interpolate", ["linear"], ["zoom"], minzoom, 0.7, 15, 1, 18, 1.2],
      "icon-allow-overlap": true,
      "icon-ignore-placement": true,
    },
  };
}
