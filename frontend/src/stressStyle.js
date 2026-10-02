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

// The tiers' shapes: what tells them apart without colour.
const TIER_SHAPES = [
  { tier: 1, label: "Comfortable for most people", short: "LTS 1", dash: [1], width: 3 },
  { tier: 2, label: "Comfortable for most adults", short: "LTS 2", dash: [4, 1], width: 3 },
  { tier: 3, label: "For confident riders", short: "LTS 3", dash: [2, 2], width: 3.5 },
  { tier: 4, label: "Heavy or fast traffic", short: "LTS 4", dash: [1, 2], width: 4 },
  // Not a Furth tier: legal for a bicycle and best avoided (the owner's fifth
  // category, 2026-09-27): the widest line and a dash-dot nothing else uses.
  { tier: 5, label: "Legal, but best avoided", short: "Avoid", dash: [3, 1, 0.5, 1], width: 4.5 },
];

/**
 * THE STRESS COLOURS, in one place. The owner, 2026-09-29: "Also, let's change
 * the color scheme. I like LTS 1 and 2. Maybe yellow and orange for LTS 3,
 * orange and red for LTS 4, and red and black for Avoid." (OWNER-DECISIONS
 * 74). LTS 1 and 2 are kept as they were; two readings of "X and Y" are built
 * for the owner to choose between, `?palette=twotone` in the address showing
 * the second:
 *
 * - "blended": one colour per tier between the two named - LTS 3 amber (over
 *   a dark casing, since amber is not 3:1 on the base map's greens), LTS 4
 *   red-orange and Avoid dark red (over white). Relative luminance still falls
 *   tier by tier (0.57, 0.28, 0.23, 0.09, 0.02), so greyscale print keeps the
 *   order; LTS 2 and 3 are only 1.17:1 apart in grey, where their dashes
 *   (long, even) tell them apart - an amber dark enough for 1.4:1 is brown.
 * - "twotone": the first colour as the line, the second as its casing - LTS 3
 *   yellow on orange, LTS 4 orange on red, Avoid red on black. Closer to the
 *   owner's words; LTS 3 is not 3:1 on the base map (its casing 2.2:1, the line
 *   on its casing 1.5:1) and the greyscale order is lost (stressContrast.test.ts
 *   holds the chosen palette to the rule, and reports the other).
 * - "cvd" (OWNER-DECISIONS 208): the colour-blind-friendly option a rider
 *   switches to in the panel. Not a reading of the owner's colours: it is
 *   chosen by measurement to stay apart under protanopia, deuteranopia and
 *   tritanopia (Machado 2009, severity 1.0). The comfortable tiers are light
 *   and mid blue, LTS 3 a burnt orange, LTS 4 a dark red and Avoid a
 *   blue-black: blue against orange is the pair all three deficiencies keep,
 *   and the lightness falls tier by tier, so greyscale order holds too.
 *   Every adjacent pair is CIEDE2000 20 or more apart under normal vision and
 *   under each simulation (stressContrast.test.ts; the table is in
 *   docs/DEVELOPMENT.md, "The colour-blind-friendly palette"). The blue-black
 *   is not a neutral black on purpose: a protanope sees LTS 4's dark red as
 *   near-black, and a neutral black Avoid beside it measured 18 apart.
 */
export const PALETTES = {
  blended: {
    1: { color: "#9ed3ac", casing: "#17301f" },
    2: { color: "#57a06c", casing: "#17301f" },
    3: { color: "#bf730b", casing: "#2b1a05" },
    4: { color: "#a32814", casing: "#ffffff" },
    5: { color: "#4a0810", casing: "#ffffff" },
  },
  twotone: {
    1: { color: "#9ed3ac", casing: "#17301f" },
    2: { color: "#57a06c", casing: "#17301f" },
    3: { color: "#f2c21b", casing: "#f28c28" },
    4: { color: "#f28c28", casing: "#d42020" },
    5: { color: "#d42020", casing: "#111111" },
  },
  cvd: {
    1: { color: "#d2eafc", casing: "#0a1a2f" },
    2: { color: "#5d99d2", casing: "#0a1a2f" },
    3: { color: "#cd4b0a", casing: "#0a1a2f" },
    4: { color: "#6a0a06", casing: "#ffffff" },
    5: { color: "#08081e", casing: "#ffffff" },
  },
};

