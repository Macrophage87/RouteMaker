// OWNER-DECISIONS 275: painted bike lanes on LTS 4 and Avoid roads are hidden
// unless the rider turns "Show bike lanes on high-stress roads" on. The
// overlay's filter, the route panel's facility bar, the route description,
// the switch's persistence and its markup. The threshold (4) and the default
// (off) are pinned from more than one side so a mutant of either fails.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as spec from "@maplibre/maplibre-gl-style-spec";
import {
  FACILITIES,
  HIGH_STRESS_LANES_STORAGE_KEY,
  HIGH_STRESS_LANE_MIN_TIER,
  facilityLayers,
  highStressLanesOn,
  rememberHighStressLanes,
  setHighStressLanes,
  storedHighStressLanes,
  stressFilters,
  subscribeHighStressLanes,
} from "../stressStyle.js";
import { facilityMetresShown, facilityRows, highStressLaneMetres } from "./facilityBar.ts";
import { descriptionEntries, descriptionText, withoutHighStressLane } from "./routeDescription.ts";
import {
  HIGH_STRESS_LANES_HINT,
  HIGH_STRESS_LANES_LABEL,
  HighStressLanesSwitch,
} from "./highStressLanesSwitch.ts";
import type { DescriptionEntry } from "./api.ts";

/** Whether a layer's filter draws a feature with these properties. */
function draws(layerId: string, properties: Record<string, unknown>, showHigh: boolean, when?: string): boolean {
  const layer = facilityLayers("s", when as never, showHigh).find((l: { id: string }) => l.id === layerId) as { id: string; filter: unknown };
  const { filter } = spec.featureFilter(layer.filter as never, `layers[${layer.id}].filter`);
  return filter({ zoom: 14 } as never, { type: 2, properties, geometry: [] } as never);
}

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return { data, getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v) };
}

// ---- the overlay -----------------------------------------------------------

test("the threshold is LTS 4: a painted lane is drawn on tiers 1, 2, 3 and on an unrated road, and not on 4 or 5, while the switch is off", () => {
  assert.equal(HIGH_STRESS_LANE_MIN_TIER, 4);
  for (const tier of [1, 2, 3]) assert.equal(draws("facility-lane", { tier, facility: "lane" }, false), true, `LTS ${tier}`);
  assert.equal(draws("facility-lane", { facility: "lane" }, false), true, "an unrated road (no tier) keeps its lane");
  for (const tier of [4, 5]) assert.equal(draws("facility-lane", { tier, facility: "lane" }, false), false, `LTS ${tier} ${tier === 5 ? "(Avoid)" : ""}`);
});

test("with the switch on, a painted lane is drawn at every tier", () => {
  for (const tier of [1, 2, 3, 4, 5]) assert.equal(draws("facility-lane", { tier, facility: "lane" }, true), true, `LTS ${tier}`);
});

test("protected lanes and paths are drawn at every tier whatever the switch says (only paint is hidden)", () => {
  for (const showHigh of [false, true]) {
    for (const tier of [1, 2, 3, 4, 5]) {
      assert.equal(draws("facility-protected", { tier, facility: "protected" }, showHigh), true, `protected LTS ${tier}`);
      assert.equal(draws("facility-path", { tier, facility: "path" }, showHigh), true, `path LTS ${tier}`);
    }
  }
});

test("a road closed to cars at the ride's time is a path at tier 1: its path rails show, and no lane is hidden", () => {
  assert.equal(draws("facility-path", { tier: 5, facility: "lane", car_free: "weekend" }, false, "weekend"), true);
});

test("only the painted layer's filter changes with the switch: the stress layers and the other rails are the same", () => {
  const off = stressFilters(undefined, false);
  const on = stressFilters(undefined, true);
  for (const id of Object.keys(off)) {
    if (id === "facility-lane") assert.notDeepEqual(off[id], on[id]);
    else assert.deepEqual(off[id], on[id], id);
  }
});

