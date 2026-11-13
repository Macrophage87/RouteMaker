/**
 * How old the map's data is, in one line under Settings' About (backlog item "Data that says how old it is",
 * 2026-11-13): "Map data from Nov 10, 2026. Places and racks from Oct 9, 2026."
 *
 * Two dates, because they move apart. The map (roads, levels, routing) is the server's: its build day comes with
 * GET /api/coverage (`core.api.map_data_date`), so a map swap shows without a front-end release. The places a rider
 * acts on (food, places to see, water and restrooms, repair stands, racks, trail mile markers) are files built into
 * the front end from an extract, dated in amenity-data/as-of.json by scripts/refresh_places.py, which runs after each
 * map rebuild (docs/OPERATIONS.md, "Refreshing the places after a map rebuild"). Their line says the oldest of them,
 * so it never claims a file is newer than it is. The barrier list is the api's and not a place, so it is left out.
 */
import AS_OF from "../amenity-data/as-of.json" with { type: "json" };
import { locale, t } from "./i18n.ts";

/** The snapshots the "Places and racks" date covers: as-of.json's names. */
export const PLACE_FILES = ["water-restrooms", "food", "places", "trail-miles", "bike-parking"] as const;

const DAY = /^\d{4}-\d{2}-\d{2}$/;

/** The oldest extract day among the place files, or null when the file names none. */
export function placesAsOf(doc: { extract?: Record<string, string> } = AS_OF): string | null {
  const days = PLACE_FILES.map((name) => doc.extract?.[name]).filter((day): day is string => typeof day === "string" && DAY.test(day));
  return days.length === PLACE_FILES.length ? [...days].sort()[0] : null;
}

/** The map's day from GET /api/coverage's properties, or null before a first build. */
export function mapDataDay(properties: Record<string, unknown> | null | undefined): string | null {
  const day = properties?.map_data;
  return typeof day === "string" && DAY.test(day) ? day : null;
}

/** "Nov 10, 2026" in the app's language. A calendar day, so read in UTC: it never shifts by the rider's zone. */
export function dayLabel(day: string, lang: string = locale()): string {
  return new Date(`${day}T00:00:00Z`).toLocaleDateString(lang, { timeZone: "UTC", month: "short", day: "numeric", year: "numeric" });
}

/** The About line, or "" with neither date. */
export function dataAgeSaid(mapDay: string | null, placesDay: string | null = placesAsOf()): string {
  if (mapDay && placesDay) return t("Map data from {map}. Places and racks from {places}.", { map: dayLabel(mapDay), places: dayLabel(placesDay) });
  if (placesDay) return t("Places and racks from {places}.", { places: dayLabel(placesDay) });
  if (mapDay) return t("Map data from {map}.", { map: dayLabel(mapDay) });
  return "";
}