/** The palette the map uses unless the address or the accessibility switch asks for another. */
export const DEFAULT_PALETTE = "blended";

/** The palette an address's query string names (`?palette=twotone`), or the default. */
export function paletteFrom(search) {
  const match = /(?:^|[?&])palette=([a-z]+)/.exec(search ?? "");
  return match && Object.hasOwn(PALETTES, match[1]) ? match[1] : DEFAULT_PALETTE;
}

/** The palette the accessibility switch turns on (OWNER-DECISIONS 208, 211). */
export const ACCESSIBILITY_PALETTE = "cvd";

/** Where the switch is remembered, per browser: "on" or "off". */
export const ACCESSIBILITY_STORAGE_KEY = "routemaker.accessibility";

/** With the switch on, each line is this much wider (pixels), and its casing this much wider than that. */
export const STRONG_WIDTH_EXTRA = 0.5;
export const STRONG_CASING_EXTRA_PX = 3;

/** The palette an address names (`?palette=cvd`), or null when it names none this page has. */
export function queryPalette(search) {
  const match = /(?:^|[?&])palette=([a-z]+)/.exec(search ?? "");
  return match && Object.hasOwn(PALETTES, match[1]) ? match[1] : null;
}

/** The browser's localStorage, or null where reaching it throws (blocked site data, some embedded views). */
function browserStorage() {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

/**
 * The palette to start with: the address's (`?palette=`), else the
 * colour-blind-friendly one when the accessibility switch is on, else the
 * default.
 */
export function resolvePalette(search, accessibility = false) {
  return queryPalette(search) ?? (accessibility ? ACCESSIBILITY_PALETTE : DEFAULT_PALETTE);
}

/** A casing pushed to its extreme: black under a dark one, white under a light one. */
function strongerCasing(hex) {
  return relativeLuminance(hex) < 0.5 ? "#000000" : "#ffffff";
}

/**
 * The tiers, with a palette's colours. With `strong` (the accessibility
 * switch) they are drawn stronger: lines half a pixel wider, casings black or
 * white and a pixel wider again. Each tier carries the casing's extra width
 * (`casingExtra`), which the layers and the legend read.
 */
export function tiersFor(palette, strong = false) {
  return TIER_SHAPES.map((shape) => {
    const colours = PALETTES[palette][shape.tier];
    return {
      ...shape,
      ...colours,
      ...(strong
        ? { width: shape.width + STRONG_WIDTH_EXTRA, casing: strongerCasing(colours.casing), casingExtra: STRONG_CASING_EXTRA_PX }
        : { casingExtra: CASING_EXTRA_PX }),
    };
  });
}

/**
 * What this browser remembers of the accessibility switch: true (on), false
 * (off, chosen), or null where nothing is stored, the value is not one this
 * page wrote, or storage throws.
 */
export function storedAccessibility(storage = browserStorage()) {
  try {
    const value = storage?.getItem(ACCESSIBILITY_STORAGE_KEY);
    return value === "on" ? true : value === "off" ? false : null;
  } catch {
    return null;
  }
}

/**
 * Whether the switch starts on: what the browser remembers, else whether the
 * system asks for more contrast, else off. The rider's own choice, on or off,
 * always wins; it is not the general default.
 */
export function resolveAccessibility(stored, contrastRequested = false) {
  return stored ?? contrastRequested;
}

/** Remember the switch for this browser; false when storage refused (it then lasts the visit). */
export function rememberAccessibility(on, storage = browserStorage()) {
  try {
    if (!storage) return false;
    storage.setItem(ACCESSIBILITY_STORAGE_KEY, on ? "on" : "off");
    return true;
  } catch {
    return false;
  }
}

// What the page is drawn in, which a rider can change without a reload: the
// accessibility switch, and the palette it and the address decide between.
// Nothing may keep the tiers from import time: read currentTiers() when
// drawing, and subscribePalette() to draw again (paletteChoice.test.ts's
// source scan fails a module that imports a fixed list).
const locationSearch = typeof location === "undefined" ? "" : location.search;
const pinnedByAddress = queryPalette(locationSearch) !== null;
/** The rider's own choice of the switch (stored, or made this visit): null while there is none, and the system's request decides. */
let chosen = storedAccessibility();
let contrastMore = false;
let accessibility = resolveAccessibility(chosen, contrastMore);
let active = resolvePalette(locationSearch, accessibility);
/** @type {Map<string, ReturnType<typeof tiersFor>>} */
const tiersByStyle = new Map();
/** @type {Set<(name: string) => void>} */
const listeners = new Set();

function tell() {
  for (const listener of [...listeners]) listener(active);
}

/** The palette this page is using now. */
export function currentPalette() {
  return active;
}

/** Whether the accessibility switch is on. */
export function accessibilityOn() {
  return accessibility;
}

/** What the switch's state is down to: "chosen" by the rider, "contrast" (the system asks for more), or "default" (off). */
export function accessibilitySource() {
  if (chosen !== null) return "chosen";
  return contrastMore ? "contrast" : "default";
}

/** Whether the address (`?palette=`) chose the palette, which the switch does not override. */
export function paletteSetByAddress() {
  return pinnedByAddress;
}

/** A key that changes whenever what the tiers look like does: the palette, or the switch. */
export function styleKey() {
  return `${active}|${accessibility ? "strong" : "plain"}`;
}

/** The tiers, in the palette and strength in use. The same array until one of them changes. */
export function currentTiers() {
  const key = styleKey();
  let tiers = tiersByStyle.get(key);
  if (!tiers) {
    tiers = tiersFor(active, accessibility);
    tiersByStyle.set(key, tiers);
  }
  return tiers;
}

/** The Furth tiers (1-4), the ones ordered by luminance for greyscale print, in the palette in use. */
export function furthTiers() {
  return currentTiers().filter((t) => t.tier <= 4);
}

/**
 * Turn the accessibility switch on or off now and tell the subscribers; with
 * `remember` (the default) it is kept for this browser, and storage that
 * refuses leaves it set for the visit. On, the stress colours are the
 * colour-blind-friendly palette and the lines are drawn stronger; an address
 * that names a palette still decides the palette. `remember: false` is a
 * trial that leaves what is stored, and the system's say, alone.
 */
export function setAccessibility(on, { remember = true, storage } = {}) {
  const next = on === true;
  if (remember) {
    rememberAccessibility(next, storage);
    chosen = next;
  }
  apply(next);
}

function apply(next) {
  if (next === accessibility) return;
  accessibility = next;
  active = resolvePalette(locationSearch, accessibility);
  tell();
}

/** The media query for a request for more contrast: where the switch starts, until the rider chooses. */
export const CONTRAST_MEDIA = "(prefers-contrast: more)";

/** The parts of a `MediaQueryList` that are used. */
/** @typedef {{ matches: boolean, addEventListener?: Function, removeEventListener?: Function, addListener?: Function, removeListener?: Function }} MediaQuery */

let stopWatching = () => {};

/**
 * Follow the system's request for more contrast, now and as it changes (the
 * rider turns it on in the system's settings with the page open): with no
 * choice of the rider's own, the switch follows it. Returns the way to stop.
 * Called once at load with the window's own matchMedia; a test passes a
 * stand-in. A matchMedia that is missing or throws means no request.
 *
 * @param {((query: string) => MediaQuery) | null} [matchMediaImpl]
 */
export function watchContrast(matchMediaImpl = typeof matchMedia === "function" ? matchMedia : null) {
  stopWatching();
  stopWatching = () => {};
  /** @type {MediaQuery | null} */
  let query = null;
  try {
    query = matchMediaImpl ? matchMediaImpl(CONTRAST_MEDIA) : null;
  } catch {
    query = null;
  }
  const follow = (more) => {
    contrastMore = more === true;
    if (chosen === null) apply(contrastMore);
  };
  follow(query?.matches);
  if (!query) return stopWatching;
  const q = query;
  const onChange = (event) => follow(typeof event?.matches === "boolean" ? event.matches : q.matches);
  if (typeof q.addEventListener === "function") {
    q.addEventListener("change", onChange);
    stopWatching = () => q.removeEventListener?.("change", onChange);
  } else if (typeof q.addListener === "function") {
    q.addListener(onChange); // older Safari
    stopWatching = () => q.removeListener?.(onChange);
  }
  return stopWatching;
}

watchContrast();

/** Call `listener(name)` whenever the palette, or the strength the tiers are drawn at, changes; returns the way to stop. */
/** @param {(name: string) => void} listener */
export function subscribePalette(listener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

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

/** A road whose bike facility is mapped as a way of its own beside it (the tiles' "separate_bikeway"). */
const besideBikeway = ["==", ["get", "separate_bikeway"], true];

/**
 * The busy roads - LTS 3, LTS 4 and Avoid - are background.
 * The owner, 2026-09-29: "The high LTS roads aren't that important because you
 * aren't going to route around them." - "Show them faintly" (OWNER-DECISIONS
 * 76) - then "Make solid at 14" (77): faint at z12-13, where the tiles first
 * carry them, and solid from SOLID_MIN_ZOOM. One beside a separately mapped
 * bike facility (15th Street NW beside its cycle track) is not drawn until
 * BESIDE_ROAD_MIN_ZOOM and then faint at every zoom, so the facility is the
 * main line: "In that case, don't show the road, perhaps hide it until zoom
 * 15-16. The bike lane should show up as the main." (73) and "Keep it faint if
 * it parallels a protected bike path." (78). 15 of the owner's 15-16: at 15 a
 * street and its cycle track are 10-15 px apart on screen, room for both.
 */
export const BUSY_MIN_TIER = 3;
export const SOLID_MIN_ZOOM = 14;
export const BESIDE_ROAD_MIN_ZOOM = 15;
export const FAINT = { opacity: 0.4, widthScale: 0.6 };

/** An alley (the tiles' "alley"). */
const isAlley = ["==", ["get", "alley"], true];

/**
 * Alleys draw only from ALLEY_MIN_ZOOM, faint, as context: "Alley cut
 * throughs should only be used if the roads are very problematic nearby. Cut
 * down on showing them, and only use them if nessicary. Because people don't
 * think of these as intersections, alley dodging is dangerous." (the owner,
 * 2026-09-29; OWNER-DECISIONS 100). 16: close enough that an alley reads as
 * the lane behind the houses it is, not as a street.
 */
export const ALLEY_MIN_ZOOM = 16;

/**
 * A line's `full` value (opacity or width) by zoom: an alley not drawn below
 * ALLEY_MIN_ZOOM and faint from it; a busy road faint, or not drawn, where the
 * rules above say; any other line as it is.
 */
function byZoom(full, faint, busy) {
  const at = (zoom) => {
    const alley = zoom >= ALLEY_MIN_ZOOM ? faint : 0;
    const road = !busy
      ? full
      : ["case", besideBikeway, zoom >= BESIDE_ROAD_MIN_ZOOM ? faint : 0, zoom >= SOLID_MIN_ZOOM ? full : faint];
    return ["case", isAlley, alley, road];
  };
  return [
    "step",
    ["zoom"],
    at(SOLID_MIN_ZOOM - 1),
    SOLID_MIN_ZOOM,
    at(SOLID_MIN_ZOOM),
    BESIDE_ROAD_MIN_ZOOM,
    at(BESIDE_ROAD_MIN_ZOOM),
    ALLEY_MIN_ZOOM,
    at(ALLEY_MIN_ZOOM),
  ];
}

/** A line's paint, faint and late as byZoom says. */
function linePaint(color, width, busy) {
  return {
    "line-color": color,
    "line-width": byZoom(width, width * FAINT.widthScale, busy),
    "line-opacity": byZoom(1, FAINT.opacity, busy),
  };
}

/** Each overlay layer's filter in the ride time `when`, by layer id. */
export function stressFilters(when = DEFAULT_WHEN) {
  const filters = {};
  for (const tier of TIER_SHAPES) {
    const filter = ["all", drawnAt(when), ["==", tierAt(when), tier.tier]];
    filters[`stress-${tier.tier}`] = filter;
    filters[`stress-casing-${tier.tier}`] = filter;
  }
  for (const facility of FACILITIES) {
    filters[`facility-${facility.facility}`] = ["all", drawnAt(when), ["==", facilityAt(when), facility.facility]];
  }
  return filters;
}

export function stressLayers(sourceId = "stress", when = DEFAULT_WHEN, tiers = currentTiers()) {
  const filters = stressFilters(when);
  return tiers.map((tier) => ({
    id: `stress-${tier.tier}`,
    type: "line",
    source: sourceId,
    "source-layer": STRESS_TILE_LAYER,
    filter: filters[`stress-${tier.tier}`],
    paint: { ...linePaint(tier.color, tier.width, tier.tier >= BUSY_MIN_TIER), "line-dasharray": tier.dash },
  }));
}

/** The casing under each tier's line, drawn first so the tier sits on it. */
export function stressCasingLayers(sourceId = "stress", when = DEFAULT_WHEN, tiers = currentTiers()) {
  const filters = stressFilters(when);
  return tiers.map((tier) => ({
    id: `stress-casing-${tier.tier}`,
    type: "line",
    source: sourceId,
    "source-layer": STRESS_TILE_LAYER,
    filter: filters[`stress-casing-${tier.tier}`],
    paint: linePaint(tier.casing, tier.width + (tier.casingExtra ?? CASING_EXTRA_PX), tier.tier >= BUSY_MIN_TIER),
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
export function facilityWidth(facility, tierWidth, casingExtra = CASING_EXTRA_PX) {
  return tierWidth + casingExtra + 2 * facility.rail;
}

/**
 * A facility's rail width, by the tier its feature draws at in `when`, in the
 * tiers' widths and casings in use (the accessibility switch makes both
 * stronger, and the rails sit outside the casing). A tier the style has no
 * entry for (one added later) is drawn at LTS 1's width.
 */
export function facilityWidthAt(facility, when = DEFAULT_WHEN) {
  const tiers = currentTiers();
  const byTier = tiers.flatMap((tier) => [tier.tier, facilityWidth(facility, tier.width, tier.casingExtra)]);
  return ["match", tierAt(when), ...byTier, facilityWidth(facility, tiers[0].width, tiers[0].casingExtra)];
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
export function stressOverlayLayers(sourceId = "stress", when = DEFAULT_WHEN, tiers = currentTiers()) {
  return [
    ...facilityLayers(sourceId, when),
    ...stressCasingLayers(sourceId, when, tiers),
    ...stressLayers(sourceId, when, tiers),
  ];
}

/** Legend entries, which carry the label the colour alone cannot. */
export function legend(tiers = currentTiers()) {
  return tiers.map(({ tier, short, label, color, dash, width, casing }) => ({
    tier,
    short,
    label,
    color,
    dash,
    width,
    casing,
  }));
}