test("the switch is off by default, and the filters read the setting when it is not given", () => {
  assert.equal(highStressLanesOn(), false, "off by default");
  assert.deepEqual(stressFilters(), stressFilters(undefined, false));
  try {
    setHighStressLanes(true, { remember: false });
    assert.deepEqual(stressFilters(), stressFilters(undefined, true));
  } finally {
    setHighStressLanes(false, { remember: false });
  }
  assert.equal(highStressLanesOn(), false);
});

// ---- persistence -----------------------------------------------------------

test("the switch is remembered per browser, as 'on' or 'off', and reads back", () => {
  assert.equal(HIGH_STRESS_LANES_STORAGE_KEY, "routemaker.highStressLanes");
  const storage = memoryStorage();
  assert.equal(storedHighStressLanes(storage), null, "nothing stored: no choice");
  assert.equal(rememberHighStressLanes(true, storage), true);
  assert.equal(storage.data.get(HIGH_STRESS_LANES_STORAGE_KEY), "on");
  assert.equal(storedHighStressLanes(storage), true);
  rememberHighStressLanes(false, storage);
  assert.equal(storage.data.get(HIGH_STRESS_LANES_STORAGE_KEY), "off");
  assert.equal(storedHighStressLanes(storage), false);
  assert.equal(storedHighStressLanes(memoryStorage({ [HIGH_STRESS_LANES_STORAGE_KEY]: "yes" })), null, "a value this page did not write is ignored");
});

test("storage that throws or is missing never breaks the switch: it lasts the visit", () => {
  const throwing = {
    getItem: (): string | null => {
      throw new Error("SecurityError");
    },
    setItem: (): void => {
      throw new Error("SecurityError");
    },
  };
  assert.equal(storedHighStressLanes(throwing), null);
  assert.equal(rememberHighStressLanes(true, throwing), false);
  assert.equal(rememberHighStressLanes(true, null as never), false);
  try {
    setHighStressLanes(true, { storage: throwing });
    assert.equal(highStressLanesOn(), true, "set for the visit though storage refused");
  } finally {
    setHighStressLanes(false, { remember: false });
  }
});

test("setHighStressLanes stores the choice, tells the subscribers once per change, and a trial leaves storage alone", () => {
  const storage = memoryStorage();
  const seen: boolean[] = [];
  const stop = subscribeHighStressLanes((on: boolean) => void seen.push(on));
  try {
    setHighStressLanes(true, { storage });
    setHighStressLanes(true, { storage });
    assert.deepEqual(seen, [true], "no second tell for no change");
    assert.equal(storage.data.get(HIGH_STRESS_LANES_STORAGE_KEY), "on");
    setHighStressLanes(false, { remember: false, storage });
    assert.deepEqual(seen, [true, false]);
    assert.equal(storage.data.get(HIGH_STRESS_LANES_STORAGE_KEY), "on", "a trial does not touch what is stored");
    setHighStressLanes("yes" as never, { remember: false });
    assert.equal(highStressLanesOn(), false, "only true turns it on");
  } finally {
    stop();
    setHighStressLanes(false, { remember: false });
  }
  setHighStressLanes(true, { remember: false });
  assert.deepEqual(seen, [true, false], "stopped");
  setHighStressLanes(false, { remember: false });
});

let loads = 0;
/** A fresh copy of stressStyle.js, evaluated as a page load would with this localStorage. */
async function loadedWith(storage: unknown): Promise<{ highStressLanesOn(): boolean }> {
  const saved = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: storage });
  try {
    loads += 1;
    return (await import(`../stressStyle.js?lanes=${loads}`)) as { highStressLanesOn(): boolean };
  } finally {
    if (saved) Object.defineProperty(globalThis, "localStorage", saved);
    else delete (globalThis as Record<string, unknown>).localStorage;
  }
}

