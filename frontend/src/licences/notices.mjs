/**
 * Completing the licence notices the build ships at /licenses.txt.
 *
 * Vite's build.license writes one heading per bundled package with the text
 * of that package's LICENSE file under it. That leaves two gaps:
 *
 * - A package whose npm tarball has no LICENSE file gets a heading and no
 *   text. pmtiles and @protomaps/basemaps are both BSD-3-Clause, whose second
 *   clause asks for the notice and the licence to travel with a binary
 *   (minified) copy, and neither ships one. Their text is committed under
 *   frontend/notices/: the standard BSD-3-Clause text, with the holder the
 *   package's own "author" field names, since the upstream repositories'
 *   LICENSE files were not fetched (recorded as an owner item: check the
 *   holder and year against github.com/protomaps/PMTiles and
 *   github.com/protomaps/basemaps before the site is public).
 * - maplibre-gl ships a prebuilt bundle with about seventeen packages inlined
 *   (@maplibre/mlt, earcut, pbf, ...), which Vite sees as maplibre-gl alone.
 *   maplibre-gl's own LICENSE.txt does not cover them. Which packages are in
 *   it is read from the source maps maplibre-gl ships beside its bundle, and
 *   each one's LICENSE file is added under a heading of its own.
 *
 * - The self-hosted font (Atkinson Hyperlegible, OWNER-DECISIONS 384) is a file, not a
 *   package, so build.license never lists it. Its credit and the full SIL Open Font
 *   License text (frontend/src/fonts/OFL.txt) are appended under their own heading.
 *
 * A bundled package left without licence text fails the build.
 */
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

/** Committed texts for packages that ship none, relative to frontend/. */
export const COMMITTED_NOTICES = {
  pmtiles: "notices/pmtiles.txt",
  "@protomaps/basemaps": "notices/protomaps-basemaps.txt",
  "murmurhash-js": "notices/murmurhash-js.txt",
};

/** The package a source-map path under node_modules belongs to, or null. */
export function packageOf(sourcePath) {
  const at = sourcePath.lastIndexOf("node_modules/");
  if (at < 0) return null;
  const parts = sourcePath.slice(at + "node_modules/".length).split("/");
  if (parts[0].startsWith("@")) return parts[1] ? `${parts[0]}/${parts[1]}` : null;
  return parts[0] || null;
}

/** Every package named by a list of source-map `sources`, sorted, once each. */
export function inlinedPackages(sources) {
  return [...new Set(sources.map(packageOf).filter((name) => name !== null))].sort();
}

const HEADING = /^## (.+?) - (\S+) \((.+)\)$/;

/**
 * The notices with every empty entry filled and the inlined packages added.
 * `fill(name)` gives the text for a package whose entry is empty, or null;
 * `inlined` is [{name, version, license, text}] for packages bundled inside
 * another. Throws when an entry would still have no text.
 */
export function completeLicences(text, { fill, inlined = [] }) {
  const lines = text.replace(/\s+$/, "").split("\n");
  const out = [];
  const missing = [];
  for (let i = 0; i < lines.length; i += 1) {
    out.push(lines[i]);
    const heading = lines[i].match(HEADING);
    if (!heading) continue;
    let next = i + 1;
    while (next < lines.length && lines[next].trim() === "") next += 1;
    const empty = next >= lines.length || HEADING.test(lines[next]);
    if (!empty) continue;
    const body = fill(heading[1]);
    if (body && body.trim()) out.push("", body.trim(), "");
    else missing.push(heading[1]);
  }
  const listed = new Set(lines.map((l) => l.match(HEADING)?.[1]).filter(Boolean));
  const extra = inlined.filter((p) => !listed.has(p.name));
  if (extra.length > 0) {
    out.push("", "---", "", "Bundled inside maplibre-gl's own prebuilt files:", "");
    for (const p of extra) {
      if (!p.text || !p.text.trim()) {
        missing.push(p.name);
        continue;
      }
      out.push(`## ${p.name} - ${p.version} (${p.license})`, "", p.text.trim(), "");
    }
  }
  if (missing.length > 0) throw new Error(`no licence text for bundled package(s): ${missing.join(", ")}`);
  return out.join("\n").replace(/\n{3,}/g, "\n\n") + "\n";
}

/** The fonts the app serves from /assets/ (src/fonts/fonts.css), each with the licence file shipped beside it. */
export const BUNDLED_FONTS = [
  { name: "Atkinson Hyperlegible", version: "2020", license: "OFL-1.1", file: "src/fonts/OFL.txt" },
];

/**
 * The notices with the bundled fonts' credit and licence text added under a heading of their own.
 * `fonts` is [{name, version, license, text}]; throws when one has no text, as a package without
 * text does.
 */
export function withFontNotices(text, fonts) {
  if (fonts.length === 0) return text;
  const missing = fonts.filter((f) => !f.text || !f.text.trim()).map((f) => f.name);
  if (missing.length > 0) throw new Error(`no licence text for bundled font(s): ${missing.join(", ")}`);
  const out = [text.replace(/\s+$/, ""), "", "---", "", "Fonts served with the app (the SIL Open Font License allows this; the licence travels with the font):", ""];
  for (const f of fonts) out.push(`## ${f.name} - ${f.version} (${f.license})`, "", f.text.trim(), "");
  return out.join("\n").replace(/\n{3,}/g, "\n\n") + "\n";
}

/** A package's own licence file's text, or null. */
export function licenceFile(dir) {
  const name = readdirSync(dir).find((f) => /^(licen[cs]e|copying)/i.test(f));
  return name ? readFileSync(join(dir, name), "utf8") : null;
}

/** The Vite plugin: rewrites dist/licenses.txt once the bundle is written. */
export function licenceNotices(root, fileName = "licenses.txt") {
  const committed = (name) => {
    const rel = COMMITTED_NOTICES[name];
    return rel ? readFileSync(join(root, rel), "utf8") : null;
  };
  return {
    name: "routemaker-licence-notices",
    apply: "build",
    writeBundle: {
      order: "post",
      handler(options) {
        const file = join(options.dir, fileName);
        const maps = join(root, "node_modules/maplibre-gl/dist");
        const sources = readdirSync(maps)
          .filter((f) => f.endsWith(".mjs.map") && !f.includes("-dev"))
          .flatMap((f) => JSON.parse(readFileSync(join(maps, f), "utf8")).sources);
        const inlined = inlinedPackages(sources).map((name) => {
          const dir = join(root, "node_modules", name);
          const pkg = JSON.parse(readFileSync(join(dir, "package.json"), "utf8"));
          return { name, version: pkg.version, license: pkg.license, text: licenceFile(dir) ?? committed(name) };
        });
        if (!existsSync(file)) throw new Error(`${fileName} was not written by build.license`);
        const fonts = BUNDLED_FONTS.map((f) => ({ ...f, text: existsSync(join(root, f.file)) ? readFileSync(join(root, f.file), "utf8") : null }));
        writeFileSync(file, withFontNotices(completeLicences(readFileSync(file, "utf8"), { fill: committed, inlined }), fonts));
      },
    },
  };
}
