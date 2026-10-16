// The PDF cue sheets (PLAN.md, Formats: the rider cue sheet and the handlebar-format narrow one): Ride's cues in a
// table, US units first with metric in brackets, no place named (so never a Home), credits in the footer, the same
// bytes every time, and a well-formed tagged PDF (header, xref, trailer, structure tree, text layer).
import { test } from "node:test";
import assert from "node:assert/strict";
import type { DescriptionEntry } from "./api.ts";
import { routeCues } from "./course.ts";
import { cueRows, cueSheetFileName, cueSheetLine, cueSheetPdf, cueSheetTitle, rowDistance, sheetWarnings, summaryLine } from "./cueSheetPdf.ts";
import { TaggedPdf, textWidth, winAnsi, wrapText } from "./pdf.ts";
import { sampleRoute } from "./courseRoute.test.fixture.ts";

const latin1 = (bytes: Uint8Array) => Array.from(bytes, (b) => String.fromCharCode(b)).join("");

/** The file's objects by number, found through its own xref table; throws where the table or trailer is wrong. */
function parsePdf(file: string): { objects: Map<number, string>; trailer: string } {
  assert.ok(file.startsWith("%PDF-1.7\n"), "header");
  assert.ok(file.endsWith("%%EOF\n"), "end marker");
  const startxref = Number(/startxref\n(\d+)\n%%EOF\n$/.exec(file)?.[1]);
  assert.equal(file.slice(startxref, startxref + 5), "xref\n", "startxref points at the xref table");
  const head = /^xref\n0 (\d+)\n/.exec(file.slice(startxref));
  assert.ok(head, "xref subsection");
  const size = Number(head[1]);
  const table = file.slice(startxref + head[0].length);
  assert.equal(table.slice(0, 20), "0000000000 65535 f \n", "object 0 is free");
  const objects = new Map<number, string>();
  for (let n = 1; n < size; n += 1) {
    const entry = table.slice(n * 20, n * 20 + 20);
    assert.match(entry, /^\d{10} 00000 n \n$/, `xref entry ${n} is 20 bytes`);
    const at = Number(entry.slice(0, 10));
    assert.equal(file.slice(at, at + `${n} 0 obj\n`.length), `${n} 0 obj\n`, `xref offset of object ${n}`);
    const end = file.indexOf("\nendobj\n", at);
    objects.set(n, file.slice(at + `${n} 0 obj\n`.length, end));
  }
  const trailer = file.slice(file.indexOf("trailer\n", startxref));
  assert.match(trailer, new RegExp(`/Size ${size} `));
  return { objects, trailer };
}

/** The text a viewer extracts, in content order: every Tj string, unescaped (WinAnsi, read as Latin-1). */
function shownText(file: string): string[] {
  return Array.from(file.matchAll(/\(((?:\\.|[^\\)])*)\) Tj/g), (m) =>
    m[1].replace(/\\([0-7]{3}|.)/g, (_, e: string) => (e.length === 3 ? String.fromCharCode(parseInt(e, 8)) : e)),
  );
}

test("the rider sheet's rows are Ride's cues: miles and km from the start, the turn, the road, the notes", () => {
  assert.deepEqual(
    cueRows(sampleRoute(), "sheet").map((r) => [rowDistance(r), r.turn, r.road, r.notes]),
    [
      ["0.0 mi (0.0 km)", "Start", "R Street Northwest", ""],
      ["0.3 mi (0.5 km)", "Left", "17th Street Northwest", ""],
      ["0.6 mi (0.9 km)", "Caution", "Florida Avenue Northwest", "Cross Florida Avenue Northwest (LTS 4)."],
      ["0.7 mi (1.2 km)", "Caution", "Dupont Circle", "Avoid-rated junction ahead: Dupont Circle."],
      ["0.9 mi (1.5 km)", "Stop 1", "", ""],
      ["0.9 mi (1.5 km)", "Right", "", ""],
      ["1.2 mi (2.0 km)", "Note", "Connecticut Avenue Northwest", "Connecticut Avenue Northwest, busy road (LTS 4)."],
      ["1.9 mi (3.0 km)", "Finish", "", "The end of the route."],
    ],
  );
  // The same cues, in the same order, as the FIT and TCX courses.
  assert.deepEqual(
    cueRows(sampleRoute(), "sheet").map((r) => r.type),
    routeCues(sampleRoute()).map((c) => c.type),
  );
  // A via point is no cue, as in Ride.
  assert.ok(!cueRows(sampleRoute(), "sheet", [1]).some((r) => r.type === "stop"));
});

