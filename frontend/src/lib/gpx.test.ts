import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import {
  COPYRIGHT_AUTHOR,
  GPX_NS_11,
  GpxError,
  MAX_GPX_BYTES,
  MAX_GPX_POINTS,
  PLAN_TYPE_PREFIX,
  parseGpx,
  writeGpx,
  type GpxExport,
} from "./gpx.ts";
import type { LonLat } from "./geo.ts";

const FIXTURES = new URL("../../../fixtures/reference-routes/", import.meta.url);

const doc = (body: string, root = `xmlns="${GPX_NS_11}" version="1.1" creator="test"`) =>
  `<?xml version="1.0" encoding="UTF-8"?>\n<gpx ${root}>${body}</gpx>`;

const LINE: LonLat[] = [
  [-77.0434, 38.9096],
  [-77.03, 38.9],
  [-77.0091, 38.8899],
];

const EXPORT: GpxExport = {
  name: "Group Ride route, 4.1 km",
  description: "Group Ride. 4.1 km (2.5 mi), climb 12 m (39 ft).",
  attribution: [
    "© OpenStreetMap contributors, ODbL",
    "Stress tiers use traffic volume from the District Department of Transportation, adapted, CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)",
    "Traffic volume: Virginia Department of Transportation",
    "Elevation: USGS 3D Elevation Program",
  ],
  preset: "group-ride",
  planPoints: [LINE[0], LINE[2]],
  geometry: LINE,
};

// ---------------------------------------------------------------------------
// Reading

test("tracks keep every segment, in order, as lon/lat pairs", () => {
  const file = parseGpx(
    doc(
      `<trk><name>Two parts</name><trkseg><trkpt lat="38.9" lon="-77.0"/><trkpt lat="38.91" lon="-77.01"><ele>12</ele></trkpt></trkseg>` +
        `<trkseg><trkpt lat='38.92' lon='-77.02'></trkpt></trkseg></trk>` +
        `<trk><trkseg><trkpt lat="38.93" lon="-77.03"/></trkseg></trk>`,
    ),
  );
  assert.equal(file.tracks.length, 2);
  assert.equal(file.tracks[0].name, "Two parts");
  assert.deepEqual(file.tracks[0].segments, [
    [
      [-77.0, 38.9],
      [-77.01, 38.91],
    ],
    [[-77.02, 38.92]],
  ]);
  assert.deepEqual(file.tracks[1].segments, [[[-77.03, 38.93]]]);
});

test("routes, route point names and waypoints are read", () => {
  const file = parseGpx(
    doc(
      `<metadata><name>The &amp; ride</name></metadata>` +
        `<wpt lat="38.8" lon="-77.1"><name><![CDATA[Rest <stop>]]></name></wpt>` +
        `<rte><name>R</name><type>${PLAN_TYPE_PREFIX}mass-ride</type><rtept lat="38.9" lon="-77"><name>Start</name></rtept><rtept lat="38.95" lon="-77.05"/></rte>`,
    ),
  );
  assert.equal(file.name, "The & ride");
  assert.deepEqual(file.waypoints, [{ lon: -77.1, lat: 38.8, name: "Rest <stop>" }]);
  assert.equal(file.routes.length, 1);
  assert.equal(file.routes[0].type, `${PLAN_TYPE_PREFIX}mass-ride`);
  assert.deepEqual(
    file.routes[0].points.map((p) => [p.lon, p.lat, p.name]),
    [
      [-77, 38.9, "Start"],
      [-77.05, 38.95, undefined],
    ],
  );
});

test("a prefixed GPX namespace is GPX; the same names in another namespace are not", () => {
  const file = parseGpx(
    `<g:gpx xmlns:g="${GPX_NS_11}" xmlns:x="urn:other" version="1.1" creator="t">` +
      `<g:trk><g:trkseg><g:trkpt lat="38.9" lon="-77"><g:extensions><x:trkpt lat="1" lon="1"/></g:extensions></g:trkpt></g:trkseg></g:trk>` +
      `<x:trk><x:trkseg><x:trkpt lat="38.1" lon="-77"/></x:trkseg></x:trk></g:gpx>`,
  );
  assert.deepEqual(file.tracks.map((t) => t.segments), [[[[-77, 38.9]]]]);
});

test("GPX 1.0 is read, its name directly under gpx", () => {
  const file = parseGpx(
    `<gpx xmlns="http://www.topografix.com/GPX/1/0" version="1.0" creator="old"><name>Old</name>` +
      `<trk><trkseg><trkpt lat="38.9" lon="-77"/><trkpt lat="38.91" lon="-77"/></trkseg></trk></gpx>`,
  );
  assert.equal(file.version, "1.0");
  assert.equal(file.name, "Old");
  assert.equal(file.tracks[0].segments[0].length, 2);
});