test("on load: off with nothing stored or with 'off'; on only when 'on' was stored", async () => {
  assert.equal((await loadedWith(memoryStorage())).highStressLanesOn(), false);
  assert.equal((await loadedWith(memoryStorage({ [HIGH_STRESS_LANES_STORAGE_KEY]: "off" }))).highStressLanesOn(), false);
  assert.equal((await loadedWith(memoryStorage({ [HIGH_STRESS_LANES_STORAGE_KEY]: "garbage" }))).highStressLanesOn(), false);
  assert.equal((await loadedWith(memoryStorage({ [HIGH_STRESS_LANES_STORAGE_KEY]: "on" }))).highStressLanesOn(), true);
  assert.equal((await loadedWith(undefined)).highStressLanesOn(), false, "no storage at all");
});

// ---- the route panel's facility bar ---------------------------------------

const spans = [
  { from_m: 0, to_m: 1000, tier: 2, facility: "lane" as const },
  { from_m: 1000, to_m: 1600, tier: 4, facility: "lane" as const },
  { from_m: 1600, to_m: 2000, tier: 5, facility: "lane" as const },
  { from_m: 2000, to_m: 2500, tier: 4, facility: "protected" as const },
  { from_m: 2500, to_m: 3000, tier: 3, facility: "none" as const },
];
const totals = { path: 0, protected: 500, lane: 2000, none: 500 };

test("the facility bar counts painted lane on LTS 4 and Avoid as 'no facility' while the switch is off", () => {
  assert.equal(highStressLaneMetres(spans), 1000);
  assert.deepEqual(facilityMetresShown(totals, spans, false), { path: 0, protected: 500, lane: 1000, none: 1500 });
  const rows = facilityRows(totals, spans, false);
  const metres = Object.fromEntries(rows.map((r) => [r.key, r.metres]));
  assert.equal(metres.lane, 1000);
  assert.equal(metres.none, 1500);
  assert.equal(metres.protected, 500, "protected lane on LTS 4 stays protected");
  assert.equal(rows.reduce((s, r) => s + r.percent, 0), 100);
});

test("with the switch on, or without spans, the bar is the API's totals", () => {
  assert.deepEqual(facilityMetresShown(totals, spans, true), totals);
  assert.deepEqual(facilityMetresShown(totals, undefined, false), totals);
  assert.deepEqual(facilityMetresShown(totals, [], false), totals);
  assert.equal(facilityRows(totals, spans, true).find((r) => r.key === "lane")?.metres, 2000);
  assert.equal(facilityRows(totals).find((r) => r.key === "lane")?.metres, 2000, "no spans: as before");
});

test("the bar's threshold is LTS 4: a painted span on LTS 3 is counted, one on LTS 4 is not", () => {
  const at = (tier: number) => highStressLaneMetres([{ from_m: 0, to_m: 100, tier, facility: "lane" }]);
  assert.equal(at(3), 0);
  assert.equal(at(4), 100);
  assert.equal(at(5), 100);
  assert.equal(highStressLaneMetres([{ from_m: 0, to_m: 100, tier: null, facility: "lane" }]), 0, "an unrated stretch is not high stress");
  assert.equal(highStressLaneMetres([{ from_m: 0, to_m: 100, tier: 5, facility: "path" }]), 0, "only paint is moved");
});

test("the bar never moves more painted lane than the route has, and keeps the default off", () => {
  assert.deepEqual(facilityMetresShown({ lane: 300, none: 0 }, spans, false), { lane: 0, none: 300 });
  // facilityRows' own default is off, as the setting's is.
  assert.equal(facilityRows(totals, spans).find((r) => r.key === "lane")?.metres, 1000);
});

// ---- the route description -------------------------------------------------

