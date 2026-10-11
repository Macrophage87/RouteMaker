import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { BUNDLED_FONTS, BUNDLED_ICONS, COMMITTED_NOTICES, completeLicences, fontTexts, iconTexts, inlinedPackages, licenceFile, packageOf, withFontNotices, withIconNotices } from "./notices.mjs";

const FRONTEND = new URL("../../", import.meta.url);

const VITE = `# Licenses

The app bundles dependencies which contain the following licenses:

## @protomaps/basemaps - 5.7.2 (BSD-3-Clause)

## fflate - 0.8.3 (MIT)

MIT License

Copyright (c) 2023 Arjun Barrett

## pmtiles - 4.5.0 (BSD-3-Clause)
`;

/** Each heading and the text under it, up to the next heading. */
function entries(text) {
  const out = {};
  let current = null;
  for (const line of text.split("\n")) {
    const heading = line.match(/^## (.+?) - /);
    if (heading) out[(current = heading[1])] = "";
    else if (current) out[current] += line + "\n";
  }
  return out;
}

test("an entry with no text is filled with the committed notice", () => {
  const fill = (name) => ({ pmtiles: "Copyright (c) P\n\nBSD text", "@protomaps/basemaps": "Copyright (c) B" })[name] ?? null;
  const done = entries(completeLicences(VITE, { fill }));
  assert.match(done.pmtiles, /Copyright \(c\) P[\s\S]*BSD text/);
  assert.match(done["@protomaps/basemaps"], /Copyright \(c\) B/);
  // An entry that had its text keeps it, unchanged and not doubled.
  assert.match(done.fflate, /Arjun Barrett/);
  assert.equal(done.fflate.match(/MIT License/g).length, 1);
});

test("the build fails, naming it, when a bundled package is left without text", () => {
  assert.throws(() => completeLicences(VITE, { fill: () => null }), /@protomaps\/basemaps, pmtiles/);
  assert.throws(() => completeLicences(VITE, { fill: (n) => (n === "pmtiles" ? "x" : "   ") }), /basemaps/);
  const fill = () => "text";
  assert.throws(
    () => completeLicences(VITE, { fill, inlined: [{ name: "earcut", version: "3", license: "ISC", text: "" }] }),
    /earcut/,
  );
  assert.throws(
    () => completeLicences(VITE, { fill, inlined: [{ name: "earcut", version: "3", license: "ISC", text: " \n " }] }),
    /earcut/,
  );
});

test("a line under an entry that only looks like a heading is text, not a new entry", () => {
  // Licence texts taken from READMEs carry their own "## License" lines.
  const text = "## murmurhash-js - 1.0.0 (MIT)\n\n## License (MIT)\n\nCopyright (c) 2011 Gary Court\n";
  assert.doesNotThrow(() => completeLicences(text, { fill: () => null }));
  assert.equal(completeLicences(text, { fill: () => "FILLED" }).includes("FILLED"), false);
});

test("packages inlined in another's bundle get headings and text of their own", () => {
  const inlined = [
    { name: "@maplibre/mlt", version: "1.3.0", license: "(MIT OR Apache-2.0)", text: "MIT License\n\nCopyright (c) 2024 MapLibre contributors" },
    { name: "fflate", version: "0.8.3", license: "MIT", text: "listed already" },
  ];
  const text = completeLicences(VITE, { fill: () => "text", inlined });
  const done = entries(text);
  assert.match(done["@maplibre/mlt"], /MapLibre contributors/);
  assert.match(text, /^## @maplibre\/mlt - 1\.3\.0 \(\(MIT OR Apache-2\.0\)\)$/m);
  // A package Vite already lists is not listed twice.
  assert.equal(text.match(/^## fflate /gm).length, 1);
  assert.doesNotMatch(text, /listed already/);
});

test("a source-map path names its package, scoped or not", () => {
  assert.equal(packageOf("../node_modules/@maplibre/mlt/dist/vector/vector.js"), "@maplibre/mlt");
  assert.equal(packageOf("../node_modules/earcut/src/earcut.js"), "earcut");
  assert.equal(packageOf("../node_modules/a/node_modules/pbf/index.js"), "pbf");
  assert.equal(packageOf("../src/style/style.ts"), null);
  assert.equal(packageOf("../node_modules/@scope"), null);
  assert.equal(packageOf("../node_modules/@scope/"), null);
  assert.equal(packageOf("../node_modules/"), null);
  assert.deepEqual(
    inlinedPackages(["../node_modules/pbf/a.js", "../src/x.ts", "../node_modules/pbf/b.js", "../node_modules/@m/mlt/c.js"]),
    ["@m/mlt", "pbf"],
  );
});

test("the committed notices exist and carry a copyright line and licence text", () => {
  for (const [name, rel] of Object.entries(COMMITTED_NOTICES)) {
    const file = new URL(rel, FRONTEND);
    assert.ok(existsSync(file), `${name}: ${rel} is missing`);
    const text = readFileSync(file, "utf8");
    assert.match(text, /^Copyright \(c\) /m, name);
    assert.ok(text.length > 800, `${name}'s notice is too short to be a licence`);
  }
  const bsd = readFileSync(new URL(COMMITTED_NOTICES.pmtiles, FRONTEND), "utf8");
  assert.match(bsd, /Redistributions in binary form must reproduce/);
});

test("the notices cover every package inlined in the maplibre-gl this lockfile installs", () => {
  // The premise of the second gap: the bundle maplibre-gl ships has other
  // packages in it, @maplibre/mlt among them, and each has text to ship.
  const dist = new URL("node_modules/maplibre-gl/dist/", FRONTEND);
  const sources = JSON.parse(readFileSync(new URL("maplibre-gl-shared.mjs.map", dist), "utf8")).sources;
  const names = inlinedPackages(sources);
  assert.ok(names.includes("@maplibre/mlt"), names.join(", "));
  assert.ok(names.length >= 10, names.join(", "));
  const without = names.filter(
    (name) => !licenceFile(new URL(`node_modules/${name}/`, FRONTEND).pathname) && !(name in COMMITTED_NOTICES),
  );
  assert.deepEqual(without, [], "inlined packages with neither a licence file nor a committed notice");
});

test("the self-hosted font's credit and the full SIL Open Font License are added under a heading of its own (384)", () => {
  assert.deepEqual(BUNDLED_FONTS.map((f) => f.name), ["Atkinson Hyperlegible"]);
  const fonts = BUNDLED_FONTS.map((f) => ({ ...f, text: readFileSync(new URL(f.file, FRONTEND), "utf8") }));
  const base = completeLicences(VITE, { fill: () => "text" });
  const text = withFontNotices(base, fonts);
  // Every earlier notice is still there, ahead of the font's, unchanged.
  assert.ok(text.startsWith(base.trimEnd()), "the package notices are kept in full");
  assert.ok(text.indexOf("## pmtiles") >= 0 && text.indexOf("## fflate") >= 0);
  assert.match(text, /^## Atkinson Hyperlegible - 2020 \(OFL-1\.1\)$/m);
  assert.match(text, /Copyright 2020 Braille Institute of America, Inc\./);
  assert.match(text, /SIL OPEN FONT LICENSE Version 1\.1 - 26 February 2007/);
  assert.match(text, /PERMISSION & CONDITIONS/);
  assert.match(text, /DISCLAIMER/);
  // The earlier entries are untouched and the font comes after them.
  assert.ok(text.indexOf("## pmtiles") < text.indexOf("## Atkinson Hyperlegible"));
  // A font with no text fails the build, as a package without text does.
  assert.throws(() => withFontNotices(VITE, [{ name: "Atkinson Hyperlegible", version: "2020", license: "OFL-1.1", text: " " }]), /Atkinson Hyperlegible/);
  assert.equal(withFontNotices(VITE, []), VITE);
});

test("fontTexts reads each licence file, and gives null for a missing one, which fails the build", () => {
  const real = fontTexts(fileURLToPath(FRONTEND));
  assert.equal(real.length, BUNDLED_FONTS.length);
  assert.match(real[0].text, /SIL OPEN FONT LICENSE Version 1\.1/);
  const empty = mkdtempSync(join(tmpdir(), "notices-"));
  mkdirSync(join(empty, "src/fonts"), { recursive: true });
  const missing = fontTexts(empty);
  assert.equal(missing[0].text, null);
  assert.throws(() => withFontNotices("x", missing), /no licence text for bundled font\(s\): Atkinson Hyperlegible/);
});

test("the font files are the ones the owner approved: sha256 and the wOF2 magic bytes", () => {
  const sha = {
    "atkinson-hyperlegible-regular.woff2": "d64ba838ef5472bba248620ec4fd8b5aa7cf0db2908e0bb230600caf279ba7bc",
    "atkinson-hyperlegible-bold.woff2": "140e2bd25a7315c8a062508391426b0d8c3297400c947b8d847be28f73a199f0",
    "OFL.txt": "f32d22b3908fcad2c86a74000614ec22e6a7f66ea7e867e616026a27aebdc143",
  };
  for (const [name, hash] of Object.entries(sha)) {
    const bytes = readFileSync(new URL(`src/fonts/${name}`, FRONTEND));
    assert.equal(createHash("sha256").update(bytes).digest("hex"), hash, name);
    if (name.endsWith(".woff2")) assert.equal(bytes.subarray(0, 4).toString("latin1"), "wOF2", name);
  }
});

test("the font files, the licence and the plugin's wiring are in place", () => {
  for (const name of ["atkinson-hyperlegible-regular.woff2", "atkinson-hyperlegible-bold.woff2", "OFL.txt"])
    assert.ok(existsSync(new URL(`src/fonts/${name}`, FRONTEND)), name);
  const plugin = readFileSync(new URL("src/licences/notices.mjs", FRONTEND), "utf8");
  assert.match(plugin, /const fonts = fontTexts\(root\);/);
  assert.match(plugin, /withFontNotices\(completeLicences\(readFileSync\(file, "utf8"\), \{ fill: committed, inlined \}\), fonts\)/);
});

test("the Avoid junction icon's Apache 2.0 notice and full licence are added under a heading of their own (310)", () => {
  assert.deepEqual(BUNDLED_ICONS.map((i) => i.license), ["Apache-2.0"]);
  const icons = iconTexts(fileURLToPath(FRONTEND));
  assert.equal(icons.length, 1);
  const text = withIconNotices(withFontNotices(VITE, []), icons);
  assert.ok(text.startsWith(VITE.replace(/\s+$/, "")));
  assert.match(text, /^## Noto Emoji skull and crossbones \(U\+2620\) - e20cbc2bbec1926686be9f9bee7d1d2cfa1fea0e \(Apache-2\.0\)$/m);
  assert.match(text, /Copyright 2013 Google, Inc\. All Rights Reserved\./);
  assert.match(text, /2D\/svg\/emoji_u2620\.svg/);
  assert.match(text, /TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION/);
  // An icon with no text fails the build.
  assert.throws(() => withIconNotices(VITE, [{ ...BUNDLED_ICONS[0], text: null }]), /no licence text for bundled icon/);
  assert.equal(withIconNotices(VITE, []), VITE);
  const plugin = readFileSync(new URL("src/licences/notices.mjs", FRONTEND), "utf8");
  assert.match(plugin, /withIconNotices\(withFontNotices\(/);
});
