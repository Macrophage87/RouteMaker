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
/** The words for the units a rider types in (the target distance, the system weight). */
export const MILES_WORD = "miles";
export const POUNDS_WORD = "pounds";
export const FEET_PER_METRE = 3.28084;
export const KMH_PER_MPH = 1.609344;

/**
 * Below this a distance is given in feet (and metres): a tenth of a mile, 528
 * ft (161 m), where "0.1 mi" would stop saying anything.
 */
export const FEET_BELOW_M = METRES_PER_MILE / 10;

/** How far apart a start and an end may be for the hills slider to look for climbs (src/core/routing.py). */
export const SEEK_MAX_SPAN_M = 50_000;

/** How far apart a start and an end may be for the hills slider to weigh alternatives when avoiding hills (src/core/routing.py). */
export const AVOID_MAX_SPAN_M = 25_000;

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

/**
 * What a rider may type, miles first, kilometres in brackets, as a rule says it:
 * "0.7 to 621 miles (1 to 1,000 km)" (the a11y review's N3).
 */
export function milesRange(minMiles: number, maxMiles: number, minM: number, maxM: number): string {
  const km = (m: number) => Math.round(m / 1000).toLocaleString("en-US");
  return `${minMiles} to ${maxMiles} ${MILES_WORD} (${km(minM)} to ${km(maxM)} km)`;
}

/**
 * A stretch of the route, as the API's description words one (src/routemaker/describe.py
 * range_words): "1.1 to 1.8 mi (1.7 to 2.9 km)", miles to a tenth and kilometres to a tenth in
 * brackets; a short one in feet.
 */
export function formatMileRange(fromM: number, toM: number): string {
  const mi = (m: number) => (m / METRES_PER_MILE).toFixed(1);
  const km = (m: number) => (m / 1000).toFixed(1);
  // Under a tenth of a mile, describe.py range_words' feet rule: where it starts and how long, in feet
  // ("1.2 mi (1.9 km), for 300 ft (91 m)"). Also where both ends round to the same tenth, which
  // range_words does not check, so "0.6 to 0.6 mi" is never said.
  if (toM - fromM < FEET_BELOW_M || mi(fromM) === mi(toM)) {
    const length = toM - fromM;
    const feet = length * FEET_PER_METRE;
    const ft = feet >= 100 ? Math.round(feet / 10) * 10 : Math.round(feet);
    return `${mi(fromM)} mi (${km(fromM)} km), for ${ft} ft (${Math.round(length)} m)`;
  }
  return `${mi(fromM)} to ${mi(toM)} mi (${km(fromM)} to ${km(toM)} km)`;
}

/** "55 to 1,543 pounds (25 to 700 kg)": a weight range, pounds first. */
export function poundsRange(minLb: number, maxLb: number, minKg: number, maxKg: number): string {
  return `${minLb} to ${maxLb} ${POUNDS_WORD} (${minKg} to ${maxKg} kg)`;
}

/** "4.7 mi (7.6 km)"; below a tenth of a mile "500 ft (150 m)". */
export function formatDistance(metres: number): string {
  if (!usable(metres)) return DASH;
  if (metres < FEET_BELOW_M) {
    return `${roundShort(metres * FEET_PER_METRE)} ft (${roundShort(metres)} m)`;
  }
  return `${milesFigure(metres)} mi (${(metres / 1000).toFixed(1)} km)`;
}

/**
 * A station's distance from where the rider is (the nearest-stations lists, OWNER-DECISIONS 466a):
 * miles to a tenth with the metres in brackets to the nearest ten while under a kilometre,
 * "0.2 mi (320 m)", then kilometres, "1.8 mi (2.9 km)"; below a tenth of a mile feet first,
 * "490 ft (150 m)".
 */
export function formatStationDistance(metres: number): string {
  if (!usable(metres)) return "distance unknown";
  if (metres < FEET_BELOW_M) {
    const feet = metres >= 30 ? Math.round((metres * FEET_PER_METRE) / 10) * 10 : Math.round(metres * FEET_PER_METRE);
    return `${feet} ft (${roundShort(metres)} m)`;
  }
  const metric = metres < 995 ? `${Math.round(metres / 10) * 10} m` : `${(metres / 1000).toFixed(1)} km`;
  return `${milesFigure(metres)} mi (${metric})`;
}

/**
 * A radius said aloud as a friendly figure ("Use my location", OWNER-DECISIONS
 * 395): below a tenth of a mile, the nearest 10 ft (at least 10), so 15 m is
 * "50 ft (15 m)" and not a falsely precise "49 ft"; miles from there on.
 */
export function formatRadius(metres: number): string {
  if (!usable(metres) || metres >= FEET_BELOW_M) return formatDistance(metres);
  const feet = Math.max(10, Math.round((metres * FEET_PER_METRE) / 10) * 10);
  const metric = metres >= 100 ? Math.round(metres / 10) * 10 : Math.max(1, Math.round(metres));
  return `${feet} ft (${metric} m)`;
}

