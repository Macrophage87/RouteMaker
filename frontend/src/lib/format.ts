/**
 * Numbers as the panel, the notices and the GPX export show them: US customary
 * first, metric in brackets. The owner, 2026-09-27: "This is a US-based map, so
 * people are more used to miles over km. Have both, but metric should be
 * secondary." - and 2026-09-29, "The US customary unit change wasn't made
 * yet." (OWNER-DECISIONS 85). The one formatter: nothing else writes a unit.
 * Stored values and API fields stay metric.
 */

const DASH = "–";
export const METRES_PER_MILE = 1609.344;
export const FEET_PER_METRE = 3.28084;
export const KMH_PER_MPH = 1.609344;

/**
 * Below this a distance is given in feet (and metres): a tenth of a mile, 528
 * ft (161 m), where "0.1 mi" would stop saying anything.
 */
export const FEET_BELOW_M = METRES_PER_MILE / 10;

/** How far apart a start and an end may be for the hills slider to look for climbs (src/core/api.py). */
export const SEEK_MAX_SPAN_M = 50_000;

function usable(value: number): boolean {
  return Number.isFinite(value) && value >= 0;
}

/** Whole units, or to the nearest ten from a hundred up: "500 ft (150 m)", not "499 ft (152 m)". */
function roundShort(value: number): number {
  return value >= 100 ? Math.round(value / 10) * 10 : Math.round(value);
}

/** Miles to one place, as the distance shows them and a file name carries them: "4.7". */
export function milesFigure(metres: number): string {
  return (metres / METRES_PER_MILE).toFixed(1);
}

/** "4.7 mi (7.6 km)"; below a tenth of a mile "500 ft (150 m)". */
export function formatDistance(metres: number): string {
  if (!usable(metres)) return DASH;
  if (metres < FEET_BELOW_M) {
    return `${roundShort(metres * FEET_PER_METRE)} ft (${roundShort(metres)} m)`;
  }
  return `${milesFigure(metres)} mi (${(metres / 1000).toFixed(1)} km)`;
}

/** A round figure for a limit or a span, in whole units: "31 mi (50 km)". */
export function formatRoughDistance(metres: number): string {
  if (!usable(metres)) return DASH;
  return `${Math.round(metres / METRES_PER_MILE)} mi (${Math.round(metres / 1000)} km)`;
}

export function formatDuration(seconds: number): string {
  if (!usable(seconds)) return DASH;
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `${hours} h ${String(minutes % 60).padStart(2, "0")} min`;
}

/** A climb, a descent or an elevation: "266 ft (81 m)". */
export function formatClimb(metres: number): string {
  if (!usable(metres)) return DASH;
  return `${Math.round(metres * FEET_PER_METRE)} ft (${Math.round(metres)} m)`;
}

/** A speed from km/h: "12 mph (19 km/h)". */
export function formatSpeed(kmh: number): string {
  if (!usable(kmh)) return DASH;
  return `${Math.round(kmh / KMH_PER_MPH)} mph (${Math.round(kmh)} km/h)`;
}

/** A whole number of seconds, for "trying again in ...": "1 second", "5 seconds". */
export function formatSeconds(seconds: number): string {
  return seconds === 1 ? "1 second" : `${seconds} seconds`;
}
