/**
 * The stress overlay's paint definition.
 *
 * Kept as data rather than as inline style calls so that it can be asserted:
 * the accessibility rule is that nothing encodes meaning in colour alone, and a
 * rule that lives only in a reviewer's memory is one dash width away from being
 * broken. Each tier therefore carries a dash pattern and a label as well as a
 * colour, which also makes the overlay legible in the printed black and white a
 * marshal actually carries.
 *
 * Relative luminance decreases monotonically as stress rises, so the ordering
 * survives greyscale printing rather than running through hues that flatten
 * into the same grey. The test computes that luminance from the colour itself;
 * an earlier version compared a `lightness` number typed by hand beside each
 * colour, which meant the palette could violate the property while the test
 * passed. It did: LTS4 was the darkest tier of the four and sat eight grey
 * levels from LTS1, so on a marshal's black-and-white sheet "comfortable" and
 * "heavy traffic" printed the same.
 *
 * Each tier also carries a casing: a solid line drawn under it, two pixels
 * wider, in a colour chosen to stand apart from both the tier and whatever the
 * line is drawn over. The calm tiers are light greens, and on the base map
 * they are drawn over parkland, woods and scrub that are the same light greens
 * (LTS 1 against the park fill was 1.00:1), so without the casing the calmest
 * streets - the ones this map exists to find - were the invisible ones. A dark
 * casing under LTS 1 and 2 and a white one under LTS 3 and 4 keeps every tier
 * at least 3:1 from the map (WCAG 1.4.11's figure for graphics) and from both
 * themes' panel behind the legend; stressContrast.test.ts measures that
 * against the base map's own fill colours.
 */

export const STRESS_TIERS = [
  {
    tier: 1,
    label: "Comfortable for most people",
    short: "LTS 1",
    color: "#9ed3ac",
    dash: [1],
    width: 3,
    casing: "#17301f",
  },
  {
    tier: 2,
    label: "Comfortable for most adults",
    short: "LTS 2",
    color: "#57a06c",
    dash: [4, 1],
    width: 3,
    casing: "#17301f",
  },
  {
    tier: 3,
    label: "For confident riders",
    short: "LTS 3",
    color: "#8a4a10",
    dash: [2, 2],
    width: 3.5,
    casing: "#ffffff",
  },
  {
    tier: 4,
    label: "Heavy or fast traffic",
    short: "LTS 4",
    color: "#340808",
    dash: [1, 2],
    width: 4,
    casing: "#ffffff",
  },
  // Not a Furth tier: legal for a bicycle and best avoided (the owner's fifth
  // category, 2026-09-27). It cannot be darker than LTS 4 by a readable step,
  // so it stands apart instead: a colour no other tier is near, the widest
  // line, and a dash-dot pattern nothing else uses, over a white casing.
  {
    tier: 5,
    label: "Legal, but best avoided",
    short: "Avoid",
    color: "#b0006a",
    dash: [3, 1, 0.5, 1],
    width: 4.5,
    casing: "#ffffff",
  },
];

/** The Furth tiers, the ones ordered by luminance for greyscale print. */
export const FURTH_TIERS = STRESS_TIERS.filter((t) => t.tier <= 4);

