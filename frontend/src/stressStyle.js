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
 * Colours are ordered light to dark with increasing stress so that the ordering
 * survives greyscale printing, rather than running through hues that flatten
 * into the same grey.
 */

export const STRESS_TIERS = [
  {
    tier: 1,
    label: "Comfortable for most people",
    short: "LTS 1",
    color: "#1a6b3c",
    lightness: 0.28,
    dash: [1],
    width: 3,
  },
  {
    tier: 2,
    label: "Comfortable for most adults",
    short: "LTS 2",
    color: "#4a8f2f",
    lightness: 0.45,
    dash: [4, 1],
    width: 3,
  },
  {
    tier: 3,
    label: "For confident riders",
    short: "LTS 3",
    color: "#c47d1a",
    lightness: 0.62,
    dash: [2, 2],
    width: 3.5,
  },
  {
    tier: 4,
    label: "Heavy or fast traffic",
    short: "LTS 4",
    color: "#a01f1f",
    lightness: 0.78,
    dash: [1, 2],
    width: 4,
  },
];

/** The basemap, served from a local PMTiles file rather than a tile provider. */
export const BASEMAP = {
  // Range requests against one file on our own disk: no third party sees which
  // routes are being looked at, which matters when some of them are for
  // unpermitted rides.
  protocol: "pmtiles",
  url: "pmtiles:///tiles/dc-metro.pmtiles",
  attribution: "© OpenStreetMap contributors, © Protomaps",
};

export function stressLayers(sourceId = "segments") {
  return STRESS_TIERS.map((tier) => ({
    id: `stress-${tier.tier}`,
    type: "line",
    source: sourceId,
    "source-layer": "segment",
    filter: ["==", ["get", "stress_tier"], tier.tier],
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
