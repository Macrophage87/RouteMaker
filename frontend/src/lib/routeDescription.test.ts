import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  DESCRIPTION_HEADING,
  chevron,
  cueSheetFileName,
  descriptionEntries,
  GPX_FULL_MAX_CHARS,
  descriptionText,
  gpxDescriptionText,
  hasOverview,
  readOpen,
  readView,
  viewFor,
  writeView,
  saysItsSeverity,
  stepCount,
  toggleLabel,
  toggleName,
  crossingsOf,
  entryLines,
  writeOpen,
} from "./routeDescription.ts";
import type { DescriptionEntry, RouteResponse } from "./api.ts";
import { planPointName, writeGpx } from "./gpx.ts";
import { exportOf } from "./gpxText.ts";
import { pointName } from "./summary.ts";

// OWNER-DECISIONS 220: the route in words for blind stokers: a heading, an
// ordered list of single sentences, copy and download, nothing announced.

function entry(text: string, extra: Partial<DescriptionEntry> = {}): DescriptionEntry {
  return {
    kind: "stretch",
    from_m: 0,
    to_m: 1931,
    from_mi: 0,
    to_mi: 1.2,
    street: "Capital Crescent Trail",
    tier: 1,
    facility: "path",
    turn: null,
    text,
    ...extra,
  };
}

const route: Pick<RouteResponse, "preset" | "distance_m" | "description"> &
  Partial<Pick<RouteResponse, "description_overview">> = {
  preset: "default" as const,
  distance_m: 3811,
  description: [
    entry("0.0 to 1.2 mi (0.0 to 1.9 km): Capital Crescent Trail, traffic-free path."),
    entry("1.2 to 1.5 mi (1.9 to 2.4 km): Left onto Bethesda Avenue at a signal (Higher stress junction), busy road (LTS 3).", {
      severity: "orange",
    }),
  ],
};

test("the entries are the API's, in order; none from an older API or an empty list", () => {
  assert.equal(descriptionEntries(route)?.length, 2);
  assert.equal(descriptionEntries({ description: undefined }), null);
  assert.equal(descriptionEntries({ description: null }), null);
  assert.equal(descriptionEntries({ description: [] }), null);
});

test("an entry with no sentence is not listed", () => {
  const listed = descriptionEntries({ description: [entry("  "), entry("A sentence.")] });
  assert.deepEqual(listed?.map((e) => e.text), ["A sentence."]);
});

test("the heading is the one a screen reader jumps to", () => {
  assert.equal(DESCRIPTION_HEADING, "Route description");
});

test("the step count is words, singular for one", () => {
  assert.equal(stepCount([entry("a")]), "1 step");
  assert.equal(stepCount([entry("a"), entry("b")]), "2 steps");
  const two = [entry("a"), entry("b")];
  assert.equal(toggleLabel(two), "2 steps");
});

test("the toggle's label does not change with its state, and its chevron is a shape", () => {
  assert.notEqual(chevron(true), chevron(false));
  assert.equal(toggleLabel([entry("a")]), toggleLabel([entry("a")]));
});

test("the copied text is a heading line and one numbered line per entry, US units first", () => {
  assert.equal(
    descriptionText(route),
    "RouteMaker Default route, 2.4 mi (3.8 km).\n" +
      "1. 0.0 to 1.2 mi (0.0 to 1.9 km): Capital Crescent Trail, traffic-free path.\n" +
      "2. 1.2 to 1.5 mi (1.9 to 2.4 km): Left onto Bethesda Avenue at a signal (Higher stress junction), busy road (LTS 3).\n",
  );
});

test("the text has just the heading line where there is nothing to list", () => {
  assert.equal(descriptionText({ preset: "default", distance_m: 1609.344, description: null }), "RouteMaker Default route, 1.0 mi (1.6 km).\n");
});

test("the file name is beside the GPX file's, and says what it is", () => {
  assert.equal(cueSheetFileName(route), "routemaker-default-2_4-miles-description.txt");
});

