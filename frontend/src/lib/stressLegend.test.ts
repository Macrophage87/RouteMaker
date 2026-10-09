// What the legend says about zoom (owner, 2026-09-28: "Zoomed out just show the trails.").
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { STRESS_ZOOMS } from "./mapStyle.ts";
import { planToOpen, rememberPlanForPage } from "./signIn.ts";
import {
  CAR_FREE_NOTE,
  LTS_MEANS,
  STRESS_PAGE,
  STRESS_PAGE_TEXT,
  MTB_LEGEND,
  MtbTrailSwatch,
  ROADWAY_LANES,
  ROUTE_AT_EVERY_ZOOM,
  StressLegend,
  StressZoomNotes,
  UNKNOWN_SURFACE_LEGEND,
  UNPAVED_LEGEND,
  ZOOMED_OUT,
  dashPx,
  everyTrailFrom,
  facilityLegendHint,
  rideLayerText,
  stressZoomHint,
  stressZoomNotice,
} from "./stressLegend.ts";
import {
  FACILITIES,
  LEGEND_SWATCH_PX,
  PALETTES,
  UNKNOWN_SURFACE_DASH,
  UNPAVED_DASH,
  currentTiers,
  legendWidths,
  setAccessibility,
  setHighStressLanes,
  tiersFor,
  unpavedWidth,
  MTB_TRAIL,
  mtbTrailPaint,
} from "../stressStyle.js";
import { HIGH_STRESS_LANES_LABEL } from "./highStressLanesSwitch.ts";

test("zoomed out, with the overlay on, the notice says the road stress is a zoom away", () => {
  const out = stressZoomNotice(STRESS_ZOOMS.ride - 0.01, true);
  assert.equal(out, `Zoom in to see more paths and trails, calm roads and traffic stress on roads. ${ZOOMED_OUT}`);
  assert.ok(out!.startsWith("Zoom in to see more paths and trails, calm roads and traffic stress on roads. Zoomed out, only the long-distance"));
  assert.equal(stressZoomNotice(STRESS_ZOOMS.min, true), out);
});

test("at zoom 12-13 the notice says this is the where-to-ride view and what waits for zoom 14 (OWNER-DECISIONS 391)", () => {
  const out = stressZoomNotice(STRESS_ZOOMS.ride, true);
  assert.equal(
    out,
    "Zoom in to see busy roads and every street. This is the where-to-ride view: connected paths and trails and long calm roads. Busy roads, mountain-bike trails and short paths show from zoom 14.",
  );
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
  assert.ok(hint.startsWith(`${ZOOMED_OUT} A named paved trail counts when it runs 2.5 mi (4.0 km) or more at zoom 11, or 5.0 mi (8.0 km) at zoom 10;`));
  assert.ok(hint.includes("an unpaved one needs a regional bike route or a longer run. Trails beside a road count the same way."));
  assert.ok(hint.includes("Lines are drawn thinner at zooms 10 and 11."));
  assert.ok(hint.includes(everyTrailFrom(STRESS_ZOOMS.ride)));
  assert.equal(
    everyTrailFrom(12),
    "Paths on local routes and other connected paths show from zoom 12; mountain-bike trails and every short path show from zoom 14.",
  );
  // OWNER-DECISIONS 391: zoom 12-13 is where to ride, and says what waits for zoom 14.
  assert.ok(hint.includes(rideLayerText(STRESS_ZOOMS.ride, STRESS_ZOOMS.quiet)));
  assert.ok(
    hint.includes(
      "From zoom 12 the map shows where to ride: the paths and trails that connect into a network of 1,320 ft (0.4 km) or more, " +
        "and calm roads (LTS 1 and 2) that run 2.0 mi (3.2 km) or more without crossing or joining a busy road. Busy roads (LTS 3 and above, and best avoided), " +
        "mountain-bike trails, shorter paths, the other streets and the junction warnings on the map show from zoom 14.",
    ),
  );
  assert.ok(hint.includes(ROUTE_AT_EVERY_ZOOM));
  assert.match(ROUTE_AT_EVERY_ZOOM, /own busy stretches and junction warnings at every zoom/);
  assert.doesNotMatch(hint, /faintly,? and from zoom 14|show, faintly/, "no busy road is drawn at zoom 12-13 now");
  assert.ok(hint.includes(`From zoom ${STRESS_ZOOMS.quiet} the busy roads at LTS 3 and above and the quiet streets, footways and sidewalks show too, every line solid from zoom 14.`));
  assert.ok(hint.includes("Roads bikes may not use, such as expressways, are left unmarked."));
  assert.ok(hint.includes("shows only from zoom 15, and faintly, so the bike lane is the main line."));
  assert.ok(hint.includes("Alleys show only from zoom 16, faintly, and the roads inside cemeteries, parking lots, military bases and secure government sites, such as prisons and guarded research campuses, not at all, but for the numbered public roads and the few streets open to the public through them."));
  assert.match(hint, new RegExp(`Further out than zoom ${STRESS_ZOOMS.min} nothing`));
  assert.match(hint, / The map is at zoom 12\.$/);
  assert.doesNotMatch(stressZoomHint(null), /The map is at/);
});