test("points with an unusable position are skipped and counted", () => {
  const file = parseGpx(
    doc(
      `<trk><trkseg><trkpt lat="91" lon="-77"/><trkpt lat="38.9" lon="abc"/><trkpt lat="38.9"/><trkpt lat="38.9" lon="-77"/></trkseg></trk>`,
    ),
  );
  assert.equal(file.skipped, 3);
  assert.deepEqual(file.tracks[0].segments[0], [[-77, 38.9]]);
});

test("what is not well-formed GPX 1.0 or 1.1 is refused", () => {
  const refused: Array<[string, GpxError["code"]]> = [
    ["<kml><Document/></kml>", "not-gpx"],
    [`<gpx xmlns="${GPX_NS_11}" version="2.0"></gpx>`, "not-gpx"],
    [`<gpx version="1.1"></gpx>`, "not-gpx"],
    [`<gpx xmlns="http://www.topografix.com/GPX/1/0" version="1.1"></gpx>`, "not-gpx"],
    [`<gpx xmlns="http://www.topografix.com/GPX/1/0" version="2.0"></gpx>`, "not-gpx"],
    [doc("<trk><name>a</trk></name>"), "malformed"],
    [doc("<trk><trkseg></trk>"), "malformed"],
    [doc("<trk>"), "malformed"],
    [doc("") + "<gpx/>", "malformed"],
    [doc("") + "trailing text", "malformed"],
    [doc("<trk><name>a &nbsp; b</name></trk>"), "malformed"],
    [doc('<trk><trkseg><trkpt lat="38.9" lon="-77"'), "malformed"],
    ["", "not-gpx"],
    ["just text", "malformed"],
  ];
  for (const [text, code] of refused) {
    assert.throws(() => parseGpx(text), (e: unknown) => e instanceof GpxError && e.code === code, text);
  }
});

test("a DOCTYPE is refused, so no entity is ever expanded", () => {
  const bomb =
    `<?xml version="1.0"?><!DOCTYPE gpx [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]>` +
    `<gpx xmlns="${GPX_NS_11}" version="1.1" creator="x"><metadata><name>&b;</name></metadata></gpx>`;
  assert.throws(() => parseGpx(bomb), (e: unknown) => e instanceof GpxError && e.code === "doctype");
});

test("more than the point cap is refused; the cap itself is read", () => {
  const points = (n: number) => `<trk><trkseg>${'<trkpt lat="38.9" lon="-77"/>'.repeat(n)}</trkseg></trk>`;
  assert.equal(parseGpx(doc(points(MAX_GPX_POINTS))).tracks[0].segments[0].length, MAX_GPX_POINTS);
  assert.throws(
    () => parseGpx(doc(points(MAX_GPX_POINTS) + '<wpt lat="38.9" lon="-77"/>')),
    (e: unknown) => e instanceof GpxError && e.code === "too-many-points",
  );
});

test("a text longer than 20 MB is refused before it is scanned", () => {
  assert.throws(
    () => parseGpx(doc("") + " ".repeat(MAX_GPX_BYTES)),
    (e: unknown) => e instanceof GpxError && e.code === "too-big",
  );
});

test("a > inside a quoted attribute value does not end the tag", () => {
  const file = parseGpx(doc(`<trk><trkseg><trkpt lat="38.9" lon="-77" x="a>b"/><trkpt lon='-77.1' y='c>"d' lat='38.8'/></trkseg></trk>`));
  assert.deepEqual(file.tracks[0].segments[0], [[-77, 38.9], [-77.1, 38.8]]);
});

test("a byte-order mark, comments and processing instructions are allowed", () => {
  const file = parseGpx(
    `﻿<?xml version="1.0"?><!-- a comment --><gpx xmlns="${GPX_NS_11}" version="1.1" creator="t"><!-- <trk> -->` +
      `<?pi x?><trk><trkseg><trkpt lat="38.9" lon="-77"/></trkseg></trk></gpx>\n`,
  );
  assert.equal(file.tracks.length, 1);
});

test("every reference route fixture reads as one track of its trkpt count", (t) => {
  if (!existsSync(FIXTURES)) {
    // Run from frontend/ alone (a container with only frontend/ mounted).
    t.skip("the repository's fixtures/ is not here");
    return;
  }
  const names = readdirSync(FIXTURES).filter((n) => n.endsWith(".gpx"));
  assert.ok(names.length >= 10, `${names.length}`);
  for (const name of names) {
    const text = readFileSync(new URL(name, FIXTURES), "utf8");
    const file = parseGpx(text);
    const count = (text.match(/<trkpt\b/g) ?? []).length;
    assert.equal(file.tracks.flatMap((t) => t.segments).flat().length, count, name);
  }
});