/** WCAG relative luminance of a hex colour, 0 (black) to 1 (white). */
export function relativeLuminance(hex) {
  const channels = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const [r, g, b] = channels.map((c) =>
    c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4,
  );
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** Contrast ratio between two hex colours, per WCAG 2.x. */
export function contrastRatio(a, b) {
  const [hi, lo] = [relativeLuminance(a), relativeLuminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** The basemap, served from a local PMTiles file rather than a tile provider. */
//
// The path is the one Caddy serves the archive at (Caddyfile, /basemap/*;
// docs/OPERATIONS.md, "The base map"). It is relative on purpose: the pmtiles
// protocol fetches it on the page's own thread, so the browser resolves it
// against the page and sends the same-origin Referer that the edge's hotlinking
// guard requires. The archive's embedded attribution names OpenStreetMap only,
// so the credit is stated here rather than read from it.
export const BASEMAP = {
  // Range requests against one file on our own disk: no third party sees which
  // routes are being looked at, which matters when some of them are for
  // unpermitted rides.
  protocol: "pmtiles",
  path: "/basemap/region.pmtiles",
  url: "pmtiles:///basemap/region.pmtiles",
  attribution:
    '<a href="https://www.openstreetmap.org/copyright">© OpenStreetMap contributors</a> (ODbL)' +
    ', <a href="https://protomaps.com">© Protomaps</a>',
};

// The stress tiles' layer and property, per the SHARED API CONTRACT for
// /tiles/stress/{z}/{x}/{y}.pbf: one layer named "stress", a "tier" of 1-5 or
// null on each feature (5 is "legal but avoid", added 2026-09-27).
export const STRESS_TILE_LAYER = "stress";

/**
 * Roads closed to motor traffic at set times (the tiles' "car_free", or
 * "car_free_only" in a zoomed-out tile, which carries such a road for those
 * times alone: core/stress_tiles.py). The owner, 2026-09-29: "One note:
 * Car-free roads should be regarded the same as an off-road path on a map."
 * and, for the weekend closures, "Path on weekends only" - so in one of those
 * ride times the road draws exactly as an off-road path, tier 1, and in any
 * other with its own stress, and a zoomed-out tile's road is not drawn then.
 * A road closed for good is a path in the tiles already. `when` is the ride
 * time the map follows: "weekend", "weekday_rush" or "weekday_offpeak".
 */
const carFreeNow = (when) => [
  "in",
  when,
  ["coalesce", ["get", "car_free"], ["get", "car_free_only"], ""],
];

/** The tier a feature draws at in the ride time `when`. */
export const tierAt = (when) => ["case", carFreeNow(when), 1, ["get", "tier"]];

/** The bike facility a feature draws as in the ride time `when`. */
export const facilityAt = (when) => ["case", carFreeNow(when), "path", ["get", "facility"]];

/** Whether a feature is drawn at all in the ride time `when`. */
export const drawnAt = (when) => [
  "any",
  ["!", ["has", "car_free_only"]],
  ["in", when, ["get", "car_free_only"]],
];

/** Until the map knows the ride time; App gives it at once (lib/rideTime.ts). */
export const DEFAULT_WHEN = "weekday_offpeak";

/** Each overlay layer's filter in the ride time `when`, by layer id. */
export function stressFilters(when = DEFAULT_WHEN) {
  const filters = {};
  for (const tier of STRESS_TIERS) {
    const filter = ["all", drawnAt(when), ["==", tierAt(when), tier.tier]];
    filters[`stress-${tier.tier}`] = filter;
    filters[`stress-casing-${tier.tier}`] = filter;
  }
  for (const facility of FACILITIES) {
    filters[`facility-${facility.facility}`] = ["all", drawnAt(when), ["==", facilityAt(when), facility.facility]];
  }
  return filters;
}

export function stressLayers(sourceId = "stress", when = DEFAULT_WHEN) {
  const filters = stressFilters(when);
  return STRESS_TIERS.map((tier) => ({
    id: `stress-${tier.tier}`,
    type: "line",
    source: sourceId,
    "source-layer": STRESS_TILE_LAYER,
    filter: filters[`stress-${tier.tier}`],
    paint: {
      "line-color": tier.color,
      "line-width": tier.width,
      "line-dasharray": tier.dash,
    },
  }));
}

/** The casing under each tier's line, drawn first so the tier sits on it. */
export function stressCasingLayers(sourceId = "stress", when = DEFAULT_WHEN) {
  const filters = stressFilters(when);
  return STRESS_TIERS.map((tier) => ({
    id: `stress-casing-${tier.tier}`,
    type: "line",
    source: sourceId,
    "source-layer": STRESS_TILE_LAYER,
    filter: filters[`stress-casing-${tier.tier}`],
    paint: {
      "line-color": tier.casing,
      "line-width": tier.width + CASING_EXTRA_PX,
    },
  }));
}

/** How much wider a casing is than its tier's line: a pixel on each side. */
export const CASING_EXTRA_PX = 2;

/**
 * Bike facilities (owner request of 2026-09-27: off-road paths, then protected
 * lanes, well above painted lanes, above ordinary streets; sharrows count as
 * nothing). The tiles carry a "facility" of path, protected, lane or none once
 * the segment table has it (core/stress_tiles.py), and nothing before.
 *
 * Each is drawn as a pair of violet rails either side of the stress line - a
 * wider line under the tier's casing - so the tier's own colour and dash stay
 * readable on the same street and the route's blue is not reused. Width and
 * dash tell the three apart without colour: a path's rails are bold and solid,
 * a protected lane's bold and broken like a row of posts, a painted lane's
 * thin. "none" (sharrows included) draws nothing.
 */
export const FACILITIES = [
  { facility: "path", short: "Path", label: "Off-road bike path", color: "#4c1d95", rail: 3, dash: null },
  { facility: "protected", short: "Protected", label: "Protected bike lane", color: "#4c1d95", rail: 3, dash: [0.5, 0.35] },
  { facility: "lane", short: "Painted", label: "Painted bike lane", color: "#8b5cf6", rail: 1.5, dash: null },
];

/** A facility's rails: wide enough to show `rail` px beyond each side of the casing. */
export function facilityWidth(facility, tierWidth) {
  return tierWidth + CASING_EXTRA_PX + 2 * facility.rail;
}

// A tier the style has no entry for (one added later) is drawn at LTS 1's width.
const DEFAULT_TIER_WIDTH = STRESS_TIERS[0].width;

/** A facility's rail width, by the tier its feature draws at in `when`. */
export function facilityWidthAt(facility, when = DEFAULT_WHEN) {
  const byTier = STRESS_TIERS.flatMap((tier) => [tier.tier, facilityWidth(facility, tier.width)]);
  return ["match", tierAt(when), ...byTier, facilityWidth(facility, DEFAULT_TIER_WIDTH)];
}

export function facilityLayers(sourceId = "stress", when = DEFAULT_WHEN) {
  const filters = stressFilters(when);
  return FACILITIES.map((facility) => {
    const paint = {
      "line-color": facility.color,
      "line-width": facilityWidthAt(facility, when),
    };
    if (facility.dash) paint["line-dasharray"] = facility.dash;
    return {
      id: `facility-${facility.facility}`,
      type: "line",
      source: sourceId,
      "source-layer": STRESS_TILE_LAYER,
      filter: filters[`facility-${facility.facility}`],
      paint,
    };
  });
}

/**
 * The overlay's layers in the order they are added to the map, bottom first:
 * the facility rails, every casing, then every tier. A casing drawn after a
 * tier would paint over it, solid, wherever the two meet - including its own
 * tier, which would then vanish under its casing; rails drawn over a casing
 * would do the same to the whole line.
 */
export function stressOverlayLayers(sourceId = "stress", when = DEFAULT_WHEN) {
  return [...facilityLayers(sourceId, when), ...stressCasingLayers(sourceId, when), ...stressLayers(sourceId, when)];
}

/** Legend entries, which carry the label the colour alone cannot. */
export function legend() {
  return STRESS_TIERS.map(({ tier, short, label, color, dash, width, casing }) => ({
    tier,
    short,
    label,
    color,
    dash,
    width,
    casing,
  }));
}