test("a flagged junction says its severity in words, not only in a colour", () => {
  assert.equal(saysItsSeverity(route.description[1]), true);
  assert.equal(saysItsSeverity(entry("Left onto B.", { severity: "red" })), false);
  assert.equal(saysItsSeverity(entry("Left onto B.")), true);
});

test("the open state is remembered, closed by default and where storage fails", () => {
  const store = new Map<string, string>();
  const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) };
  assert.equal(readOpen(storage), false);
  writeOpen(true, storage);
  assert.equal(readOpen(storage), true);
  writeOpen(false, storage);
  assert.equal(readOpen(storage), false);
  const broken = {
    getItem: () => {
      throw new Error("blocked");
    },
    setItem: () => {
      throw new Error("blocked");
    },
  };
  assert.equal(readOpen(broken), false);
  assert.doesNotThrow(() => writeOpen(true, broken));
  assert.equal(readOpen(null), false);
});

// The component is placed by App and keeps to the accessible pattern. Read as
// source, as the other panels' structure is (no DOM here).
const component = readFileSync(new URL("../RouteDescription.tsx", import.meta.url), "utf8");
const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");

test("the section is a labelled heading, a disclosure button and an ordered list", () => {
  assert.match(component, /<h3 id="route-description-heading">/);
  assert.match(component, /aria-labelledby="route-description-heading"/);
  assert.match(component, /aria-expanded=\{open\}/);
  assert.match(component, /aria-controls=\{listId\}/);
  assert.match(component, /<ol id=\{listId\}[^>]*hidden=\{!open\}/);
  assert.match(component, /onClick=\{onCopy\}>\s*Copy description/);
  assert.match(component, /onClick=\{onDownload\}>\s*Download as text/);
});

test("nothing is announced on a route change: no live region but the copy reply", () => {
  assert.doesNotMatch(component, /aria-live/);
  assert.doesNotMatch(component, /role="alert"/);
  assert.equal((component.match(/role="status"/g) ?? []).length, 1);
});

test("App places it in the route summary and the component stays separate", () => {
  // In the sidebar redesign (312) it is the "Directions" fold of the route summary: `fold`.
  // A Mass Ride's federal-land lines (item 239) are handed in from the App, which has the overlay's data.
  assert.match(app, /<RouteDescription route=\{route\} fold rideAction=\{rideAction\} federal=\{federal\} \/>/);
});

// --- OWNER-DECISIONS 224: stops are "Stop N" everywhere ---

