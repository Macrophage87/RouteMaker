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
 */

export const STRESS_TIERS = [
  {
    tier: 1,
    label: "Comfortable for most people",
    short: "LTS 1",
    color: "#9ed3ac",
    dash: [1],
    width: 3,
  },
  {
    tier: 2,
    label: "Comfortable for most adults",
    short: "LTS 2",
    color: "#57a06c",
    dash: [4, 1],
    width: 3,
  },
  {
    tier: 3,
    label: "For confident riders",
    short: "LTS 3",
    color: "#8a4a10",
    dash: [2, 2],
    width: 3.5,
  },
  {
    tier: 4,
    label: "Heavy or fast traffic",
    short: "LTS 4",
    color: "#340808",
    dash: [1, 2],
    width: 4,
  },
];

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
// /tiles/stress/{z}/{x}/{y}.pbf: one layer named "stress", a "tier" of 1-4 or
// null on each feature.
export const STRESS_TILE_LAYER = "stress";

export function stressLayers(sourceId = "stress") {
  return STRESS_TIERS.map((tier) => ({
    id: `stress-${tier.tier}`,
    type: "line",
    source: sourceId,
    "source-layer": STRESS_TILE_LAYER,
    filter: ["==", ["get", "tier"], tier.tier],
    paint: {
      "line-color": tier.color,
      "line-width": tier.width,
      "line-dasharray": tier.dash,
    },
  }));
}

/** Legend entries, which carry the label the colour alone cannot. */
export function legend() {
  return STRESS_TIERS.map(({ tier, short, label, color, dash }) => ({
    tier,
    short,
    label,
    color,
    dash,
  }));
}
