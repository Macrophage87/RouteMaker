// Settings' maps for no signal, the popout, as the rider sees it (rendered, not read as source).
import { test } from "node:test";
import assert from "node:assert/strict";
import { render } from "./testSupport/render.ts";
import { RegionPackDialog } from "./RegionPackSetting.tsx";
import type { KeptPack, PackList } from "./lib/regionPack.ts";

const MB = 1024 * 1024;
const square = (w: number, s: number, e: number, n: number): [number, number][] => [[w, s], [e, s], [e, n], [w, n], [w, s]];
const LIST: PackList = {
  buildId: "20261115T125405Z",
  levelFactor: [1],
  box: [-78.05, 38.2, -76.02, 39.72],
  packs: [
    { id: "beltway", name: "Inside the Beltway", bytes: 10.8 * MB, sha256: "a", url: "/offline-packs/x/beltway.json.gz", area: { outline: square(-77.2, 38.8, -76.9, 39), outsideBeltway: false, whole: false } },
    { id: "nova", name: "Northern Virginia", bytes: 20.4 * MB, sha256: "b", url: "/offline-packs/x/nova.json.gz", area: { outline: square(-78, 38.3, -77.1, 39.3), outsideBeltway: true, whole: false } },
    { id: "rest", name: "Southern Maryland", bytes: 9 * MB, sha256: "c", url: "/offline-packs/x/rest.json.gz", area: { outline: null, outsideBeltway: false, whole: false } },
    { id: "all", name: "Everything", bytes: 69.2 * MB, sha256: "d", url: "/offline-packs/x/all.json.gz", area: { outline: null, outsideBeltway: false, whole: true } },
  ],
};
const kept = (id: string, bytes: number): KeptPack => ({ id, name: id, buildId: LIST.buildId, bytes, sha256: "a", levelFactor: [1], key: id });

const popout = (list: PackList | null, onPhone: KeptPack[]) =>
  render(<RegionPackDialog open list={list} kept={onPhone} onClose={() => undefined} onKept={() => undefined} />);

test("nothing kept: says so, shows the map and each area with its size and Download, and Download all as one file", async () => {
  const screen = await popout(LIST, []);
  const text = screen.text();
  assert.match(text, /None on this phone/);
  assert.ok(screen.get("img", "Map of the areas"));
  assert.ok(screen.button("Download Inside the Beltway"));
  assert.ok(screen.button("Download Southern Maryland"));
  assert.match(text, /20 MB/);
  assert.ok(screen.button("Download all (69 MB)"));
  assert.equal(screen.all("button", "Delete all").length, 0, "nothing to delete");
  assert.equal(screen.all("button", /Everything/).length, 0, "the whole map is Download all, not a row");
});

test("two areas kept: what is on the phone, the map's date, Delete for each and Delete all", async () => {
  const screen = await popout(LIST, [kept("beltway", 10.8 * MB), kept("nova", 20.4 * MB)]);
  const text = screen.text();
  assert.match(text, /On this phone: 31 MB/);
  assert.match(text, /Map of Nov 15, 2026/);
  assert.ok(screen.button("Delete Inside the Beltway"));
  assert.ok(screen.button("Delete Northern Virginia"));
  assert.ok(screen.button("Download Southern Maryland"));
  assert.ok(screen.button("Delete all"));
});

test("the whole map kept: every area is part of it, with Delete all only", async () => {
  const screen = await popout(LIST, [kept("all", 69.2 * MB)]);
  assert.equal(screen.text().split("Part of the whole map").length - 1, 3);
  assert.equal(screen.all("button", /^Download/).length, 0);
  assert.equal(screen.all("button", /^Delete (?!all$)/).length, 0, "no area's own Delete");
  assert.ok(screen.button("Delete all"));
});

test("no signal: the kept areas are still shown and can be deleted", async () => {
  const screen = await popout(null, [kept("beltway", 10.8 * MB)]);
  assert.match(screen.text(), /Needs a signal to list the maps/);
  assert.ok(screen.button("Delete Inside the Beltway"));
  assert.equal(screen.all("button", /^Download/).length, 0);
});
