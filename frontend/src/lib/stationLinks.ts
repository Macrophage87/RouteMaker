/**
 * The station panel's links (OWNER-DECISIONS 441b-441f): a Metro station offers its
 * WMATA station page, a MARC Penn Line station the line's timetable page. Offered, never
 * followed by itself (441c): the station's card shows the link, and the rider decides.
 *
 * The WMATA slugs are a curated table (rail-data/wmata-station-slugs.json, a data file
 * like the stations themselves), keyed by the station's name in DC Open Data's
 * Metro Stations Regional layer (the map's own names; railStations.ts), never made up
 * from a name at runtime (441b). Every slug was checked once, read only, against
 * wmata.com on 2026-10-07 under the owner's permission (441f): each answered with its
 * station's page, a wrong slug answers 404. WMATA's own short names are the pattern
 * ("Rhode Island Av", "Naylor Rd", "U St"), which is why several differ from DC's.
 * stationLinks.test.ts holds the table to every Metro station the map draws.
 *
 * MARC: only the Penn Line is drawn (441e), so a Penn station offers the Penn Line
 * timetable; Union Station and New Carrollton, shared with Metro, offer both pages.
 * Names are in text only (trademarks; OWNER-DECISIONS 441).
 */
import { haversineM, type LonLat } from "./geo.ts";
import { visibleLines, type RailVisibility, type Station } from "./railStations.ts";

export const WMATA_STATION_BASE = "https://www.wmata.com/ridertools/station/";
export const MARC_PENN_TIMETABLE = "https://www.mta.maryland.gov/schedule/timetable/marc-penn";

/** DC Open Data's station name -> WMATA's station page slug (rail-data/wmata-station-slugs.json; railData.ts). */
export type StationSlugs = Readonly<Record<string, string>>;

/** The checked table as the fixture holds it; null when it does not fit (the links are then left off). */
export function parseStationSlugs(text: string): StationSlugs | null {
  try {
    const parsed = JSON.parse(text) as { slugs?: unknown };
    const slugs = parsed.slugs;
    if (!slugs || typeof slugs !== "object") return null;
    const entries = Object.entries(slugs as Record<string, unknown>);
    if (!entries.every(([, v]) => typeof v === "string" && /^[a-z0-9'-]+$/.test(v))) return null;
    return Object.fromEntries(entries) as Record<string, string>;
  } catch {
    return null;
  }
}

export interface StationLink {
  /** The link's short visible words (OWNER-DECISIONS 441q), shown beside the station's visible name. */
  text: string;
  /**
   * Its accessible name: the station, the page and the site, and that it leaves the map.
   * It starts with or holds the visible words, so a voice-control rider can say them
   * (WCAG 2.5.3, label in name).
   */
  label: string;
  href: string;
}

/** Said beside the links on a station's card: they leave the map, for another site. */
export const STATION_LINK_NOTE = "Opens in a new tab.";
export const WMATA_LINK_TEXT = "Station site";
export const MARC_LINK_TEXT = "MARC timetable";

/** "Dupont Circle station", but "Union Station" as it is. */
function stationWords(name: string): string {
  return /\bstation$/i.test(name.trim()) ? name.trim() : `${name.trim()} station`;
}

/** The pages a station's card offers: WMATA's for a Metro station, the Penn Line timetable for a MARC Penn one. */
export function stationLinks(station: Pick<Station, "name" | "metro" | "penn">, slugs: StationSlugs): StationLink[] {
  const links: StationLink[] = [];
  const slug = station.metro.length > 0 && Object.hasOwn(slugs, station.name) ? slugs[station.name] : undefined;
  if (slug) {
    links.push({
      text: WMATA_LINK_TEXT,
      label: `${stationWords(station.name)} site, WMATA, opens in a new tab`,
      href: `${WMATA_STATION_BASE}${slug}`,
    });
  }
  if (station.penn) {
    links.push({ text: MARC_LINK_TEXT, label: "MARC timetable, Penn Line, MTA Maryland, opens in a new tab", href: MARC_PENN_TIMETABLE });
  }
  return links;
}

/** The links as DOM, for a station's card and the road panel (a real list of real links). */
export function stationLinksElement(station: Pick<Station, "name" | "metro" | "penn">, slugs: StationSlugs): HTMLElement | null {
  const links = stationLinks(station, slugs);
  if (links.length === 0) return null;
  const root = document.createElement("div");
  root.className = "station-links";
  const list = document.createElement("ul");
  for (const link of links) {
    const item = document.createElement("li");
    const a = document.createElement("a");
    a.href = link.href;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.textContent = link.text;
    a.setAttribute("aria-label", link.label);
    item.append(a);
    list.append(item);
  }
  const note = document.createElement("p");
  note.className = "hint";
  note.textContent = STATION_LINK_NOTE;
  root.append(list, note);
  return root;
}

/** How near a spot a station is for the road panel to offer its pages: a short walk with a bike. */
export const STATION_NEAR_M = 400;

/**
 * The station shown on the map nearest a spot, within STATION_NEAR_M, if it offers a page:
 * the road panel's way to a station's links for a rider who does not use a pointer (441b,
 * keyboard reachable).
 */
export function stationNearSpot(
  stations: readonly Station[],
  visibility: RailVisibility,
  point: LonLat,
  slugs: StationSlugs,
  maxM: number = STATION_NEAR_M,
): { station: Station; distanceM: number } | null {
  let best: { station: Station; distanceM: number } | null = null;
  for (const station of stations) {
    if (visibleLines(station, visibility).length === 0 || stationLinks(station, slugs).length === 0) continue;
    const distanceM = haversineM(station.point, point);
    if (distanceM <= maxM && (!best || distanceM < best.distanceM)) best = { station, distanceM };
  }
  return best;
}
