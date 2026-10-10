import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import {
  AVOID_DISC,
  AVOID_ICON_PX,
  AVOID_CARD_HEADING,
  AVOID_NOUN,
  AVOID_PLEA,
  AVOID_SPOT_M,
  AVOID_SYMBOL,
  avoidIconSvg,
  avoidCardSaid,
  avoidCardText,
  avoidItems,
  avoidMarkerName,
  avoidNearSpot,
  avoidNoAlternate,
  avoidOffer,
  avoidRowName,
  nestedGlyph,
} from "./avoidJunctions.ts";
import { ICON_PX } from "./intersectionMarkers.ts";
import { saysItsSeverity } from "./routeDescription.ts";
import type { AvoidJunctionPass, DescriptionEntry, RouteResponse } from "./api.ts";

const GLYPH_URL = new URL("../icons/noto-emoji-u2620.svg", import.meta.url);
const GLYPH = readFileSync(GLYPH_URL, "utf8");

const PASS: AvoidJunctionPass = {
  id: 7,
  name: "Main St and 1st Ave",
  reason: "no gap in fast traffic",
  lon: -77.035,
  lat: 38.9,
  m: 1100,
  label: "Avoid-rated junction: Main St and 1st Ave, no gap in fast traffic",
};

test("the glyph is the file the owner approved, unmodified (310)", () => {
  const hash = createHash("sha256").update(readFileSync(GLYPH_URL)).digest("hex");
  assert.equal(hash, "4baff1c033110775d495b6fe6da05a7bdf94452af12f8a9207c00de28364535e");
});

