// Stop icons and the icons' two styles (Stephen 2026-11-10: "Stops can have icons too", "Allow both", "We can use
// noto"): the link's `si`, the icon kept on its stop through an edit, the Noto pictures as bundled, and the choice.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import type { LonLat } from "./geo.ts";
import { ViaMarks, decodeStopIcons, encodeStopIcons, stopIcons } from "./pointKinds.ts";
import { decodePlan, encodePlan } from "./planHash.ts";
import { NOTE_ICONS } from "./routeNotes.ts";
import { readIconStyle, writeIconStyle } from "./iconStyle.ts";

const NOTO_SHA256: Record<string, string> = {
  "noto-emoji-u1f374.svg": "20aad3b1d514df37e7e9a94a16d681db11f1e3aa79024e031e1b8b69c666f115",
  "noto-emoji-u1f3de.svg": "089a1527f476a23ecba055b59edbe4d0225c06d1c53dcc1fb6967006f3459c75",
  "noto-emoji-u1f4a7.svg": "d4751fed323d453bc85a3366c01f1a0bf0f5ca5260bf48e6eb4b150c2af86dfa",
  "noto-emoji-u1f4cd.svg": "c410eebb03aa1ac88d10563ca204f118e79303f6d4c7294945e1165766679fbf",
  "noto-emoji-u1f4f7.svg": "7e0572c943b5a8d2b1e11ecebda3521f40dd37ae10578a9d9d59a8e5945a6895",
  "noto-emoji-u1f527.svg": "585050ccfcdaa032b836e008b71995086b4f734352cf6ab933d173e8add83976",
  "noto-emoji-u1f573.svg": "0b8176881c391b9586f34934f45d95db9b0328d07047b111dd1619a6fc8e2f58",
  "noto-emoji-u1f697.svg": "0ed788aa0d922d69a031b7ece7e862e254b9cd07e3c7e6974e0f5ac5694cb549",
  "noto-emoji-u1f6a7.svg": "cde40e90038b77fdeeefae35deb5c0f002e57d02619a4b2f9d0398da39a74103",
  "noto-emoji-u1f6bb.svg": "7c1684ce488d8cc18946f651a313fcbd5203387ffaac48c57e44fc95ad07b244",
  "noto-emoji-u2615.svg": "5830ae818458ee3c51208af6196a8a6c3d2a27e652aed2380c0b26a39d13d9dc",
  "noto-emoji-u26a0.svg": "040e0a04356c12994f61a7011f47c7f278394f039feb01b5f3b2f82be3c7cc1f",
};

test("a stop's icon travels in the link as si=index:icon; a via point or an unknown icon has none", () => {
  const marks = new ViaMarks();
  const points: LonLat[] = [[-77.03, 38.9], marks.named([-77.02, 38.91], "Cafe"), marks.via([-77.01, 38.92]), [-77.0, 38.93]];
  marks.setIcon(points[1], "coffee");
  marks.setIcon(points[2], "pin");
  const icons = stopIcons(points, marks.iconOf, marks.isVia);
  assert.deepEqual([...icons], [[1, "coffee"]]);
  assert.deepEqual(encodeStopIcons(icons), ["1:coffee"]);
  const hash = encodePlan(points, "default", undefined, [2], [], new Map([[1, "Cafe"]]), "q", [], icons);
  assert.match(hash, /&si=1%3Acoffee/);
  assert.deepEqual([...decodePlan(hash).icons], [[1, "coffee"]]);
  // An older link has none; a newer icon, the start or an index past the end is left out.
  assert.equal(decodePlan(encodePlan(points, "default", undefined, [2], [], new Map(), "q", [], new Map())).icons.size, 0);
  assert.deepEqual([...decodeStopIcons(["1:nosuchicon", "0:coffee", "9:coffee", "2:water"], 4)], [[2, "water"]]);
});

test("a stop keeps its icon through a switch of kind and back, and a rename leaves it", () => {
  const marks = new ViaMarks();
  const stop = marks.named([-77.02, 38.91], "Cafe");
  marks.setIcon(stop, "coffee");
  const asVia = marks.withKind(stop, "via");
  const back = marks.withKind(asVia, "stop");
  assert.equal(marks.iconOf(back), "coffee");
  marks.rename(back, "Other cafe");
  assert.equal(marks.iconOf(back), "coffee");
  marks.setIcon(back, undefined);
  assert.equal(marks.iconOf(back), undefined);
});

test("every icon has its Noto picture, bundled exactly as downloaded, with no script or outside reference", () => {
  const codes = Object.values(NOTE_ICONS).map((emoji) => (emoji.codePointAt(0) as number).toString(16));
  const files = codes.map((code) => `noto-emoji-u${code}.svg`);
  assert.deepEqual([...files].sort(), Object.keys(NOTO_SHA256).sort());
  const art = readFileSync(new URL("../app/iconArt.tsx", import.meta.url), "utf8");
  for (const file of files) {
    const bytes = readFileSync(new URL(`../icons/${file}`, import.meta.url));
    assert.equal(createHash("sha256").update(bytes).digest("hex"), NOTO_SHA256[file], file);
    const text = bytes.toString("utf8");
    assert.ok(!/<script|\son[a-z]+=|href="(?!#)/i.test(text), file);
    assert.ok(art.includes(`../icons/${file}?url`), `iconArt.tsx bundles ${file}`);
  }
});

test("the icons are Noto pictures unless the phone's emoji is chosen, kept on this device", () => {
  const kept = new Map<string, string>();
  const store = { getItem: (k: string) => kept.get(k) ?? null, setItem: (k: string, v: string) => void kept.set(k, v), removeItem: (k: string) => void kept.delete(k) };
  assert.equal(readIconStyle(store), "noto");
  writeIconStyle("emoji", store);
  assert.equal(readIconStyle(store), "emoji");
  writeIconStyle("noto", store);
  assert.equal(readIconStyle(store), "noto");
});