/**
 * A set distance in whole feet, metres in brackets, whatever its size: "1,000 ft (305 m)". For a figure
 * chosen in feet (the water list's reach), which formatDistance would say as "0.2 mi (0.3 km)".
 */
export function formatFeet(metres: number): string {
  const feet = Math.round(metres * FEET_PER_METRE);
  return `${feet.toLocaleString("en-US")} ft (${Math.round(metres)} m)`;
}

/**
 * A place on a chart's distance axis, miles first, kilometres in brackets, short enough to label a tick:
 * "0 mi (0 km)", "4 mi (6.4 km)", "26 mi (42 km)" (the route chart, OWNER-DECISIONS 322).
 */
export function formatAxisDistance(metres: number): string {
  const at = Math.max(Number.isFinite(metres) ? metres : 0, 0);
  const short = (value: number) => (value >= 10 ? Math.round(value) : Number(value.toFixed(1))).toString();
  return `${short(at / METRES_PER_MILE)} mi (${short(at / 1000)} km)`;
}

/**
 * A run of road or path for the map's explanations, given in miles: feet (and kilometres) below
 * half a mile, so a quarter mile reads "1,320 ft (0.4 km)" and not the "0.3 mi" that
 * `formatDistance`'s one decimal rounds it to, which is not the bar; from half a mile as
 * `formatDistance` says it.
 */
export function formatRunMiles(miles: number): string {
  const metres = miles * METRES_PER_MILE;
  if (miles < 0.5) return `${Math.round(miles * 5280).toLocaleString("en-US")} ft (${(metres / 1000).toFixed(1)} km)`;
  return formatDistance(metres);
}

/** An extra distance inside a sentence, miles first, metric in brackets: "+1.2 mi (1.9 km)". */
export function formatExtra(metres: number): string {
  if (!usable(metres)) return DASH;
  return `+${milesFigure(metres)} mi (${(metres / 1000).toFixed(1)} km)`;
}

/**
 * A distance for every mile of something, from a ratio (metres per metre): to a
 * tenth below ten miles, so the calm curve's 0.585 at position 85 is "0.6 mi
 * (0.9 km)" and not a rounded-up "1 mi (1 km)"; whole units from ten up.
 */
export function formatPerMile(ratio: number): string {
  if (!usable(ratio)) return DASH;
  if (ratio < 10) {
    const miles = Math.max(0.1, Math.round(ratio * 10) / 10);
    return `${miles.toFixed(1)} mi (${((miles * METRES_PER_MILE) / 1000).toFixed(1)} km)`;
  }
  return formatRoughDistance(ratio * METRES_PER_MILE);
}

/**
 * A group's length, a rough figure: under a mile in feet to the nearest 10 and metres to the
 * nearest 5, "1,560 ft (475 m)"; from a mile, miles to two places, "1.18 mi (1.9 km)".
 */
export function formatGroupLength(metres: number): string {
  if (!usable(metres)) return DASH;
  if (metres < METRES_PER_MILE) {
    const feet = Math.round((metres * FEET_PER_METRE) / 10) * 10;
    return `${feet.toLocaleString("en-US")} ft (${Math.round(metres / 5) * 5} m)`;
  }
  return `${(metres / METRES_PER_MILE).toFixed(2)} mi (${(metres / 1000).toFixed(1)} km)`;
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

/** A range of speeds from mph: "6 to 8 mph (10 to 13 km/h)", said as a range by a screen reader (not "6 minus 8"), miles first (the Mass Ride map's 6 to 8 mph, OWNER-DECISIONS 326). */
export function formatSpeedRange(lowMph: number, highMph: number): string {
  if (!usable(lowMph) || !usable(highMph)) return DASH;
  return `${Math.round(lowMph)} to ${Math.round(highMph)} mph (${Math.round(lowMph * KMH_PER_MPH)} to ${Math.round(highMph * KMH_PER_MPH)} km/h)`;
}

/** A whole number of seconds, for "trying again in ...": "1 second", "5 seconds". */
export function formatSeconds(seconds: number): string {
  return seconds === 1 ? "1 second" : `${seconds} seconds`;
}

/** The distance as said, US units only (Ride mode, WEB-NAV-plan.md Q4): "50 feet", "300 feet", "0.4 miles", "1 mile". */
export function spokenDistance(metres: number): string {
  const m = Math.max(0, metres);
  if (m < METRES_PER_MILE / 10) {
    const feet = m * FEET_PER_METRE;
    const rounded = feet >= 200 ? Math.round(feet / 50) * 50 : Math.max(10, Math.round(feet / 10) * 10);
    return `${rounded} feet`;
  }
  const miles = Math.round((m / METRES_PER_MILE) * 10) / 10;
  if (miles === 1) return "1 mile";
  return `${Number.isInteger(miles) ? miles.toFixed(0) : miles.toFixed(1)} miles`;
}
