// What the legend says about zoom (owner, 2026-09-28: "Zoomed out just show the trails.").
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { STRESS_ZOOMS } from "./mapStyle.ts";
import {
  CAR_FREE_NOTE,
  LTS_MEANS,
  ROADWAY_LANES,
  StressLegend,
  StressZoomNotes,
  UNPAVED_LEGEND,
  ZOOMED_OUT,
  dashPx,
  facilityLegendHint,
  stressZoomHint,
  stressZoomNotice,
} from "./stressLegend.ts";
import {
  FACILITIES,
  LEGEND_SWATCH_PX,
  PALETTES,
  UNPAVED_DASH,
  currentTiers,
  legendWidths,
  setAccessibility,
  setHighStressLanes,
  tiersFor,
  unpavedWidth,
} from "../stressStyle.js";
import { HIGH_STRESS_LANES_LABEL } from "./highStressLanesSwitch.ts";

test("zoomed out, with the overlay on, the notice says the road stress is a zoom away", () => {
  const out = stressZoomNotice(STRESS_ZOOMS.busy - 0.01, true);
  assert.equal(out, "Zoom in to see traffic stress on roads. Zoomed out, only traffic-free paths and trails are shown.");
  assert.equal(stressZoomNotice(STRESS_ZOOMS.min, true), out);
});

test("at busy-road zoom the notice says the quiet streets are a zoom away, and the busy roads faint", () => {
  const out = stressZoomNotice(STRESS_ZOOMS.busy, true);
  assert.equal(out, "Zoom in to see the quiet streets. Busy roads are drawn faintly until zoom 14.");
  assert.equal(stressZoomNotice(STRESS_ZOOMS.quiet - 0.01, true), out);
});

test("from the quiet streets' zoom there is no notice; below the tiles' zoom it asks for a zoom in", () => {
  assert.equal(stressZoomNotice(STRESS_ZOOMS.quiet, true), null);
  assert.equal(stressZoomNotice(16, true), null);
  assert.equal(stressZoomNotice(STRESS_ZOOMS.min - 0.5, true), "Zoom in to see traffic-free paths, trails and traffic stress.");
});

test("with the overlay off, or before the map has a zoom, there is no notice", () => {
  assert.equal(stressZoomNotice(11, false), null);
  assert.equal(stressZoomNotice(null, true), null);
});

test("the standing hint names the zooms from STRESS_ZOOMS and the zoom the map is at", () => {
  const hint = stressZoomHint(12.7);
  assert.ok(hint.startsWith(`${ZOOMED_OUT} Trails beside a road are among them.`));
  assert.ok(hint.includes(`From zoom ${STRESS_ZOOMS.busy} the busy roads at LTS 3 and above show, faintly,`));
  assert.ok(hint.includes(`from zoom ${STRESS_ZOOMS.quiet} the quiet streets, footways and sidewalks, with every line solid from zoom 14.`));
  assert.ok(hint.includes("Roads bikes may not use, such as expressways, are left unmarked."));
  assert.ok(hint.includes("shows only from zoom 15, and faintly, so the bike lane is the main line."));
  assert.ok(hint.includes("Alleys show only from zoom 16, faintly, and the roads inside cemeteries, military bases and parking lots not at all."));
  assert.match(hint, new RegExp(`Further out than zoom ${STRESS_ZOOMS.min} nothing`));
  assert.match(hint, / The map is at zoom 12\.$/);
  assert.doesNotMatch(stressZoomHint(null), /The map is at/);
});

test("rendered: the notice as a status, then the hint", () => {
  const html = renderToStaticMarkup(createElement(StressZoomNotes, { zoom: 11.2, shown: true }));
  assert.match(html, /^<p class="notice" role="status">Zoom in to see traffic stress on roads\./);
  assert.match(html, /<p class="hint">Zoomed out, only traffic-free paths and trails are shown\./);
  // The hint rendered is the one for the map's own zoom (round-1 mutant F08).
  assert.match(html, /The map is at zoom 11\.<\/p><p class="hint">Roads closed to cars/);
  const street = renderToStaticMarkup(createElement(StressZoomNotes, { zoom: 14, shown: true }));
  assert.doesNotMatch(street, /notice/);
  assert.match(street, /<p class="hint">/);
});

