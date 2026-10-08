/**
 * The Mass Ride map's paint: the stress tiles coloured by carrying capacity, in riders
 * per minute at 6-8 mph, not by traffic stress (OWNER-DECISIONS 325, 326, 327, 387).
 *
 * "This needs a redesign. The focus is on carrying capacity, not LTS here. ... The
 * headline color should be riders per minute. Trails and protected bike lanes aren't
 * relevant here." (325). Four bands (326), a spectral ramp with the line widening as the
 * capacity does (327: "Do a spectral color. Red for bottleneck purple for wide open.
 * Line thickness too."):
 *
 *   under 60:   red    #d7191c, 4 px,   short dash   (bottleneck)
 *   60 to 120:  orange #f28e2b, 5.5 px, long dash    (tight)
 *   120 to 200: green  #1a9850, 7 px,   solid        (good)
 *   200 and up: purple #6a3d9a, 8.5 px, solid        (wide open)
 *
 * Each band is outlined by a halo 3:1 from it (dark under the red, orange and green, white under the
 * purple), which also shows in the gaps of the dashes. Colour is never the only cue: the red and the green, which a red-green colour-blind
 * rider sees as one, differ in width (4 against 7 px) and in dash, and every band
 * differs from its neighbour in width and the lower two in dash (massStyle.test.ts
 * measures the pairs under simulated colour vision; docs/DEVELOPMENT.md has the table).
 *
 * The capacity is the `rpm` of the Mass Ride's own tiles (core/mass_tiles.py, source
 * MASS_SOURCE_ID), rounded down to ten, so the band edges (multiples of ten) never move.
 * Those tiles draw the roads with a capacity at every zoom the map asks for, z10-14
 * (OWNER-DECISIONS 415: the busy roads too at z12-13, where the stress tiles are the ride
 * layer), and only inside the District of Columbia (418), clipped to its boundary; the
 * border roads count as inside (420). A table without the column (promoted before the
 * rebuild that writes it) gives empty tiles, and nothing here draws.
 *
 * Focus by zoom (421, 422: "Maybe focus on higher capacity roads at large zooms", "The focus
 * option sounds good."): each band has a first zoom, `minzoom`. Zoom 10-11 draws only Wide
 * open, and only where it runs MASS_WIDE_RUN_MI or more (the tiles drop the isolated
 * blocks: an island of 200 on a turn lane would read as a speck); zoom 12-13 Good and Wide
 * open; zoom 14 on, every band. The tiles hold the same bands (core/mass_tiles.py,
 * `min_rpm_for`; tests/test_mass_tiles.py holds the two equal), the layers carry the
 * `minzoom` too, and the legend says in words which bands show at the zoom the map is at
 * (lib/massCapacity.ts, `massBandsSaid`). Avoid shows at every zoom: it is a warning, not a band.
 *
 * Hidden in this mode, at every zoom: every stress-map layer - the LTS colours, the
 * facility rails (path, protected and painted lane), the trails and paths, the zoomed-out
 * long trails and the ride layer's calm roads (325; 417: "Mass rides should mainly only show
 * capacity and federal land. Trails and PBLs aren't relevant here."; 417a: "The major trail
 * PBL etc should not be shown at any zoom in mass ride."), and the base map's path names
 * (lib/mapGlue.ts, setMassMode). A stretch marked Avoid shows only "Avoid", in its own
 * style with no capacity colour (325, 327: near-black on coral, with the label).
 *
 * HAZARDS (part 3, not built): rider-marked Caution and Warning side rails come from the
 * peer-review backend, which does not exist yet (387). `hazardLayers` is where they join:
 * an empty list, drawn over the capacity lines and under the Avoid label. Nothing is
 * drawn, and nothing here asks a backend for hazards.
 */

/** The Mass Ride tiles' source (lib/mapStyle.ts, massSource; core/mass_tiles.py). */
export const MASS_SOURCE_ID = "mass";

/**
 * The bands, lowest first. `min` inclusive, `max` exclusive (the last has none). `minzoom`:
 * the first zoom the band is drawn at (421).
 */