test("rendered: the notice as a status, then the hint", () => {
  const html = renderToStaticMarkup(createElement(StressZoomNotes, { zoom: 11.2, shown: true }));
  assert.match(html, /^<p class="notice" role="status">Zoom in to see more paths and trails, calm roads and traffic stress on roads\./);
  assert.match(html, /<p class="hint">Zoomed out, only the long-distance paths and trails are shown: those on regional or national bike routes, long named trails, and roads closed to cars at set times\./);
  // The hint rendered is the one for the map's own zoom (round-1 mutant F08).
  assert.match(html, /The map is at zoom 11\.<\/p><p class="hint">Roads closed to cars/);
  const street = renderToStaticMarkup(createElement(StressZoomNotes, { zoom: 14, shown: true }));
  assert.doesNotMatch(street, /notice/);
  assert.match(street, /<p class="hint">/);
});

test("App's legend passes the zoom and whether the overlay is on", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  // App.tsx is not rendered by a test: it only places the legend (the legend itself is rendered below).
  // In the sidebar's Map layers sheet the zoom explanations are behind a disclosure (foldedZoom, OWNER-DECISIONS 312).
  assert.match(app, /<StressLegend facilities=\{facilitiesShown\} zoom=\{zoom\} shown=\{stressVisible\} foldedZoom \/>/);
});