const entry = (over: Partial<DescriptionEntry>): DescriptionEntry => ({
  kind: "stretch",
  from_m: 0,
  to_m: 500,
  from_mi: 0,
  to_mi: 0.3,
  street: "Kenilworth Avenue Northeast",
  tier: 4,
  facility: "lane",
  turn: null,
  text: "0.0 to 0.3 mi (0.0 to 0.5 km): Kenilworth Avenue Northeast, heavy traffic (LTS 4), painted bike lane.",
  ...over,
});

test("a stretch on LTS 4 or Avoid is not called a bike lane while the switch is off", () => {
  const four = withoutHighStressLane(entry({}));
  assert.equal(four.facility, null);
  assert.ok(!/bike lane/.test(four.text), four.text);
  assert.match(four.text, /heavy traffic \(LTS 4\)/, "the stress rating stays");
  const five = withoutHighStressLane(entry({ tier: 5, text: "x, Avoid (legal, but best avoided), painted bike lane." }));
  assert.ok(!/bike lane/.test(five.text) && /Avoid/.test(five.text));
});

test("everything else in the description is left as it is: LTS 3 paint, protected lanes, paths and other stretches", () => {
  const three = entry({ tier: 3, text: "a, busy road (LTS 3), painted bike lane." });
  assert.equal(withoutHighStressLane(three), three, "painted on LTS 3 stays a bike lane");
  const protectedFour = entry({ facility: "protected", text: "a, heavy traffic (LTS 4), protected bike lane." });
  assert.equal(withoutHighStressLane(protectedFour), protectedFour);
  const none = entry({ facility: null, text: "a, heavy traffic (LTS 4)." });
  assert.equal(withoutHighStressLane(none), none);
  const unrated = entry({ tier: null, text: "a, stress not rated, painted bike lane." });
  assert.equal(withoutHighStressLane(unrated), unrated);
});

const route = {
  preset: "default",
  distance_m: 3000,
  description: [entry({}), entry({ tier: 2, text: "b, fairly low stress (LTS 2), painted bike lane." })],
  description_overview: [entry({}), entry({ tier: 2, text: "b, fairly low stress (LTS 2), painted bike lane." })],
} as never;

test("descriptionEntries and the text for the clipboard and file follow the switch, off by default", () => {
  const off = descriptionEntries(route, "full") ?? [];
  assert.ok(!/bike lane/.test(off[0].text) && /painted bike lane/.test(off[1].text));
  const on = descriptionEntries(route, "full", true) ?? [];
  assert.match(on[0].text, /painted bike lane/);
  assert.ok(!/LTS 4\), painted bike lane/.test(descriptionText(route, "full")), "the copied text too");
  try {
    setHighStressLanes(true, { remember: false });
    assert.match(descriptionText(route, "full"), /LTS 4\), painted bike lane/);
  } finally {
    setHighStressLanes(false, { remember: false });
  }
});