test("the handlebar strip keeps the distance, turn and road, and leaves out the notes on the road", () => {
  const rows = cueRows(sampleRoute(), "strip");
  assert.deepEqual(
    rows.map((r) => r.turn),
    ["Start", "Left", "Caution", "Caution", "Stop 1", "Right", "Finish"],
  );
  const text = shownText(latin1(cueSheetPdf(sampleRoute(), "strip")));
  // Large type: the miles at 16 pt, the road abbreviated as a unit's screen has it.
  // A space is kept at each break, so the text layer reads "0.3 mi (0.5 km)".
  assert.ok(text.includes("0.3 ") && text.includes("mi (0.5 km)") && text.includes("17th St NW"));
  assert.ok(!text.some((t) => /busy road/.test(t)), "no notes column");
});

test("US units first, metric in brackets, in everything the sheet says", () => {
  const route = sampleRoute();
  assert.equal(summaryLine(route), "Distance 1.9 mi (3.0 km). Climb 39 ft (12 m), descent 26 ft (8 m). Moving time about 10 min.");
  const text = shownText(latin1(cueSheetPdf(route, "sheet")));
  assert.ok(text.includes("Miles (km)"));
  for (const t of text) {
    // A metric figure is only ever in brackets after the US one: "(0.5 km)" after "mi", "(12 m)" after "ft".
    for (const m of t.matchAll(/\d[\d.,]* (km|m)\b/g)) {
      assert.match(t.slice(0, m.index), /(mi|ft) \($/, t);
    }
  }
  assert.ok(text.some((t) => /mi \(\d/.test(t)) && text.some((t) => /ft \(\d/.test(t)));
  assert.ok(text.includes("1.9 mi (3.0 km)"));
});

test("the warnings are the route's own notices", () => {
  const route = sampleRoute({ avoid_notice: "This route goes through an Avoid-rated junction: Dupont Circle, fast merging traffic." });
  assert.deepEqual(sheetWarnings(route), ["This route goes through an Avoid-rated junction: Dupont Circle, fast merging traffic."]);
  assert.deepEqual(sheetWarnings(sampleRoute()), []);
  const text = shownText(latin1(cueSheetPdf(route, "sheet")));
  assert.ok(text.includes("Warnings"));
  assert.ok(!shownText(latin1(cueSheetPdf(sampleRoute(), "sheet"))).includes("Warnings"));
});

test("no place is named, so a Home never is: the name is the ride type and distance, the points Start, Stop N, Finish", () => {
  // A street the API happens to call Home is the road's name; a plan point's label never reaches the sheet.
  const route = sampleRoute();
  for (const kind of ["sheet", "strip"] as const) {
    const file = latin1(cueSheetPdf(route, kind));
    assert.ok(!file.includes("Home"));
    assert.ok(!file.includes("H\\000o"), "nor in the UTF-16 title");
    assert.equal(cueSheetTitle(route, kind), kind === "sheet" ? "Cue sheet, Default route, 1.9 mi (3.0 km)" : "Handlebar cue strip, Default route, 1.9 mi (3.0 km)");
  }
  assert.equal(cueSheetFileName(route, "sheet"), "routemaker-default-1_9mi-cues.pdf");
  assert.equal(cueSheetFileName(route, "strip"), "routemaker-default-1_9mi-strip.pdf");
});

test("the credits are in every page's footer and once at the end, with no author, producer or dates", () => {
  const file = latin1(cueSheetPdf(sampleRoute(), "sheet"));
  const text = shownText(file);
  const credit = "Route data: \xa9 OpenStreetMap contributors (ODbL); USGS 3DEP. Planned with RouteMaker.";
  assert.equal(text.filter((t) => t === credit).length, 2);
  assert.ok(text.includes("Page 1 of 1"));
  assert.ok(!/\/(Author|Producer|CreationDate|ModDate)\b/.test(file));
});

test("the file is a well-formed PDF: header, xref offsets, trailer, page tree and content lengths", () => {
  for (const kind of ["sheet", "strip"] as const) {
    const file = latin1(cueSheetPdf(sampleRoute(), kind));
    const { objects, trailer } = parsePdf(file);
    assert.match(trailer, /\/Root 1 0 R \/Info 7 0 R \/ID \[<[0-9A-F]{32}> <[0-9A-F]{32}>\]/);
    assert.match(objects.get(1) ?? "", /\/Type \/Catalog .*\/StructTreeRoot 5 0 R \/MarkInfo << \/Marked true >> \/Lang \(en-US\)/);
    assert.match(objects.get(2) ?? "", /\/Type \/Pages \/Kids \[8 0 R\] \/Count 1/);
    const page = objects.get(8) ?? "";
    assert.match(page, kind === "sheet" ? /\/MediaBox \[0 0 612 792\]/ : /\/MediaBox \[0 0 216 792\]/);
    const stream = /^<< \/Length (\d+) >>\nstream\n([\s\S]*)\nendstream$/.exec(objects.get(9) ?? "");
    assert.ok(stream, "content stream");
    assert.equal(Number(stream[1]), stream[2].length, "stream Length");
    // ASCII after the binary marker.
    assert.ok(/^[\x0a\x20-\x7e]*$/.test(file.slice(15)));
  }
});

test("it is tagged: every marked run belongs to a structure element in the parent tree, the rest are artifacts", () => {
  const file = latin1(cueSheetPdf(sampleRoute(), "sheet"));
  const { objects } = parsePdf(file);
  const stream = objects.get(9) ?? "";
  const runs = Array.from(stream.matchAll(/\/(\w+) <<\/MCID (\d+)>> BDC/g));
  assert.ok(runs.length > 20);
  runs.forEach((m, i) => assert.equal(Number(m[2]), i, "MCIDs in order from 0"));
  const nums = /\/Nums \[0 \[([^\]]*)\]\]/.exec(objects.get(6) ?? "");
  assert.ok(nums, "parent tree for page 0");
  const owners = nums[1].trim().split(/ 0 R ?/).filter(Boolean).map(Number);
  assert.equal(owners.length, runs.length);
  owners.forEach((n, mcid) => {
    const el = objects.get(n) ?? "";
    assert.match(el, new RegExp(`/S /${runs[mcid][1]} `), `MCID ${mcid}'s element is its tag`);
    assert.match(el, new RegExp(`/MCID ${mcid} >>`));
  });
  // The table: header cells scoped to their columns, four to a row.
  const elems = Array.from(objects.values()).filter((o) => o.includes("/Type /StructElem"));
  assert.equal(elems.filter((o) => /\/S \/TH .*\/Scope \/Column/.test(o)).length, 4);
  assert.equal(elems.filter((o) => o.includes("/S /TR ")).length, 1 + cueRows(sampleRoute(), "sheet").length);
  assert.equal(elems.filter((o) => o.includes("/S /H1 ")).length, 1);
  // Footer and rules are artifacts.
  assert.ok(/\/Artifact BMC BT [^\n]*\(Page 1 of 1\) Tj ET EMC/.test(stream));
});

test("a long route runs to more pages, the header carried over as an artifact, the parent tree per page", () => {
  const base = sampleRoute();
  const line = Array.from({ length: 3001 }, (_, i) => [base.geometry.coordinates[0][0] + i * 0.0001156, base.geometry.coordinates[0][1]] as [number, number]);
  const description: DescriptionEntry[] = Array.from({ length: 80 }, (_, k) => ({
    kind: "stretch",
    from_m: k * 370,
    to_m: k * 370 + 370,
    from_mi: 0,
    to_mi: 0,
    street: `Street ${k} Northwest`,
    tier: 1,
    facility: null,
    turn: { movement: k % 2 ? "left" : "right", onto: `Street ${k} Northwest`, control: null, severity: null },
    text: `x: Turn onto Street ${k} Northwest.`,
  })) as DescriptionEntry[];
  const route = sampleRoute({ geometry: { type: "LineString", coordinates: line }, distance_m: 30000, description });
  const file = latin1(cueSheetPdf(route, "sheet"));
  const { objects } = parsePdf(file);
  const count = Number(/\/Count (\d+)/.exec(objects.get(2) ?? "")?.[1]);
  assert.ok(count >= 2, `pages: ${count}`);
  const text = shownText(file);
  assert.ok(text.includes(`Page ${count} of ${count}`));
  assert.equal(text.filter((t) => t === "Miles (km)").length, count, "the header on every page");
  // Tagged once: the carried-over header rows are artifacts.
  const elems = Array.from(objects.values()).filter((o) => o.includes("/Type /StructElem"));
  assert.equal(elems.filter((o) => o.includes("/S /TH ")).length, 4);
  assert.match(objects.get(6) ?? "", new RegExp(`/Nums \\[0 \\[.*\\] ${count - 1} \\[`));
  // Every cue is there, in order.
  const roads = text.filter((t) => /^Street \d+ Northwest$/.test(t)).map((t) => Number(/\d+/.exec(t)?.[0]));
  assert.deepEqual(roads, [...roads].sort((a, b) => a - b));
  assert.equal(new Set(roads).size, 80);
});

test("the status line says what was made, in US units with metric in brackets", () => {
  assert.equal(cueSheetLine(sampleRoute(), "sheet"), "PDF cue sheet: 8 cues, on letter paper.");
  assert.equal(cueSheetLine(sampleRoute(), "strip"), "PDF handlebar strip: 7 cues, 3 by 11 inches (7.6 by 27.9 cm); print at actual size and cut out.");
});

test("one route always gives the same bytes", () => {
  for (const kind of ["sheet", "strip"] as const) {
    assert.deepEqual(cueSheetPdf(sampleRoute(), kind), cueSheetPdf(sampleRoute(), kind));
  }
  assert.notDeepEqual(cueSheetPdf(sampleRoute(), "sheet"), cueSheetPdf(sampleRoute({ climb_m: 13 }), "sheet"));
});

test("the writer: WinAnsi text, Helvetica widths, wrapping, escaping", () => {
  assert.deepEqual(winAnsi("© – é ✓"), [0xa9, 0x20, 0x96, 0x20, 0xe9, 0x20, 0x3f]);
  assert.equal(textWidth("Hello", "regular", 10), 22.78);
  assert.ok(textWidth("Hello", "bold", 10) > textWidth("Hello", "regular", 10));
  assert.deepEqual(wrapText("Left onto Connecticut Avenue Northwest", "regular", 10, 100), ["Left onto Connecticut", "Avenue Northwest"]);
  for (const line of wrapText("Supercalifragilisticexpialidocious", "regular", 10, 40)) assert.ok(textWidth(line, "regular", 10) <= 40);
  const pdf = new TaggedPdf(100, 100, { title: "T", creator: "RouteMaker", lang: "en-US" });
  pdf.text(pdf.addPage(), pdf.element("P"), 10, 10, 10, "regular", "a (b) \\ ©");
  assert.ok(pdf.serialize().includes("(a \\(b\\) \\\\ \\251) Tj"));
});
