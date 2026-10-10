// OWNER-DECISIONS 301 ("sources need citing") and 306 ("keep it brief and put the full
// information in documentation. Sort of like how you'd cite in a paragraph."): every source
// a rider sees the work of is cited on the map by a short name, from credits.json, whose
// texts tests/test_credits.py holds to docs/SOURCES.md's full references; and the
// comparison data used only inside the project is named nowhere a rider sees.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { BASEMAP } from "../stressStyle.js";
import { CREDITS, MAP_ATTRIBUTION, MAP_CREDITS, buildStyle } from "./mapStyle.ts";

const DATA = JSON.parse(readFileSync(new URL("./credits.json", import.meta.url), "utf8")) as Array<{ text: string; html: string }>;
const strip = (html: string) => html.replace(/<[^>]+>/g, "");

test("the credits are short source names, exactly these, OpenStreetMap first (OWNER-DECISIONS 306)", () => {
  assert.deepEqual(
    DATA.map((c) => c.text),
    [
      "© OpenStreetMap contributors (ODbL)",
      "Protomaps",
      "DC Open Data (CC BY 4.0, adapted)",
      "VDOT",
      "Open Baltimore",
      "Montgomery County Planning Department",
      "USGS 3DEP",
      "U.S. Census Bureau",
      "Photon",
      "Capital Bikeshare",
    ],
  );
  for (const credit of DATA) {
    assert.equal(strip(credit.html), credit.text, "the text is the html without its links");
    assert.ok(credit.text.length <= 40, `brief: ${credit.text}`);
  }
  // Links only where they are the citation's own: OpenStreetMap's copyright page and the CC BY licence.
  const links = DATA.flatMap((c) => [...c.html.matchAll(/href="([^"]+)"/g)].map((m) => m[1]));
  assert.deepEqual(links, ["https://www.openstreetmap.org/copyright", "https://creativecommons.org/licenses/by/4.0/"]);
});

test("the map's attribution is credits.json, in its order, then the software licences", () => {
  assert.deepEqual(CREDITS, DATA);
  assert.deepEqual(MAP_CREDITS, DATA.map((c) => c.html));
  assert.equal(MAP_ATTRIBUTION, [...DATA.map((c) => c.html), '<a href="/licenses.txt">Software licences</a>'].join(" | "));
  // The base map source's own credit is folded into the one entry (MapLibre drops a part of a longer one).
  assert.ok(MAP_ATTRIBUTION.startsWith(BASEMAP.attribution), BASEMAP.attribution);
  assert.equal((buildStyle("https://x.example", []).sources.protomaps as { attribution: string }).attribution, BASEMAP.attribution);
  assert.doesNotMatch(MAP_ATTRIBUTION, /Stress tiers use|Street speeds|Roadway Block|komoot/, "no long descriptions: those are docs/SOURCES.md's");
});

test("Arlington's and Alexandria's comparison data, internal only, is named nowhere a rider sees", async () => {
  const { readdirSync, readFileSync, statSync } = await import("node:fs");
  const { join } = await import("node:path");
  const root = new URL("..", import.meta.url).pathname;
  const offenders: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) {
        walk(path);
        continue;
      }
      // The code and the page, where a credit would be written; the data files hold place names (a station called Arlington Cemetery).
      if (/\.test\./.test(name) || !/\.(ts|tsx|js|mjs|css|html)$/.test(name)) continue;
      if (/Arlington|Alexandria/i.test(readFileSync(path, "utf8"))) offenders.push(path);
    }
  };
  walk(root);
  assert.deepEqual(offenders, []);
  assert.doesNotMatch(MAP_ATTRIBUTION, /Arlington|Alexandria/i);
});