export const MASS_BANDS = [
  { key: "bottleneck", name: "bottleneck", short: "Under 60", min: 0, max: 60, minzoom: 14, color: "#d7191c", halo: "#1c1917", width: 4, dashPx: [6, 4] },
  { key: "tight", name: "tight", short: "60 to 120", min: 60, max: 120, minzoom: 14, color: "#f28e2b", halo: "#1c1917", width: 5.5, dashPx: [14, 4] },
  { key: "good", name: "good", short: "120 to 200", min: 120, max: 200, minzoom: 12, color: "#1a9850", halo: "#1c1917", width: 7, dashPx: null },
  { key: "wide", name: "wide open", short: "200 and up", min: 200, max: null, minzoom: 10, color: "#6a3d9a", halo: "#ffffff", width: 8.5, dashPx: null },
];

/**
 * Below the Good band's first zoom a Wide open block is drawn only as part of this many miles
 * of continuous Wide open road (422, provisional; core/mass_tiles.py WIDE_RUN_MI).
 */
export const MASS_WIDE_RUN_MI = 0.5;

/**
 * The bands (indices into MASS_BANDS, lowest first) the map draws at `zoom`: the tiles' own
 * zoom, so a map at 11.6 draws z11's. None below the first band's zoom.
 */
export function massBandsAt(zoom) {
  if (typeof zoom !== "number" || !Number.isFinite(zoom)) return [];
  const z = Math.floor(zoom);
  return MASS_BANDS.flatMap((band, i) => (band.minzoom <= z ? [i] : []));
}

/** The band's dash in line widths (MapLibre's unit), or null for a solid line. */
export function dashInWidths(band) {
  return band.dashPx ? band.dashPx.map((px) => px / band.width) : null;
}

/** The band (0 to 3) a riders-per-minute figure is in, or null for no figure. */
export function bandIndex(rpm) {
  if (typeof rpm !== "number" || !Number.isFinite(rpm) || rpm < 0) return null;
  let found = 0;
  MASS_BANDS.forEach((band, i) => {
    if (rpm >= band.min) found = i;
  });
  return found;
}

/**
 * The Avoid stretch's own style in this mode (327: "Avoid keeps its near-black on coral
 * with the AVOID label"): the widest line, a dash-dot nothing else has.
 */
export const MASS_AVOID = { color: "#14040a", casing: "#ee3b2c", width: 6.5, casingWidth: 9, dash: [5, 1, 0.5, 1], label: "AVOID" };

/** Extra casing width, the whole line (a pixel a side), and with the accessibility switch another pixel. */
export const MASS_CASING_EXTRA_PX = 2;
export const MASS_STRONG_CASING_EXTRA_PX = 3;

/** The layer ids this mode adds, by group. */
export const MASS_LAYER_IDS = {
  casing: MASS_BANDS.map((band) => `mass-casing-${band.key}`),
  line: MASS_BANDS.map((band) => `mass-line-${band.key}`),
  avoidCasing: "mass-avoid-casing",
  avoid: "mass-avoid",
  avoidLabel: "mass-avoid-label",
};

/** Every layer id, in draw order. */
export function massLayerIds() {
  return [...MASS_LAYER_IDS.casing, ...MASS_LAYER_IDS.line, MASS_LAYER_IDS.avoidCasing, MASS_LAYER_IDS.avoid, MASS_LAYER_IDS.avoidLabel];
}

/**
 * A feature the Mass Ride map draws at all: a road with a capacity, not a trail or a path
 * (126, 127), not a mountain-bike trail (452; the Mass Ride tiles carry none, and this keeps
 * it so where the layers read the stress tiles), not an alley, and not a road the zoomed-out
 * tile carries only for its closed times. A feature with no `rpm` is the stress map's (`massHides`).
 */
const isRoad = [
  "all",
  ["has", "rpm"],
  ["!=", ["get", "trail"], true],
  ["!=", ["get", "facility"], "path"],
  ["!=", ["get", "mtb"], true],
  ["!", ["has", "alley"]],
  ["!", ["has", "car_free_only"]],
];

const isAvoid = ["==", ["get", "tier"], 5];

