/**
 * A TCX course file (Garmin's TrainingCenterDatabase v2 schema, TrainingCenterDatabasev2.xsd, read 2026-10-16),
 * from a compiled course (course.ts). PLAN.md, Formats: TCX "collapses hardest: its course point type is a
 * closed list of sixteen values with no slight, sharp, u-turn, fork, or roundabout, its point name is capped at ten
 * characters and the course name at fifteen, and both time and position are required on every course point. So
 * TCX ... carries an abbreviation in the name field and the full cue text in `CoursePoint/Notes`."
 *
 * Attribution goes in Course/Notes (PLAN.md's per-format slot). Clean: no Author element and no Creator (either
 * would name a device or an account), and every time is the course's fixed base plus the route's pace, so one
 * route gives the same bytes. Children are in the schema's sequence order: Course_t is Name, Lap, Track, Notes,
 * CoursePoint; CoursePoint_t is Name, Time, Position, AltitudeMeters, PointType, Notes.
 */
import type { Course, CourseCueType } from "./course.ts";

export const TCX_NS = "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2";

/**
 * PointType for each cue: the published mapping (stops, walks and notes, flagged crossings among them, collapse to
 * Generic; TCX has no slight turn, so a bear is a left or a right).
 */
export const TCX_CUE_TYPES: Record<CourseCueType, string> = {
  start: "Generic",
  finish: "Generic",
  stop: "Generic",
  walk: "Generic",
  note: "Generic",
  danger: "Danger",
  left: "Left",
  right: "Right",
  slight_left: "Left",
  slight_right: "Right",
};

export function escapeXml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\uFFFE\uFFFF]/g, "")
    // A lone surrogate is no character at all, so not XML either.
    .replace(/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/g, "");
}

/** "2000-01-01T00:12:34Z": whole seconds, UTC. */
function isoTime(unixS: number): string {
  return new Date(Math.round(unixS) * 1000).toISOString().replace(/\.\d{3}Z$/, "Z");
}

function position(lat: number, lon: number, indent: string): string[] {
  return [
    `${indent}<Position>`,
    `${indent}  <LatitudeDegrees>${lat.toFixed(6)}</LatitudeDegrees>`,
    `${indent}  <LongitudeDegrees>${lon.toFixed(6)}</LongitudeDegrees>`,
    `${indent}</Position>`,
  ];
}

/** The TCX course document for a compiled course (course.ts compileCourse with format "tcx"). */
export function writeTcx(course: Course): string {
  const lines: string[] = [];
  const first = course.records[0];
  const last = course.records[course.records.length - 1];
  const time = (s: number) => isoTime(course.baseUnixS + s);
  lines.push('<?xml version="1.0" encoding="UTF-8"?>');
  lines.push(`<TrainingCenterDatabase xmlns="${TCX_NS}">`);
  lines.push("  <Courses>");
  lines.push("    <Course>");
  lines.push(`      <Name>${escapeXml(course.name)}</Name>`);
  lines.push("      <Lap>");
  lines.push(`        <TotalTimeSeconds>${Math.round(course.totalS)}</TotalTimeSeconds>`);
  lines.push(`        <DistanceMeters>${course.totalM.toFixed(1)}</DistanceMeters>`);
  if (first) lines.push(...position(first.lat, first.lon, "        ").map((l) => l.replace("Position>", "BeginPosition>")));
  if (last) lines.push(...position(last.lat, last.lon, "        ").map((l) => l.replace("Position>", "EndPosition>")));
  lines.push("        <Intensity>Active</Intensity>");
  lines.push("      </Lap>");
  lines.push("      <Track>");
  for (const r of course.records) {
    lines.push("        <Trackpoint>");
    lines.push(`          <Time>${time(r.timeS)}</Time>`);
    lines.push(...position(r.lat, r.lon, "          "));
    if (r.ele !== null) lines.push(`          <AltitudeMeters>${r.ele.toFixed(1)}</AltitudeMeters>`);
    lines.push(`          <DistanceMeters>${r.distM.toFixed(1)}</DistanceMeters>`);
    lines.push("        </Trackpoint>");
  }
  lines.push("      </Track>");
  lines.push(`      <Notes>${escapeXml(course.notes)}</Notes>`);
  for (const c of course.cues) {
    const r = course.records[c.vertex];
    // TCX requires a time and a position on every course point: one with no record is left out.
    if (!r) continue;
    lines.push("      <CoursePoint>");
    lines.push(`        <Name>${escapeXml(c.name)}</Name>`);
    lines.push(`        <Time>${time(r.timeS)}</Time>`);
    lines.push(...position(r.lat, r.lon, "        "));
    if (r.ele !== null) lines.push(`        <AltitudeMeters>${r.ele.toFixed(1)}</AltitudeMeters>`);
    lines.push(`        <PointType>${TCX_CUE_TYPES[c.type]}</PointType>`);
    lines.push(`        <Notes>${escapeXml(c.text)}</Notes>`);
    lines.push("      </CoursePoint>");
  }
  lines.push("    </Course>");
  lines.push("  </Courses>");
  lines.push("</TrainingCenterDatabase>");
  return `${lines.join("\n")}\n`;
}
