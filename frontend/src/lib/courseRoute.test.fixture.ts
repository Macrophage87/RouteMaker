// A route for the course export's tests (course.test.ts, fit.test.ts); not part of the app.
import type { DescriptionEntry, RouteResponse } from "./api.ts";
import type { LonLat } from "./geo.ts";

const M_PER_DEG = 111_195;
const LAT = 38.9;
const KX = M_PER_DEG * Math.cos((LAT * Math.PI) / 180);
export const at = (east: number, north = 0): LonLat => [-77.05 + east / KX, LAT + north / M_PER_DEG];

function entry(kind: DescriptionEntry["kind"], from: number, to: number, text: string, extra: Partial<DescriptionEntry> = {}): DescriptionEntry {
  return { kind, from_m: from, to_m: to, from_mi: from / 1609.344, to_mi: to / 1609.344, street: null, tier: 1, facility: null, turn: null, text, ...extra };
}

const turn = (movement: "left" | "right", onto: string | null) => ({ movement, onto, control: null, severity: null });

/** 3 km east, a vertex every 10 m, with a turn of each kind, a flagged crossing, an Avoid junction, a stop and a busy stretch. */
export function sampleRoute(over: Partial<RouteResponse> = {}): RouteResponse {
  const line = Array.from({ length: 301 }, (_, i) => at(i * 10));
  const description: DescriptionEntry[] = [
    entry("stretch", 0, 500, "0 to 0.3 mi (0 to 0.5 km): R Street Northwest, LTS 1.", { street: "R Street Northwest" }),
    entry("stretch", 500, 900, "0.3 to 0.6 mi: Left onto 17th Street Northwest, LTS 2.", { street: "17th Street Northwest", tier: 2, turn: turn("left", "17th Street Northwest") }),
    entry("junction", 900, 900, "At 0.6 mi: Cross Florida Avenue Northwest (LTS 4).", { street: "Florida Avenue Northwest", severity: "red" }),
    entry("avoid", 1200, 1200, "At 0.7 mi: Avoid-rated junction ahead: Dupont Circle.", { street: "Dupont Circle", severity: "avoid" }),
    entry("via", 1500, 1500, "At 0.9 mi: Stop 1.", { via: 1 }),
    entry("stretch", 1500, 2000, "0.9 to 1.2 mi: Right onto the path.", { street: null, turn: turn("right", null) }),
    entry("stretch", 2000, 3000, "1.2 to 1.9 mi: Connecticut Avenue Northwest, busy road (LTS 4).", { street: "Connecticut Avenue Northwest", tier: 4 }),
  ];
  return {
    preset: "default",
    variant: "standard",
    geometry: { type: "LineString", coordinates: line },
    distance_m: 3000,
    duration_s: 600,
    climb_m: 12,
    descent_m: 8,
    attribution: ["© OpenStreetMap contributors (ODbL)", "USGS 3DEP"],
    description,
    leg_ends: [150, 300],
    profile: { m: [0, 3000], elevation_m: [20, 50] },
    ...over,
  } as unknown as RouteResponse;
}