/** Each Mass Ride layer's filter, by id. */
export function massFilters() {
  const filters = {};
  MASS_BANDS.forEach((band, i) => {
    const inBand = band.max === null ? [">=", ["get", "rpm"], band.min] : ["all", [">=", ["get", "rpm"], band.min], ["<", ["get", "rpm"], band.max]];
    const filter = ["all", isRoad, ["!", isAvoid], inBand];
    filters[MASS_LAYER_IDS.casing[i]] = filter;
    filters[MASS_LAYER_IDS.line[i]] = filter;
  });
  const avoid = ["all", isRoad, isAvoid];
  filters[MASS_LAYER_IDS.avoidCasing] = avoid;
  filters[MASS_LAYER_IDS.avoid] = avoid;
  filters[MASS_LAYER_IDS.avoidLabel] = avoid;
  return filters;
}

/**
 * The filter that takes a stress or facility layer's features out where the tiles carry
 * `rpm`: LTS colours, rails and the tier-5 Avoid style give way to this mode's. A table
 * without the column has no `rpm` anywhere, so none is taken out.
 */
export const massHides = ["!", ["has", "rpm"]];

/**
 * A width that grows with the zoom: every road is drawn from z10 (core/mass_tiles.py), and a
 * full-width line there would fill the map; from z16 it is as drawn.
 */
function byZoom(width) {
  return ["interpolate", ["linear"], ["zoom"], 12, width * 0.45, 14, width * 0.8, 16, width];
}

/**
 * The hazards' seam (part 3, OWNER-DECISIONS 325 and 387). Rider-marked Caution and
 * Warning stretches will be drawn as near-black side rails beside the road (Caution
 * dotted, Warning dash-dot; 327), from a source that does not exist yet. This returns the
 * layers for them: none, today. Part 3 fills it in, in this position in the order.
 */
export function hazardLayers() {
  return [];
}

/** Whether rider-marked hazards are built: not until the rider-report backend exists (part 3). */
export const HAZARDS_BUILT = false;

/**
 * The Mass Ride layers, in draw order: every casing under every line, then the Avoid
 * stretches, then the hazard seam, then the Avoid label. `strong` is the accessibility
 * switch (a pixel more of casing).
 */
export function massLayers(sourceId = MASS_SOURCE_ID, sourceLayer = "stress", strong = false) {
  const filters = massFilters();
  const extra = strong ? MASS_STRONG_CASING_EXTRA_PX : MASS_CASING_EXTRA_PX;
  const base = { type: "line", source: sourceId, "source-layer": sourceLayer };
  const casings = MASS_BANDS.map((band, i) => ({
    ...base,
    id: MASS_LAYER_IDS.casing[i],
    minzoom: band.minzoom,
    filter: filters[MASS_LAYER_IDS.casing[i]],
    paint: { "line-color": band.halo, "line-width": byZoom(band.width + extra) },
  }));
  const lines = MASS_BANDS.map((band, i) => {
    const dash = dashInWidths(band);
    return {
      ...base,
      id: MASS_LAYER_IDS.line[i],
      minzoom: band.minzoom,
      filter: filters[MASS_LAYER_IDS.line[i]],
      paint: { "line-color": band.color, "line-width": byZoom(band.width), ...(dash ? { "line-dasharray": dash } : {}) },
    };
  });
  const avoid = [
    {
      ...base,
      id: MASS_LAYER_IDS.avoidCasing,
      filter: filters[MASS_LAYER_IDS.avoidCasing],
      paint: { "line-color": MASS_AVOID.casing, "line-width": byZoom(MASS_AVOID.casingWidth + (extra - MASS_CASING_EXTRA_PX)) },
    },
    {
      ...base,
      id: MASS_LAYER_IDS.avoid,
      filter: filters[MASS_LAYER_IDS.avoid],
      paint: { "line-color": MASS_AVOID.color, "line-width": byZoom(MASS_AVOID.width), "line-dasharray": MASS_AVOID.dash },
    },
  ];
  const label = {
    ...base,
    id: MASS_LAYER_IDS.avoidLabel,
    type: "symbol",
    minzoom: 14,
    filter: filters[MASS_LAYER_IDS.avoidLabel],
    layout: {
      "symbol-placement": "line",
      "text-field": MASS_AVOID.label,
      "text-font": ["Noto Sans Medium"],
      "text-size": 12,
      "text-letter-spacing": 0.08,
      "text-max-angle": 30,
    },
    paint: { "text-color": "#ffffff", "text-halo-color": MASS_AVOID.color, "text-halo-width": 2 },
  };
  return [...casings, ...lines, ...avoid, ...hazardLayers(), label];
}