test("one phrase for what the map shows zoomed out, wherever the legend says it", () => {
  assert.equal(
    ZOOMED_OUT,
    "Zoomed out, only the long-distance paths and trails are shown: those on regional or national bike routes, long named trails, and roads closed to cars at set times.",
  );
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
        // A ring first where the tier has one (371: two-tone LTS 3 and 4, and the legend's own round Avoid).
        const ringed = tier.ring ?? tier.legendRing;
        const all = rows[i].lines;
        if (ringed) {
          assert.equal(all[0].stroke, ringed, `${tier.short} ring`);
          assert.equal(Number(all[0]["stroke-width"]), widths.tiers[i].ring);
        }
        const [casing, ...rest] = ringed ? all.slice(1) : all;
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
  const rows = swatches(legendHtml()).slice(currentTiers().length + 2);
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
  assert.deepEqual(swatches(legendHtml(new Set(["lane"]))).slice(currentTiers().length + 2).map((r) => r.text.split(" ")[0]), ["Painted"]);
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

test("the legend has a row for the mountain-bike trails' not-for-routes line, in words, in the list, at every zoom (OWNER-DECISIONS 452a)", () => {
  assert.deepEqual(MTB_LEGEND, {
    short: "Mountain-bike trail",
    label: "Not used for routes (Gravel and Mountain Goat may use it): a thin grey dotted line.",
  });
  for (const strong of [false, true]) {
    withSwitches(strong, false, () => {
      for (const zoom of [10, 12, 14, 16]) {
        for (const foldedZoom of [false, true]) {
          const html = renderToStaticMarkup(createElement(StressLegend, { facilities: new Set(), zoom, shown: true, foldedZoom }));
          const list = html.slice(html.indexOf('aria-label="Traffic stress legend"'), html.indexOf("</ul>"));
          const row = /<li class="mtb-trail">([\s\S]*?)<\/li>/.exec(list);
          assert.ok(row, `zoom ${zoom}, folded ${foldedZoom}: the row is in the stress legend's list`);
          const text = row[1].replace(/<svg[\s\S]*?<\/svg>/, "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
          assert.equal(text, `${MTB_LEGEND!.short} ${MTB_LEGEND!.label}`);
          // The swatch is decoration: the words carry it for a screen reader.
          assert.match(row[1], /^<svg [^>]*aria-hidden="true"/);
          assert.ok(!html.includes("mtb-hidden") && !html.includes("not shown on the map"), "452's line is gone");
        }
      }
    });
  }
  // The live zoom notice does not repeat it (the review's nit); the zoom words say where they show from again.
  assert.doesNotMatch(stressZoomNotice(12, true)!, /not used|not shown/i);
});

test("the mountain-bike trail's swatch is the map's dots, on the base map's earth colour, wider and darker with the accessibility switch", () => {
  for (const strong of [false, true]) {
    const html = renderToStaticMarkup(createElement(MtbTrailSwatch, { strong }));
    const paint = mtbTrailPaint(strong);
    assert.ok(html.includes(`fill="${MTB_TRAIL.legendGround}"`), html);
    const line = /<line ([^>]*?)\/?>/.exec(html)![1];
    assert.ok(line.includes(`stroke="${paint["line-color"]}"`), line);
    assert.ok(line.includes(`stroke-width="${paint["line-width"]}"`), line);
    assert.ok(line.includes(`stroke-dasharray="${dashPx(MTB_TRAIL.dash, paint["line-width"])}"`), line);
    assert.ok(!html.includes("<line") || html.match(/<line/g)!.length === 1, "one line: no casing or rails");
  }
});

test("the legend has a Surface unknown row: LTS 1's casing and line in short dashes, and the words, no color alone (OWNER-DECISIONS 376, A)", () => {
  for (const strong of [false, true]) {
    withSwitches(strong, false, () => {
      const tiers = currentTiers();
      const widths = legendWidths(tiers);
      const rows = swatches(legendHtml());
      const row = rows[tiers.length + 1];
      assert.ok(row.text.startsWith("Surface unknown"), row.text);
      assert.ok(row.text.includes(UNKNOWN_SURFACE_LEGEND));
      const [casing, line] = row.lines;
      const dash = dashPx(UNKNOWN_SURFACE_DASH, widths.tiers[0].line);
      assert.equal(casing.stroke, tiers[0].casing);
      assert.equal(Number(casing["stroke-width"]), widths.tiers[0].casing);
      assert.equal(line.stroke, tiers[0].color);
      assert.equal(Number(line["stroke-width"]), widths.tiers[0].line);
      assert.equal(casing["stroke-dasharray"], dash, "the edge is dashed as the line is");
      assert.equal(line["stroke-dasharray"], dash);
      assert.ok(UNKNOWN_SURFACE_DASH.reduce((a, b) => a + b, 0) * widths.tiers[0].line <= LEGEND_SWATCH_PX, "a whole cycle shows");
    });
  }
  // Plain US English, what it is and why, naming the source; no jargon, no colour as the only cue.
  assert.match(UNKNOWN_SURFACE_LEGEND, /^A park path or trail away from roads with no surface mapped in OpenStreetMap, so it may be paved or unpaved: short dashes in the LTS 1 colors, with no edge lines\. A trail beside a road, or a path built for bicycles \(a bike path or a path signed for bicycles\), with no surface mapped shows as a paved path\.$/);
  assert.doesNotMatch(UNKNOWN_SURFACE_LEGEND, /colour|tile|property|null/);
});


test("the legend links to the page on how ratings work, in the same tab, its name its visible words (461)", () => {
  const html = legendHtml();
  const link = html.match(/<p class="hint stress-page-link"><a href="([^"]+)"([^>]*)>([\s\S]*?)<\/a><\/p>/);
  assert.ok(link, html.slice(0, 400));
  assert.equal(link[1], STRESS_PAGE);
  assert.equal(link[2], "", "no target or other attribute: it opens in the same tab");
  assert.equal(link[3], STRESS_PAGE_TEXT, "plain visible words, no hidden span (the accessibility review's N8)");
  assert.equal(STRESS_PAGE_TEXT, "How stress ratings work");
  assert.ok(html.indexOf("stress-page-link") > html.indexOf("lts-means"), "after the line that says what LTS is");
});

test("following the stress page link keeps the plan for the page's Back to the map (the accessibility review's SF1)", () => {
  const source = readFileSync(new URL("./stressLegend.ts", import.meta.url), "utf8");
  const body = source.slice(source.indexOf("export function StressPageLink"), source.indexOf("/** The unpaved mark's line"));
  assert.match(body, /h\("a", \{ href: STRESS_PAGE, onClick: \(\) => rememberPlanForPage\(tabSession\(\), window\.location\.hash\) \}, STRESS_PAGE_TEXT\)/);
  // The page's own links go to a bare "/": the plan comes back from this tab's storage, once.
  const store = new Map<string, string>();
  const storage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  };
  const plan = "#v=1&p=-77.03,38.9;-77.0,38.91&preset=default";
  rememberPlanForPage(storage, plan);
  assert.equal(planToOpen(storage, ""), plan);
  assert.equal(planToOpen(storage, ""), "", "read once");
  rememberPlanForPage(storage, "");
  assert.equal(planToOpen(storage, ""), "", "an empty planner keeps nothing");
  const page = readFileSync(new URL("../../public/about/stress.html", import.meta.url), "utf8");
  assert.deepEqual(
    [...page.matchAll(/<a [^>]*>Back to the map<\/a>/g)].map((m) => m[0]),
    ['<a class="back" href="/">Back to the map</a>', '<a href="/">Back to the map</a>'],
    "both go to a bare /, where planToOpen reads the kept plan",
  );
});

test("the road panel shows the same link at the end of Details and sources (correctness C4, mutation T1)", () => {
  const panel = readFileSync(new URL("../RoadInfoDialog.tsx", import.meta.url), "utf8");
  assert.match(panel, /import \{ StressPageLink \} from "\.\/lib\/stressLegend\.ts";/);
  const open = panel.indexOf('className="road-info-details"');
  const close = panel.indexOf("</details>", open);
  assert.ok(open > 0 && close > open, "the Details and sources disclosure");
  const inside = panel.slice(open, close);
  assert.equal((inside.match(/<StressPageLink\b/g) ?? []).length, 1);
  assert.match(inside, /<StressPageLink className="road-info-how" \/>\s*$/, "its last item");
  assert.equal((panel.match(/<StressPageLink\b/g) ?? []).length, 1, "once in the panel");
});