test("the glyph holds only shapes and fills: no script, no link, nothing fetched", () => {
  assert.doesNotMatch(GLYPH, /<script|javascript:|<foreignObject|<image|@import|<!ENTITY|<!DOCTYPE/i);
  assert.doesNotMatch(GLYPH, /\son[a-z]+\s*=/i);
  // The only URLs are the two namespace names.
  const urls = GLYPH.match(/https?:\/\/[^"\s]+/g) ?? [];
  assert.deepEqual([...new Set(urls)].sort(), ["http://www.w3.org/1999/xlink", "http://www.w3.org/2000/svg"]);
  assert.doesNotMatch(GLYPH, /href=/);
});

test("the marker is the glyph on a ringed dark disc, larger than a junction marker, hidden from assistive technology", () => {
  // The owner, 2026-10-10: "Make it larger than a normal icon."
  assert.ok(AVOID_ICON_PX >= ICON_PX * 1.5, `${AVOID_ICON_PX} against ${ICON_PX}`);
  assert.match(avoidIconSvg(GLYPH), new RegExp(`^<svg [^>]*width="${AVOID_ICON_PX}" height="${AVOID_ICON_PX}"`));
  const svg = avoidIconSvg(GLYPH, 24);
  assert.match(svg, /^<svg [^>]*width="24" height="24"[^>]*aria-hidden="true" focusable="false">/);
  assert.match(svg, new RegExp(`<circle cx="12" cy="12" r="11" fill="${AVOID_DISC.fill}" stroke="${AVOID_DISC.ring}"`));
  // The nested glyph: no XML declaration, no comment, no document id (several markers share a page).
  assert.doesNotMatch(svg, /<\?xml|<!--|id="Layer_4"/);
  assert.match(svg, /<svg x="4" y="4" width="16" height="16" viewBox="0 0 128 128" aria-hidden="true" focusable="false">/);
  assert.equal((svg.match(/<svg\b/g) ?? []).length, 2);
  assert.equal((svg.match(/<\/svg>/g) ?? []).length, 2);
  // And the glyph's own shapes come through.
  assert.equal((svg.match(/<path\b/g) ?? []).length, (GLYPH.match(/<path\b/g) ?? []).length);
});

test("the halo: the pale glyph against the dark disc, and the white ring against a dark map, pass 3:1", () => {
  const luminance = (hex: string) => {
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const ratio = (a: string, b: string) => {
    const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (hi + 0.05) / (lo + 0.05);
  };
  // The glyph's bone colour (its main fill) on the disc.
  assert.ok(ratio("#8ABFD1", AVOID_DISC.fill) >= 3);
  // The disc against a white or pale basemap, and the ring against a dark one.
  assert.ok(ratio(AVOID_DISC.fill, "#ffffff") >= 3);
  assert.ok(ratio(AVOID_DISC.ring, "#1f1f1f") >= 3);
});

test("nestedGlyph keeps the viewBox and drops the rest of the opening tag", () => {
  const out = nestedGlyph('<?xml version="1.0"?><!-- x --><svg id="a" x="0px" viewBox="0 0 10 10" style="s"><g/></svg>', 1, 2, 3);
  assert.equal(out, '<svg x="1" y="2" width="3" height="3" viewBox="0 0 10 10" aria-hidden="true" focusable="false"><g/></svg>');
});

test("the names are the rating and the reason, never the glyph's name (309)", () => {
  assert.equal(AVOID_NOUN, "Avoid-rated junction");
  assert.equal(AVOID_SYMBOL, "☠");
  const [item] = avoidItems({ avoid_junctions: [PASS] });
  assert.equal(item.where, "At 0.7 mi (1.1 km)");
  const name = avoidRowName(item);
  assert.equal(
    name,
    "Avoid-rated junction: Main St and 1st Ave, no gap in fast traffic, at 0.7 mi (1.1 km). Riding through it is a really bad idea. Please reconsider your route.",
  );
  assert.doesNotMatch(name, /skull/i);
  assert.equal(
    avoidMarkerName(item),
    "Avoid-rated junction: Main St and 1st Ave, no gap in fast traffic. Riding through it is a really bad idea. Please reconsider your route.",
  );
  assert.doesNotMatch(avoidMarkerName(item), /skull/i);
});

test("no list, or an older API, is no Avoid junction", () => {
  assert.deepEqual(avoidItems(null), []);
  assert.deepEqual(avoidItems({}), []);
  assert.deepEqual(avoidItems({ avoid_junctions: [] }), []);
});

test("the way round is offered with its length and how much longer, US units first (335)", () => {
  const around = { distance_m: 6000, extra_distance_m: 3800 } as unknown as RouteResponse["avoid_alternate"];
  assert.equal(avoidOffer({ avoid_alternate: around }), "Show the route that avoids it: 3.7 mi (6.0 km), 2.4 mi (3.8 km) longer");
  assert.equal(avoidOffer({ avoid_alternate: null }), null);
  assert.equal(avoidOffer(null), null);
});

test("where there is no way round, the notice says why", () => {
  const search = (alternate: "found" | "no_route" | "time" | null) => ({
    avoid_search: { passed: 1, penalty_s: 1800, decision: "kept" as const, alternate, avoided: 0 },
  });
  assert.equal(avoidNoAlternate(search("no_route")), "No route round it was found.");
  assert.match(avoidNoAlternate(search("time")) ?? "", /no time left/);
  assert.equal(avoidNoAlternate(search("found")), null);
  assert.equal(avoidNoAlternate({ avoid_search: null }), null);
});

test("the description's Avoid entry says its rating in words", () => {
  const entry = {
    kind: "avoid",
    severity: "avoid",
    text: "Avoid-rated junction ahead at 0.7 mi (1.1 km): Main St and 1st Ave, no gap in fast traffic. Riding through it is a really bad idea. Please reconsider your route.",
  } as DescriptionEntry;
  assert.ok(saysItsSeverity(entry));
});

test("the plea is the API's own words (the owner, 2026-10-10: \"this is a really bad idea, please reconsider\")", () => {
  const python = readFileSync(new URL("../../../src/routemaker/avoid_junctions.py", import.meta.url), "utf8");
  assert.ok(python.includes(`PLEA = "${AVOID_PLEA}"`), "src/routemaker/avoid_junctions.py PLEA");
  assert.match(AVOID_PLEA, /really bad idea/);
  assert.match(AVOID_PLEA, /reconsider/);
});

test("the road panel warns of an Avoid-rated junction on the route near the spot it was opened on", () => {
  const route = { avoid_junctions: [PASS] };
  // On the point, and a little off it (about 22 m north): the junction.
  assert.equal(avoidNearSpot(route, [PASS.lon, PASS.lat])?.id, PASS.id);
  assert.equal(avoidNearSpot(route, [PASS.lon, PASS.lat + 0.0002])?.id, PASS.id);
  // Past AVOID_SPOT_M (about 55 m), with no route, or from an older API: nothing.
  assert.ok(AVOID_SPOT_M >= 15 && AVOID_SPOT_M <= 50);
  assert.equal(avoidNearSpot(route, [PASS.lon, PASS.lat + 0.0005]), null);
  assert.equal(avoidNearSpot(null, [PASS.lon, PASS.lat]), null);
  assert.equal(avoidNearSpot({}, [PASS.lon, PASS.lat]), null);
  // The nearer of two.
  const other = { ...PASS, id: 99, lat: PASS.lat + 0.0003 };
  assert.equal(avoidNearSpot({ avoid_junctions: [other, PASS] }, [PASS.lon, PASS.lat + 0.0001])?.id, PASS.id);
});

test("the road panel's warning is plain, gives the stored reason, and asks the rider to reconsider", () => {
  assert.equal(AVOID_CARD_HEADING, "Avoid this intersection");
  assert.equal(
    avoidCardText(PASS),
    "Main St and 1st Ave is rated as dangerous for bikes: no gap in fast traffic. Riding through it is a really bad idea. Please reconsider your route.",
  );
  assert.equal(
    avoidCardText({ name: "", reason: "" }),
    "It is rated as dangerous for bikes. Riding through it is a really bad idea. Please reconsider your route.",
  );
  assert.equal(avoidCardSaid(PASS), `Avoid this intersection. ${avoidCardText(PASS)}`);
  assert.doesNotMatch(avoidCardSaid(PASS), /skull|\u2620/i);
});