test("App's legend passes the zoom and whether the overlay is on", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  // App.tsx is not rendered by a test: it only places the legend (the legend itself is rendered below).
  assert.match(app, /<StressLegend facilities=\{facilitiesShown\} zoom=\{zoom\} shown=\{stressVisible\} \/>/);
});

test("one phrase for what the map shows zoomed out, wherever the legend says it", () => {
  assert.equal(ZOOMED_OUT, "Zoomed out, only traffic-free paths and trails are shown.");
  assert.ok(stressZoomNotice(11, true)!.endsWith(ZOOMED_OUT));
  assert.ok(stressZoomHint(11).startsWith(ZOOMED_OUT));
  assert.equal(ROADWAY_LANES, "Protected lanes in the roadway show with their street.");
  const html = renderToStaticMarkup(createElement(StressLegend, { facilities: new Set(["path"]), zoom: 11, shown: true }));
  assert.ok(html.includes(`Sharrows count as ordinary streets. ${ROADWAY_LANES}`));
  assert.doesNotMatch(html, /only the paths|only the trails/);
});

test("the legend says car-free roads are traffic-free paths, and the timed ones follow the ride time", () => {
  assert.ok(CAR_FREE_NOTE.startsWith("Roads closed to cars are shown as traffic-free paths"));
  assert.match(CAR_FREE_NOTE, /Sligo Creek Parkway on weekends/);
  assert.ok(CAR_FREE_NOTE.endsWith("when that ride time is chosen."));
  const html = renderToStaticMarkup(createElement(StressZoomNotes, { zoom: 14, shown: true }));
  assert.ok(html.includes(CAR_FREE_NOTE));
});

// ---- the legend, rendered (moved out of App.tsx so its drawing is tested, not read) ----

const ALL = new Set(["path", "protected", "lane"]);
const legendHtml = (facilities: ReadonlySet<string> = ALL) =>
  renderToStaticMarkup(createElement(StressLegend, { facilities, zoom: 15, shown: true }));