test("a 100,000-point file reads in seconds, not minutes", () => {
  const body = Array.from(
    { length: MAX_GPX_POINTS },
    (_, i) => `<trkpt lat="${(38.8 + i * 1e-6).toFixed(7)}" lon="${(-77.1 + i * 1e-6).toFixed(7)}"><ele>12.5</ele><time>2026-01-01T00:00:00Z</time></trkpt>`,
  ).join("\n");
  const text = doc(`<trk><trkseg>${body}</trkseg></trk>`);
  const started = performance.now();
  const file = parseGpx(text);
  const elapsed = performance.now() - started;
  assert.equal(file.tracks[0].segments[0].length, MAX_GPX_POINTS);
  // About 0.7 s on the development host; a scanner that went quadratic
  // would take minutes. The page parses in a worker, so this is not a freeze.
  assert.ok(elapsed < 10_000, `${elapsed} ms for ${text.length} bytes`);
});

// ---------------------------------------------------------------------------
// Writing

/** A minimal XML tree of the writer's own output, for the structural checks. */
interface Node {
  name: string;
  attributes: Record<string, string>;
  children: Node[];
  text: string;
}

function tree(xml: string): Node {
  const root: Node = { name: "#root", attributes: {}, children: [], text: "" };
  const stack = [root];
  const token = /<\?[^?]*\?>|<\/([\w:]+)>|<([\w:]+)((?:\s+[\w:]+="[^"]*")*)\s*(\/?)>|([^<]+)/g;
  let m: RegExpExecArray | null;
  while ((m = token.exec(xml)) !== null) {
    if (m[0].startsWith("<?")) continue;
    if (m[1]) {
      const top = stack.pop();
      assert.equal(top?.name, m[1], "tags match");
    } else if (m[2]) {
      const attributes: Record<string, string> = {};
      for (const a of m[3].matchAll(/([\w:]+)="([^"]*)"/g)) attributes[a[1]] = a[2];
      const node: Node = { name: m[2], attributes, children: [], text: "" };
      stack[stack.length - 1].children.push(node);
      if (!m[4]) stack.push(node);
    } else if (m[5] !== undefined) {
      stack[stack.length - 1].text += m[5];
    }
  }
  assert.equal(stack.length, 1, "every element closed");
  assert.equal(root.children.length, 1, "one root");
  return root.children[0];
}

// The GPX 1.1 schema's content models for the types the writer emits,
// transcribed from http://www.topografix.com/GPX/1/1/gpx.xsd (no copy of the
// schema is in the repository and none was fetched): each is the ordered
// sequence of child elements with its maxOccurs.
const MANY = Number.POSITIVE_INFINITY;
const CONTENT: Record<string, Array<[string, number]>> = {
  gpx: [["metadata", 1], ["wpt", MANY], ["rte", MANY], ["trk", MANY], ["extensions", 1]],
  metadata: [
    ["name", 1], ["desc", 1], ["author", 1], ["copyright", 1], ["link", MANY],
    ["time", 1], ["keywords", 1], ["bounds", 1], ["extensions", 1],
  ],
  copyright: [["year", 1], ["license", 1]],
  link: [["text", 1], ["type", 1]],
  rte: [
    ["name", 1], ["cmt", 1], ["desc", 1], ["src", 1], ["link", MANY], ["number", 1],
    ["type", 1], ["extensions", 1], ["rtept", MANY],
  ],
  trk: [
    ["name", 1], ["cmt", 1], ["desc", 1], ["src", 1], ["link", MANY], ["number", 1],
    ["type", 1], ["extensions", 1], ["trkseg", MANY],
  ],
  trkseg: [["trkpt", MANY], ["extensions", 1]],
  wpt: [
    ["ele", 1], ["time", 1], ["magvar", 1], ["geoidheight", 1], ["name", 1], ["cmt", 1], ["desc", 1],
    ["src", 1], ["link", MANY], ["sym", 1], ["type", 1], ["fix", 1], ["sat", 1], ["hdop", 1],
    ["vdop", 1], ["pdop", 1], ["ageofdgpsdata", 1], ["dgpsid", 1], ["extensions", 1],
  ],
};
const TYPE_OF: Record<string, string> = { rtept: "wpt", trkpt: "wpt", wpt: "wpt" };
const REQUIRED_ATTRIBUTES: Record<string, string[]> = {
  gpx: ["version", "creator"],
  copyright: ["author"],
  link: ["href"],
  wpt: ["lat", "lon"],
};
const LEAVES = new Set(["name", "cmt", "desc", "type", "license", "text", "year", "time", "keywords"]);

function checkSchema(node: Node, path = "gpx"): void {
  const type = TYPE_OF[node.name] ?? node.name;
  for (const attribute of REQUIRED_ATTRIBUTES[type] ?? []) {
    assert.ok(attribute in node.attributes, `${path} needs @${attribute}`);
  }
  if (type === "wpt") {
    const lat = Number(node.attributes.lat);
    const lon = Number(node.attributes.lon);
    assert.ok(lat >= -90 && lat <= 90, `${path} latitudeType`);
    assert.ok(lon >= -180 && lon < 180, `${path} longitudeType`);
  }
  if (LEAVES.has(node.name)) {
    assert.equal(node.children.length, 0, `${path} is simple content`);
    return;
  }
  const model = CONTENT[type];
  assert.ok(model, `${path}: an element the checker knows`);
  let at = 0;
  let used = 0;
  for (const child of node.children) {
    while (at < model.length && (model[at][0] !== child.name || used >= model[at][1])) {
      at += 1;
      used = 0;
    }
    assert.ok(at < model.length, `${path}/${child.name} is allowed there, in that order`);
    used += 1;
    checkSchema(child, `${path}/${child.name}`);
  }
  assert.equal(node.text.trim(), "", `${path} has no stray text`);
}

test("the export follows the GPX 1.1 schema's structure", () => {
  const root = tree(writeGpx(EXPORT));
  assert.equal(root.name, "gpx");
  assert.equal(root.attributes.xmlns, GPX_NS_11);
  assert.equal(root.attributes.version, "1.1");
  checkSchema(root);
  // And the checker itself refuses an order the schema refuses.
  const swapped = tree(writeGpx(EXPORT).replace(/<rte>[\s\S]*<\/rte>\n/, "") .replace("</trk>", "</trk>\n  <rte><name>x</name></rte>"));
  assert.throws(() => checkSchema(swapped));
});

test("the export's attribution: OpenStreetMap in metadata/copyright with no year, every credit in the file", () => {
  const xml = writeGpx(EXPORT);
  const root = tree(xml);
  const metadata = root.children.find((c) => c.name === "metadata");
  const copyright = metadata?.children.find((c) => c.name === "copyright");
  assert.equal(copyright?.attributes.author, COPYRIGHT_AUTHOR);
  assert.match(copyright?.children.find((c) => c.name === "license")?.text ?? "", /odbl/i);
  assert.equal(copyright?.children.some((c) => c.name === "year"), false);
  assert.doesNotMatch(xml, /<year>/);
  for (const credit of EXPORT.attribution) {
    assert.ok(xml.includes(credit.replace(/&/g, "&amp;")), credit);
  }
  // With no attribution from the answer, the OpenStreetMap credit is still there.
  const bare = writeGpx({ ...EXPORT, attribution: [] });
  assert.match(bare, /<copyright author="OpenStreetMap contributors">/);
  assert.match(bare, /<desc>Route data: © OpenStreetMap contributors, ODbL\.<\/desc>/);
});

test("the export names the application, and carries no author, time or other identifying element", () => {
  const xml = writeGpx(EXPORT);
  assert.match(xml, /<gpx [^>]*creator="RouteMaker"/);
  assert.deepEqual(Object.keys(tree(xml).attributes).sort(), [
    "creator",
    "version",
    "xmlns",
    "xmlns:xsi",
    "xsi:schemaLocation",
  ]);
  for (const element of ["author", "time", "email", "extensions", "src"]) {
    assert.doesNotMatch(xml, new RegExp(`<${element}\\b`), element);
  }
});

test("the same route gives the same bytes", () => {
  assert.equal(writeGpx(EXPORT), writeGpx({ ...EXPORT, geometry: EXPORT.geometry.map((p) => [...p] as LonLat) }));
});

test("the track is the route line and the route points are the plan's, both at fixed precision", () => {
  const file = parseGpx(writeGpx(EXPORT));
  const round = (points: readonly LonLat[]) => points.map(([lon, lat]) => [Number(lon.toFixed(6)), Number(lat.toFixed(6))]);
  assert.deepEqual(file.tracks[0].segments[0], round(EXPORT.geometry));
  assert.deepEqual(
    file.routes[0].points.map((p) => [p.lon, p.lat]),
    round(EXPORT.planPoints),
  );
  assert.deepEqual(
    file.routes[0].points.map((p) => p.name),
    ["Start", "End"],
  );
  assert.equal(file.routes[0].type, `${PLAN_TYPE_PREFIX}group-ride`);
  assert.match(writeGpx(EXPORT), /lat="38\.909600" lon="-77\.043400"/);
});

test("text is escaped, and characters XML cannot carry are dropped", () => {
  const xml = writeGpx({ ...EXPORT, name: 'A <b> & "c" &amp;\u0001', attribution: ["x < y"] });
  const file = parseGpx(xml);
  assert.equal(file.name, 'A <b> & "c" &amp;');
  assert.match(xml, /Route data: x &lt; y\./);
});