test("the description and the facility bar are wired to the switch in the components", () => {
  const read = (name: string) => readFileSync(new URL(`../${name}`, import.meta.url), "utf8");
  assert.match(read("RouteDescription.tsx"), /useHighStressLanes\(\)[\s\S]*descriptionEntries\(route, view, showHighLanes\)/);
  assert.match(read("FacilityBreakdown.tsx"), /useHighStressLanes\(\)[\s\S]*facilityRows\(route\.facility_m, route\.stress_spans, showHighLanes\)/);
  assert.match(read("MapView.tsx"), /subscribeHighStressLanes\(\(\) => \{[\s\S]*setStressWhen\(map, callbacks\.current\.when\)/);
});

// ---- the switch's markup, and the legend's words ---------------------------

test("the switch is a labelled role=switch button with its state in words and a description of which roads are affected", () => {
  const off = renderToStaticMarkup(createElement(HighStressLanesSwitch, { on: false, onChange: () => {} }));
  assert.match(off, /<button type="button" role="switch" id="high-lanes-switch" class="switch" aria-checked="false" aria-labelledby="high-lanes-label" aria-describedby="high-lanes-hint">/);
  assert.match(off, /<span id="high-lanes-label" class="switch-label">Show bike lanes on high-stress roads<\/span>/);
  assert.equal(HIGH_STRESS_LANES_LABEL, "Show bike lanes on high-stress roads");
  assert.match(off, /<span class="switch-state" aria-hidden="true">Off<\/span>/);
  assert.match(off, /<p class="hint" id="high-lanes-hint">/);
  assert.match(HIGH_STRESS_LANES_HINT, /LTS 4 and Avoid/);
  assert.match(HIGH_STRESS_LANES_HINT, /Protected lanes and paths always show/);
  // Read on every focus: kept short.
  assert.ok(HIGH_STRESS_LANES_HINT.length < 150, `${HIGH_STRESS_LANES_HINT.length} characters`);
  const on = renderToStaticMarkup(createElement(HighStressLanesSwitch, { on: true, onChange: () => {} }));
  assert.match(on, /aria-checked="true"/);
  assert.match(on, />On<\/span>/);
});

test("pressing the switch asks for the opposite state", () => {
  const got: boolean[] = [];
  for (const on of [false, true]) {
    const element = HighStressLanesSwitch({ on, onChange: (next) => void got.push(next) });
    const button = (element.props.children as Array<{ type?: string; props?: { onClick?: () => void } }>).find((c) => c?.type === "button");
    button?.props?.onClick?.();
  }
  assert.deepEqual(got, [true, false]);
});

test("the panel places the switch after the Accessibility switch, only with the overlay there, and the facility legend says which roads it hides", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  // Next after the Accessibility switch, and inside the block drawn only when the stress overlay is available.
  assert.match(
    app,
    /<AccessibilitySwitch[\s\S]*?\/>\s*\{stress === "available" && \(\s*<>\s*(?:\{\/\*[\s\S]*?\*\/\}\s*)?<HighStressLanesSwitch on=\{showHighLanes\} onChange=\{\(on\) => setHighStressLanes\(on\)\} \/>/,
  );
  assert.equal((app.match(/<HighStressLanesSwitch /g) ?? []).length, 1, "drawn in one place only");
  assert.match(app, /Painted lanes on LTS 4 and Avoid roads are/);
  assert.match(app, /Show bike lanes on high-stress roads/);
  assert.ok(FACILITIES.length === 3);
});

// ---- the API's own wording (review SF3) ------------------------------------

test("the API's text_lanes_hidden is used where the API sends it: its words, and no facility", () => {
  const hidden = "0.0 to 0.3 mi (0.0 to 0.5 km): Kenilworth Avenue Northeast, heavy traffic (LTS 4).";
  const got = withoutHighStressLane(entry({ text_lanes_hidden: hidden }));
  assert.equal(got.text, hidden);
  assert.equal(got.facility, null);
  // Whatever the wording: the client does not edit it.
  const reworded = entry({ text: "x, heavy traffic (LTS 4), bike lane (paint).", text_lanes_hidden: "x, heavy traffic (LTS 4)." });
  assert.equal(withoutHighStressLane(reworded).text, "x, heavy traffic (LTS 4).");
});

test("a null text_lanes_hidden keeps the entry: an overview merge of an LTS 3 lane and an LTS 4 one is still a lane", () => {
  const merged = entry({ tier: 4, text: "x, heavy traffic (LTS 4), painted bike lane.", text_lanes_hidden: null });
  assert.equal(withoutHighStressLane(merged), merged);
  const routeWithField = {
    preset: "default",
    distance_m: 3000,
    description: [merged],
    description_overview: [merged],
  } as never;
  assert.match((descriptionEntries(routeWithField, "overview", false) ?? [])[0].text, /painted bike lane/);
});

test("only an older API, without the field, has the lane words taken out here", () => {
  const older = entry({});
  assert.ok(!("text_lanes_hidden" in older));
  assert.ok(!/bike lane/.test(withoutHighStressLane(older).text));
});