/** The legend's SVG lines, list item by list item: each item's lines' attributes. */
function swatches(html: string): Array<{ text: string; svgWidth: number; lines: Array<Record<string, string>> }> {
  return [...html.matchAll(/<li>(<svg[^>]*>[\s\S]*?<\/svg>)([\s\S]*?)<\/li>/g)].map((m) => ({
    text: m[2].replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim(),
    svgWidth: Number(/<svg width="([\d.]+)"/.exec(m[1])?.[1]),
    lines: [...m[1].matchAll(/<line ([^>]*?)\/?>/g)].map((l) => Object.fromEntries([...l[1].matchAll(/([a-z0-9-]+)="([^"]*)"/g)].map((a) => [a[1], a[2]]))),
  }));
}

function withSwitches(accessibility: boolean, lanes: boolean, body: () => void): void {
  setAccessibility(accessibility, { remember: false });
  setHighStressLanes(lanes, { remember: false });
  try {
    body();
  } finally {
    setAccessibility(false, { remember: false });
    setHighStressLanes(false, { remember: false });
  }
}

test("the legend's first line says what LTS is, in plain words (the a11y review's N2)", () => {
  const html = legendHtml();
  assert.ok(html.startsWith(`<p class="hint lts-means">${LTS_MEANS}</p>`), html.slice(0, 120));
  assert.match(LTS_MEANS, /^LTS is Level of Traffic Stress, from 1 \(calmest\) to 4 \(heavy traffic\)/);
});

test("each tier's swatch draws its casing, then its line with its dash, at the map's widths, plain and strong", () => {
  for (const strong of [false, true]) {
    withSwitches(strong, false, () => {
      const tiers = currentTiers();
      const widths = legendWidths(tiers);
      const rows = swatches(legendHtml()).slice(0, tiers.length);
      tiers.forEach((tier, i) => {
        // Casing, then (for a tier with a gap colour of its own, LTS 2, OWNER-DECISIONS 356) the gap line, then the dashed line.
        const [casing, ...rest] = rows[i].lines;
        const line = rest.at(-1)!;
        if (tier.dash && tier.gap !== tier.casing) {
          assert.equal(rest.length, 2, `${tier.short}: a gap line`);
          assert.equal(rest[0].stroke, tier.gap);
          assert.equal(Number(rest[0]["stroke-width"]), widths.tiers[i].line);
          assert.equal(rest[0]["stroke-dasharray"], undefined, "the gap line is solid");
        }
        assert.equal(casing.stroke, tier.casing, `${tier.short} casing`);
        assert.equal(Number(casing["stroke-width"]), widths.tiers[i].casing);
        assert.equal(line.stroke, tier.color);
        assert.equal(Number(line["stroke-width"]), widths.tiers[i].line);
        // The legend's dash is the tier's, scaled by its width; a solid line has none (OWNER-DECISIONS 279).
        assert.equal(line["stroke-dasharray"], tier.dash ? tier.dash.map((d: number) => d * widths.tiers[i].line).join(" ") : undefined, `${tier.short} dash`);
        assert.ok(rows[i].text.startsWith(`${tier.short} ${tier.label}`), rows[i].text);
      });
    });
  }
});

test("a swatch is long enough for a whole dash cycle of every tier, rail and the unpaved mark, in every palette, plain and strong (the a11y review's SF5)", (t) => {
  const cycle = (dash: readonly number[] | null, width: number) => (dash ? dash.reduce((a, b) => a + b, 0) * width : 0);
  let longest = 0;
  for (const palette of Object.keys(PALETTES)) {
    for (const strong of [false, true]) {
      const tiers = tiersFor(palette, strong);
      const widths = legendWidths(tiers);
      tiers.forEach((tier, i) => {
        const period = cycle(tier.dash, widths.tiers[i].line);
        longest = Math.max(longest, period);
        assert.ok(period <= LEGEND_SWATCH_PX, `${palette}${strong ? " strong" : ""} ${tier.short}: ${period} px a cycle, ${LEGEND_SWATCH_PX} px of swatch`);
      });
      for (const facility of FACILITIES) {
        const period = cycle(facility.dash, widths.rails[facility.facility]);
        assert.ok(period <= LEGEND_SWATCH_PX, `${facility.short}: ${period} px`);
      }
      assert.ok(cycle(UNPAVED_DASH, unpavedWidth(tiers[0])) <= LEGEND_SWATCH_PX);
    }
  }
  t.diagnostic(`the longest dash cycle is ${longest} px; the swatch is ${LEGEND_SWATCH_PX} px`);
  // The swatches drawn are that long.
  const rows = swatches(legendHtml());
  rows.forEach((row, r) => {
    assert.equal(row.svgWidth, LEGEND_SWATCH_PX + 4);
    if (r === currentTiers().length) {
      // The unpaved ramp: its stretches, one a tier, run the swatch's length end to end.
      const casings = row.lines.filter((_, i) => i % 3 === 0);
      assert.equal(Number(casings.at(-1)!.x2) - Number(casings[0].x1), LEGEND_SWATCH_PX, row.text);
      return;
    }
    for (const line of row.lines) assert.equal(Number(line.x2) - Number(line.x1), LEGEND_SWATCH_PX, row.text);
  });
});

test("the Unpaved row draws the brown ramp light to dark, each on its casing with the map's dots, and says so in words (OWNER-DECISIONS 302)", () => {
  for (const strong of [false, true]) {
    withSwitches(strong, false, () => {
      const tiers = currentTiers();
      const widths = legendWidths(tiers);
      const row = swatches(legendHtml())[tiers.length];
      assert.equal(row.text, `Unpaved ${UNPAVED_LEGEND}`);
      assert.equal(row.lines.length, 3 * tiers.length);
      tiers.forEach((tier, i) => {
        const [casing, line, mark] = row.lines.slice(3 * i, 3 * i + 3);
        assert.equal(casing.stroke, tier.unpavedCasing, `${tier.short} casing`);
        assert.equal(Number(casing["stroke-width"]), widths.tiers[0].casing);
        assert.equal(line.stroke, tier.unpavedColor, `${tier.short} brown`);
        assert.equal(line["stroke-dasharray"], undefined);
        assert.equal(mark.stroke, tier.unpavedCasing);
        assert.equal(Number(mark["stroke-width"]), unpavedWidth(tiers[0]));
        assert.equal(mark["stroke-dasharray"], dashPx(UNPAVED_DASH, unpavedWidth(tiers[0])));
      });
    });
  }
  assert.match(UNPAVED_LEGEND, /^Brown, darker = busier: gravel, dirt or other unpaved surface, with the dashes above and a dotted center line\. An unpaved trail has no edge lines, which a paved path has\.$/);
  assert.doesNotMatch(UNPAVED_LEGEND, /path edges/, "plain words (the a11y review's N2)");
});

test("the bike-facility legend lists the rails the map has drawn, in FACILITIES' order, each with its dash under the casing", () => {
  const widths = legendWidths(currentTiers());
  const rows = swatches(legendHtml()).slice(currentTiers().length + 1);
  assert.deepEqual(rows.map((r) => r.text.split(" ")[0]), FACILITIES.map((f) => f.short));
  FACILITIES.forEach((facility, i) => {
    const [rail, casing] = rows[i].lines;
    assert.equal(rail.stroke, facility.color);
    assert.equal(Number(rail["stroke-width"]), widths.rails[facility.facility]);
    assert.equal(rail["stroke-dasharray"], dashPx(facility.dash, widths.rails[facility.facility]));
    assert.equal(casing.stroke, "#ffffff");
    assert.equal(Number(casing["stroke-width"]), widths.facilityCasing);
  });
  // Only what the map has drawn; none, and there is no facility legend at all.
  assert.deepEqual(swatches(legendHtml(new Set(["lane"]))).slice(currentTiers().length + 1).map((r) => r.text.split(" ")[0]), ["Painted"]);
  assert.doesNotMatch(legendHtml(new Set()), /Bike facility legend|Sharrows/);
});

test("the bike-facility legend's words follow the lane switch, in plain words", () => {
  withSwitches(false, false, () => assert.ok(legendHtml().includes(facilityLegendHint(false).replace(/"/g, "&quot;"))));
  withSwitches(false, true, () => assert.ok(legendHtml().includes(facilityLegendHint(true))));
  assert.match(facilityLegendHint(false), /Painted lanes on heavy-traffic \(LTS 4\) and best-avoided roads are hidden unless you turn on "Show bike lanes on high-stress roads"\.$/);
  assert.ok(facilityLegendHint(false).includes(HIGH_STRESS_LANES_LABEL));
  assert.match(facilityLegendHint(true), /are shown, because the switch above is on\.$/);
  assert.match(facilityLegendHint(true), /a solid dark rail for a paved path/);
  assert.match(facilityLegendHint(true), /An unpaved trail has no edge lines, only the dotted center line\./);
  for (const on of [false, true]) assert.doesNotMatch(facilityLegendHint(on), /LTS 4 and Avoid|path edges/);
});

test("the legend passes the zoom and whether the overlay is on to the zoom notes", () => {
  const out = renderToStaticMarkup(createElement(StressLegend, { facilities: new Set(), zoom: 11, shown: true }));
  assert.ok(out.includes(stressZoomNotice(11, true)!));
  assert.ok(out.includes(stressZoomHint(11)));
  const hidden = renderToStaticMarkup(createElement(StressLegend, { facilities: new Set(), zoom: 11, shown: false }));
  assert.ok(!hidden.includes(stressZoomNotice(11, true)!), "no notice while the overlay is off");
});
