// The course export's place on the page: Plan's GPX section offers the file type and the device, labelled; the
// line saying what was fitted is said in the section's existing polite region; Go adds no control.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("the GPX section offers the course formats and devices, labelled, and says the result in its polite region", () => {
  const panel = read("../GpxPanel.tsx");
  assert.match(panel, /<label className="select-setting">\s*File type\s*<select/);
  assert.match(panel, /<label className="select-setting">\s*Device\s*<select/);
  assert.match(panel, /DEVICE_PROFILES\.map/);
  // The line is said in the section's existing status region, as a new node each time so a repeat is heard.
  const region = panel.slice(panel.indexOf('<div role="status" aria-live="polite">'));
  assert.match(region.slice(0, region.indexOf("</div>")), /<p key=\{courseSaid\.count\} className="hint gpx-course">/);
  // The button names the file it saves.
  assert.match(panel, /Download \{FORMAT_WORDS\[choice\.format\]\}/);
  assert.match(panel, /const FORMAT_WORDS: Record<ExportFormat, string> = \{ gpx: "GPX", fit: "FIT", tcx: "TCX", "pdf-sheet": "PDF", "pdf-strip": "PDF" \};/);
});

test("the PDF cue sheets are two more file types in the same choice, with no device choice and no new button", () => {
  const panel = read("../GpxPanel.tsx");
  assert.match(panel, /"pdf-sheet": "PDF cue sheet, to print",/);
  assert.match(panel, /"pdf-strip": "PDF handlebar strip, to print",/);
  // The device choice is for a course only.
  assert.match(panel, /\{isCourse\(choice\.format\) && \(\s*<label className="select-setting">\s*Device/);
  // One download button, as before.
  assert.equal(panel.match(/\n\s*Download \{/g)?.length, 1);
  // Made through the same checked download, its line said in the same region.
  assert.match(panel, /saveFile\(cueSheetPdf\(route, kind, vias\), "application\/pdf", cueSheetFileName\(route, kind\)\);\s*return cueSheetLine\(/);
});

test("Go adds no control: the choices appear only where the page passes the course download, which Go does not", () => {
  const panel = read("../GpxPanel.tsx");
  assert.match(panel, /const courses = onDownloadCourse !== undefined;/);
  assert.match(panel, /\{courses && \(\s*<div className="gpx-format">/);
  const app = read("../App.tsx");
  assert.match(app, /\.\.\.\(mode === "go" \? \{\} : \{ downloadCourse: downloadCourseRoute \}\)/);
  // Checked against the closures in force, as Download GPX is.
  assert.match(app, /const downloadCourseRoute = [\s\S]{0,300}?checkThen\("download", route\.geometry\.coordinates, false, \(\) => said\(downloadCourse\(/);
  // Go's own route row keeps its GPX button alone.
  assert.ok(!/FIT|TCX/.test(read("../app/RoutePanel.tsx")));
});