test("stops are Stop N in the points list, the announcements, the map and the GPX", () => {
  assert.equal(pointName(1, 4), "Stop 1");
  assert.equal(pointName(2, 4), "Stop 2");
  assert.equal(pointName(0, 4), "Start");
  assert.equal(pointName(3, 4), "End");
  assert.equal(planPointName(1, 3), "Stop 1");
  assert.equal(planPointName(2, 4), "Stop 2");
  const files = ["../App.tsx", "../MapView.tsx", "./summary.ts", "./gpx.ts", "./gpxText.ts", "./pointsList.ts", "./pointText.ts", "../FacilityBreakdown.tsx", "../railInteraction.ts"];
  for (const file of files) {
    // What a rider can read: not the comments.
    const source = readFileSync(new URL(file, import.meta.url), "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
    assert.doesNotMatch(source, /`Via |"Via |Via point|via point|Add as via/, file);
  }
  const map = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  assert.match(map, /import \{ pointLabel \} from "\.\/lib\/pointText\.ts";/);
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /announce\(insertedSaid\(leg, next\.length, loopVias\)\)/);
});

test("the GPX writer names a route's points Start, Stop N and End", () => {
  const points: [number, number][] = [[-77, 38.9], [-77.01, 38.91], [-77.02, 38.92], [-77.03, 38.93]];
  const gpx = writeGpx({ name: "n", description: "d", attribution: [], preset: "default", planPoints: points, geometry: points });
  assert.deepEqual([...gpx.matchAll(/<rtept [^>]*>\s*<name>([^<]*)<\/name>/g)].map((m) => m[1]), ["Start", "Stop 1", "Stop 2", "End"]);
  assert.doesNotMatch(gpx, /Via/);
});

// --- OWNER-DECISIONS 225 and 226: the overview, and the description in the GPX ---

const withOverview = { ...route, description_overview: [route.description[0]] };
const lineOf = (extra: object) => ({
  preset: "default" as const,
  distance_m: 500,
  climb_m: 1,
  descent_m: 1,
  geometry: { type: "LineString" as const, coordinates: [[-77, 38.9], [-77.01, 38.91]] as [number, number][] },
  attribution: [],
  ...extra,
});
const ENDS: [number, number][] = [[-77, 38.9], [-77.01, 38.91]];

test("the default view is the overview; full detail lists every entry", () => {
  assert.equal(descriptionEntries(withOverview)?.length, 1);
  assert.equal(descriptionEntries(withOverview, "overview")?.length, 1);
  assert.equal(descriptionEntries(withOverview, "full")?.length, 2);
});

test("an answer without an overview lists the full description in either view", () => {
  assert.equal(descriptionEntries(route, "overview")?.length, 2);
  assert.equal(hasOverview(route), false);
  assert.equal(viewFor(route, "overview"), "full");
  assert.equal(hasOverview({ ...route, description_overview: null }), false);
  assert.equal(hasOverview({ ...route, description_overview: route.description }), false);
});

test("the choice is offered only where the overview is shorter", () => {
  assert.equal(hasOverview(withOverview), true);
  assert.equal(viewFor(withOverview, "overview"), "overview");
  assert.equal(viewFor(withOverview, "full"), "full");
});

test("the toggle's label names the view where there is a choice, and the count of steps shown", () => {
  const entries = descriptionEntries(withOverview, "overview")!;
  assert.equal(toggleLabel(entries, "overview", true), "1 step, overview");
  assert.equal(toggleLabel(descriptionEntries(withOverview, "full")!, "full", true), "2 steps, full detail");
  assert.equal(toggleLabel(descriptionEntries(route)!), "2 steps");
});

test("copy and download text follow the view shown, and say which it is", () => {
  const overview = descriptionText(withOverview, "overview");
  const full = descriptionText(withOverview, "full");
  assert.match(overview, /^RouteMaker Default route, 2\.4 mi \(3\.8 km\)\. Overview, short stretches merged\.\n1\. 0\.0 to 1\.2 mi/);
  assert.equal(overview.split("\n").length, 3);
  assert.match(full, /Full detail\.\n1\. .*\n2\. /);
  assert.equal(full.split("\n").length, 4);
  // No choice, no view named.
  assert.doesNotMatch(descriptionText(route, "full"), /Overview|Full detail/);
});

test("the chosen view is remembered, the overview by default and where storage fails", () => {
  const store = new Map<string, string>();
  const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) };
  assert.equal(readView(storage), "overview");
  writeView("full", storage);
  assert.equal(readView(storage), "full");
  writeView("overview", storage);
  assert.equal(readView(storage), "overview");
  store.set("routemaker.description.view", "nonsense");
  assert.equal(readView(storage), "overview");
  const broken = {
    getItem: () => {
      throw new Error("blocked");
    },
    setItem: () => {
      throw new Error("blocked");
    },
  };
  assert.equal(readView(broken), "overview");
  assert.doesNotThrow(() => writeView("full", broken));
  assert.equal(readView(null), "overview");
});

test("the component offers Full detail as a checkbox, only where there is a choice, and its copy and download use the view", () => {
  assert.match(component, /type="checkbox" checked=\{view === "full"\}/);
  assert.match(component, /\{choice \? \(/);
  assert.equal((component.match(/descriptionText\(route, view, federal\)/g) ?? []).length, 2);
  assert.match(component, /writeView\(next\)/);
  assert.match(component, /useState<DescriptionView>\(\(\) => readView\(\)\)/);
});

test("the GPX description is the full text where it is short, with a label saying so", () => {
  assert.equal(
    gpxDescriptionText(withOverview),
    "Route description, full detail:\n" +
      "1. 0.0 to 1.2 mi (0.0 to 1.9 km): Capital Crescent Trail, traffic-free path.\n" +
      "2. 1.2 to 1.5 mi (1.9 to 2.4 km): Left onto Bethesda Avenue at a signal (Higher stress junction), busy road (LTS 3).",
  );
  assert.equal(gpxDescriptionText({ description: null }), "");
  assert.match(gpxDescriptionText(route), /^Route description:\n1\. /);
});

test("the GPX description is the overview where the full text is long", () => {
  const long = Array.from({ length: 60 }, (_, i) => entry(`${i}.0 to ${i}.2 mi: Street ${i}, low stress (LTS 1). ${"x".repeat(60)}`));
  const text = gpxDescriptionText({ description: long, description_overview: long.slice(0, 5) });
  assert.match(text, /^Route description, overview:\n1\. 0\.0 to 0\.2 mi/);
  assert.equal(text.split("\n").length, 6);
  // Just under the limit stays full.
  assert.equal(GPX_FULL_MAX_CHARS, 4000);
  const fits = Array.from({ length: 3 }, () => entry("y".repeat(1300)));
  assert.match(gpxDescriptionText({ description: fits, description_overview: fits.slice(0, 1) }), /^Route description, full detail:/);
  // A little over it is the overview.
  const over = Array.from({ length: 3 }, () => entry("y".repeat(1340)));
  assert.match(gpxDescriptionText({ description: over, description_overview: over.slice(0, 1) }), /^Route description, overview:/);
});

test("the export puts the description in the route's desc after the ride type, one entry to a line", () => {
  const out = exportOf(lineOf(withOverview), ENDS);
  assert.equal(out.routeText, gpxDescriptionText(withOverview));
  const gpx = writeGpx(out);
  const rte = gpx.slice(gpx.indexOf("<rte>"), gpx.indexOf("</rte>"));
  const desc = /<desc>([\s\S]*?)<\/desc>/.exec(rte)![1];
  assert.match(desc, /^Ride type: Default\.\n\nRoute description, full detail:\n1\. 0\.0 to 1\.2 mi/);
  assert.equal(desc.split("\n").filter((line) => /^\d+\. /.test(line)).length, 2);
  // Not in the track's one-line description.
  assert.doesNotMatch(gpx.slice(gpx.indexOf("<trk>")), /Route description/);
});

test("the description is escaped for XML in the file", () => {
  const nasty = [entry("0.0 to 0.3 mi: Left onto Smith & Sons <Lane> \"Q\" 'x', low stress (LTS 1)."), entry("ctl\u0001char and é accents.")];
  const gpx = writeGpx(exportOf(lineOf({ description: nasty }), ENDS));
  assert.match(gpx, /Smith &amp; Sons &lt;Lane&gt; &quot;Q&quot; 'x'/);
  assert.doesNotMatch(gpx, /Smith & Sons|<Lane>|\u0001/);
  assert.match(gpx, /ctlchar and é accents/);
  // Still the elements it had, no more.
  assert.equal((gpx.match(/<rte>/g) ?? []).length, 1);
  assert.equal((gpx.match(/<\/desc>/g) ?? []).length, 3);
});

test("no description, none in the file: the route's desc is the ride type alone", () => {
  const out = exportOf(lineOf({}), ENDS);
  assert.equal(out.routeText, undefined);
  assert.doesNotMatch(writeGpx(out), /Route description/);
});

// --- The final-fix round: the a11y and spec re-checks of 2b0cf00, OWNER-DECISIONS 248 ---

const css = readFileSync(new URL("../routeDescription.css", import.meta.url), "utf8");
const block = (selector: string) => {
  const at = css.indexOf(`${selector} {`);
  assert.ok(at >= 0, selector);
  return css.slice(at, css.indexOf("}", at));
};

test("the toggle's name says what it opens, its visible words after", () => {
  const entries = descriptionEntries(withOverview, "overview")!;
  assert.equal(toggleName(entries, "overview", true), "Route description: 1 step, overview");
  assert.equal(toggleName(descriptionEntries(route)!), "Route description: 2 steps");
  assert.ok(toggleName(entries, "overview", true).endsWith(toggleLabel(entries, "overview", true)));
  assert.match(component, /aria-label=\{toggleName\(entries, view, choice\)\}/);
});

test("the list has no scroll box of its own: the panel scrolls, by keyboard in every browser", () => {
  assert.doesNotMatch(block(".description-list"), /max-height|overflow/);
  assert.doesNotMatch(component, /tabIndex/);
});

test("Full detail: no leading space in its name, and a 24 px target", () => {
  assert.doesNotMatch(component, /\/> Full detail/);
  assert.match(component, /\/>\s*\n\s*Full detail/);
  assert.match(block(".description-view"), /min-height:\s*24px/);
});

test("Copy's reply is cleared and set again, so a second press is said", () => {
  assert.match(component, /setCopied\(""\);\s*\n\s*const done = await copy/);
  assert.match(component, /window\.setTimeout\(\(\) => \{\s*\n\s*if \(press === presses\.current\)/);
});

const crossing = (m: number, street: string, text: string) => ({ from_m: m, from_mi: m / 1609.344, street, severity: "orange" as const, crossed_tier: 3, text });
const grouped = (withCrossings: boolean): DescriptionEntry =>
  entry("1.0 to 1.2 mi (1.6 to 1.9 km): 2 crossings with traffic signals (A Street and B Street) (Higher stress junctions).", {
    kind: "junction",
    severity: "orange",
    group: {
      number: 1,
      count: 2,
      lts4: 0,
      streets: ["A Street", "B Street"],
      more: 0,
      crossings: withCrossings
        ? [
            crossing(1609, "A Street", "At 1.0 mi (1.6 km): Cross A Street (LTS 3) at a signal (Higher stress junction)."),
            crossing(1931, "B Street", "At 1.2 mi (1.9 km): Cross B Street (LTS 3) at a signal (Higher stress junction)."),
          ]
        : null,
    },
  });
const massRoute = {
  preset: "mass-ride" as const,
  distance_m: 3811,
  description: [route.description![0], grouped(true), route.description![1]],
  description_overview: [grouped(false), route.description![1]],
};

test("a group's crossings are its sub-entries in full detail, none in the overview (OWNER-DECISIONS 248)", () => {
  assert.equal(crossingsOf(grouped(true)).length, 2);
  assert.deepEqual(crossingsOf(grouped(false)), []);
  assert.deepEqual(crossingsOf(route.description![0]), []);
  // An older API's group has no crossings at all.
  assert.deepEqual(crossingsOf({ ...grouped(true), group: { number: 1, count: 2, lts4: 0, streets: [], more: 0 } }), []);
});

test("the text and the GPX list a group's crossings under it, numbered within it", () => {
  assert.deepEqual(entryLines(massRoute.description), [
    `1. ${route.description![0].text}`,
    `2. ${grouped(true).text}`,
    "   2.1. At 1.0 mi (1.6 km): Cross A Street (LTS 3) at a signal (Higher stress junction).",
    "   2.2. At 1.2 mi (1.9 km): Cross B Street (LTS 3) at a signal (Higher stress junction).",
    `3. ${route.description![1].text}`,
  ]);
  const full = descriptionText(massRoute, "full");
  assert.match(full, /\n2\. 1\.0 to 1\.2 mi .*\n   2\.1\. At 1\.0 mi .*A Street.*\n   2\.2\. At 1\.2 mi .*B Street/);
  const overview = descriptionText(massRoute, "overview");
  assert.doesNotMatch(overview, /Cross A Street/);
  assert.match(gpxDescriptionText(massRoute), /^Route description, full detail:\n1\. [^\n]*\n2\. [^\n]*\n   2\.1\. At 1\.0 mi/);
});

test("in the page a group's crossings are a nested, named ordered list", () => {
  assert.match(component, /<ol className="description-crossings" aria-label="Crossings in this group, in route order">/);
  assert.match(component, /crossingsOf\(entry\)/);
});
