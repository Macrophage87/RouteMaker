import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  DESCRIPTION_HEADING,
  chevron,
  cueSheetFileName,
  descriptionEntries,
  descriptionText,
  readOpen,
  saysItsSeverity,
  stepCount,
  toggleLabel,
  writeOpen,
} from "./routeDescription.ts";
import type { DescriptionEntry } from "./api.ts";

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

const route = {
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
  assert.match(component, /Copy description/);
});

test("nothing is announced on a route change: no live region but the copy reply", () => {
  assert.doesNotMatch(component, /aria-live/);
  assert.doesNotMatch(component, /role="alert"/);
  assert.equal((component.match(/role="status"/g) ?? []).length, 1);
});

test("App places it in the route summary and the component stays separate", () => {
  assert.match(app, /<RouteDescription route=\{route\} \/>/);
});
