// Route notes (lib/routeNotes.ts; Stephen 2026-11-10): kept in the link, a cue where the line passes them, said in
// Ride, and a row of every export.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { MAX_NOTES, NOTE_ICONS, NOTE_NEAR_M, NOTE_TEXT_MAX, PAGE_NOTES, cleanNoteText, decodeNotes, encodeNotes, noteIcon, notesFit, noteRideText, type RouteNote } from "./routeNotes.ts";
import { NOTE_ICON_WORDS } from "./routeNotesPlan.ts";
import { decodePlan, encodePlan } from "./planHash.ts";
import { NOTE_AT_TURN_M, cueSpoken, nextAction, phasesFor, rideModel, says } from "./navigate.ts";
import { compileCourse } from "./course.ts";
import { cueRows } from "./cueSheetPdf.ts";
import { deviceProfile } from "./deviceProfiles.ts";
import { at, sampleRoute } from "./courseRoute.test.fixture.ts";

const caution: RouteNote = { at: at(700, 20), kind: "caution", text: "Busy crossing, no light" };
const mural: RouteNote = { at: at(2500, -15), kind: "interest", text: "Mural on the 2200 Street side." };

test("a note's words are kept short and plain", () => {
  assert.equal(cleanNoteText("  Busy\n crossing\t "), "Busy crossing");
  assert.equal(cleanNoteText("x".repeat(200)).length, NOTE_TEXT_MAX);
  assert.equal(cleanNoteText("   "), "");
});

test("the link carries each note's kind, place and words, a comma in the words too", () => {
  const values = encodeNotes([caution, mural]);
  assert.equal(values[0], `c,${caution.at[0].toFixed(5)},${caution.at[1].toFixed(5)},Busy crossing, no light`);
  const back = decodeNotes(values);
  assert.deepEqual(back.map((n) => [n.kind, n.text]), [["caution", "Busy crossing, no light"], ["interest", "Mural on the 2200 Street side."]]);
  assert.ok(Math.abs(back[0].at[0] - caution.at[0]) < 1e-5);
  // Words left empty, an unknown kind or a broken place are left out.
  assert.deepEqual(decodeNotes(["c,-77.0,38.9,", "x,-77.0,38.9,Hi", "c,abc,38.9,Hi", "i,-77.0,138.9,Hi"]), []);
  assert.equal(decodeNotes(Array.from({ length: MAX_NOTES + 5 }, (_, i) => `i,-77.0,38.9,Note ${i}`)).length, MAX_NOTES);
});

test("a plan's link keeps its notes; an older link has none", () => {
  const points = [at(0), at(3000)];
  const hash = encodePlan(points, "default", undefined, [], [], new Map(), "q", [caution]);
  assert.match(hash, /&nt=c,-77\.04191,38\.90018,Busy\+crossing,\+no\+light&/);
  assert.deepEqual(decodePlan(hash).notes.map((n) => n.text), ["Busy crossing, no light"]);
  assert.deepEqual(decodePlan(encodePlan(points, "default", undefined, [], [], new Map(), "q", [])).notes, []);
  // Unless given, none: the account's settings and a kept route's key never carry the page's notes.
  PAGE_NOTES.list = [mural];
  try {
    assert.deepEqual(decodePlan(encodePlan(points, "default", undefined, [], [], new Map())).notes, []);
  } finally {
    PAGE_NOTES.list = [];
  }
});

test("a note near the line is a Ride cue where the line passes it; one far off is not", () => {
  const far: RouteNote = { at: at(1000, NOTE_NEAR_M + 40), kind: "caution", text: "Far away" };
  const model = rideModel(sampleRoute(), [], new Map(), new Map(), [caution, mural, far]);
  const notes = model.cues.filter((c) => c.kind === "note");
  assert.deepEqual(notes.map((c) => [Math.round(c.atM), c.text]), [[700, "Caution: Busy crossing, no light."], [2500, "Note: Mural on the 2200 Street side."]]);
  // In order along the line, indexed as it is, the end last.
  model.cues.forEach((c, i) => assert.equal(c.index, i));
  assert.ok(model.cues.every((c, i) => i === 0 || model.cues[i - 1].atM <= c.atM));
  assert.equal(model.cues[model.cues.length - 1].kind, "end");
  // Said once, early, as a hazard is: "In 500 feet, caution: ...".
  const cue = notes[0];
  assert.deepEqual(phasesFor("full", cue, 5).map((p) => p.phase), ["advance"]);
  assert.match(cueSpoken(cue, "advance", 152), /^In 500 feet, caution: Busy crossing, no light\.$/);
  // The stoker hears a caution, not a point of interest; quiet, neither.
  assert.equal(says("stoker", cue), true);
  assert.equal(says("stoker", notes[1]), false);
  assert.equal(says("quiet", cue), false);
});

test("Ride's words for a note leave the rider's own full stop out of the template's", () => {
  assert.equal(noteRideText({ kind: "interest", text: "Great view." }), "Note: Great view.");
  assert.equal(noteRideText({ kind: "interest", text: "Fountain working?" }), "Note: Fountain working?");
});

test("a note is a row of the cue sheet, the strip and the phone images, in the rider's own words", () => {
  PAGE_NOTES.list = [caution, mural];
  try {
    for (const kind of ["sheet", "strip"] as const) {
      const rows = cueRows(sampleRoute(), kind).filter((r) => r.own);
      assert.deepEqual(rows.map((r) => [r.turn, r.road, r.arrow.kind]), [["Caution", "Busy crossing, no light", "caution"], ["Note", "Mural on the 2200 Street side.", "note"]], kind);
    }
  } finally {
    PAGE_NOTES.list = [];
  }
});

test("on a device a caution is a danger course point, never dropped; a point of interest a note", () => {
  PAGE_NOTES.list = [caution, mural];
  try {
    const course = compileCourse(sampleRoute(), deviceProfile("generic"), "fit");
    assert.deepEqual(course.cues.filter((c) => c.name.startsWith("Busy cross") || c.name.startsWith("Mural")).map((c) => c.type), ["danger", "note"]);
  } finally {
    PAGE_NOTES.list = [];
  }
});

test("Ride reads the page's notes; Plan's words for them stay out of Go and Ride's modules", () => {
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  assert.equal(ride.match(/PAGE_NOTES\.list/g)?.length, 2, "the ride's model and the closure's other line");
  const notes = readFileSync(new URL("./routeNotes.ts", import.meta.url), "utf8");
  assert.ok(!/t\("Add note"\)/.test(notes));
});

test("a note shows the icon chosen for it; the kind's own is left out of the link", () => {
  // Stephen 2026-11-10: "have that note appear on the map with a choice of icon".
  const pothole: RouteNote = { ...caution, icon: "pothole" };
  const [chosen, plain] = encodeNotes([pothole, { ...mural, icon: "pin" }]);
  assert.match(chosen, /^c\.pothole,-77\.04191,/);
  assert.match(plain, /^i,/);
  const back = decodeNotes([chosen, plain, "i.nosuchicon,-77.0,38.9,Newer icon"]);
  assert.deepEqual(back.map(noteIcon), ["pothole", "pin", "pin"]);
  assert.equal(back[1].icon, undefined);
  // Every icon has its name for the dialog and a screen reader.
  assert.deepEqual(Object.keys(NOTE_ICON_WORDS), Object.keys(NOTE_ICONS));
});

test("the notes keep the link under the server's limit, the most points and the longest words too", () => {
  const long = (text: string): RouteNote[] => Array.from({ length: MAX_NOTES }, (_, i) => ({ at: at(i * 100, 5), kind: "caution", text }));
  const points = Array.from({ length: 25 }, (_, i) => at(i * 997, i * 13));
  for (const words of ["x".repeat(NOTE_TEXT_MAX), "注意".repeat(NOTE_TEXT_MAX / 2), "a+b & 50% ; c,d =x #1"]) {
    const hash = encodePlan(points, "default", undefined, [], [], new Map(), "q", long(words));
    assert.ok(hash.length <= 2048 - 300, `${hash.length} for ${words.slice(0, 6)}`);
    assert.equal(notesFit(long(words)), false);
  }
  assert.equal(notesFit([caution, mural]), true);
  // What the address holds reads back as written.
  const odd: RouteNote = { ...caution, text: "a+b & 50% ; c,d =x #1 ~é 😀" };
  assert.equal(decodePlan(encodePlan([at(0), at(10)], "default", undefined, [], [], new Map(), "q", [odd])).notes[0].text, odd.text);
});

test("a note at a turn is put just before it, and the card leads with the turn", () => {
  // The review, 2026-11-10: a caution a few metres past the turn was said after it, or dropped.
  const atTurn: RouteNote = { at: at(503, 5), kind: "caution", text: "Busy crossing" };
  const model = rideModel(sampleRoute(), [], new Map(), new Map(), [atTurn, { ...mural, at: at(480, 5) }]);
  const turn = model.cues.find((c) => c.kind === "turn")!;
  const note = model.cues.find((c) => c.note?.text === "Busy crossing")!;
  assert.ok(Math.abs(turn.atM - 500) < 1);
  assert.equal(note.atM, turn.atM - 1);
  assert.ok(note.index < turn.index);
  assert.ok(NOTE_AT_TURN_M >= 20);
  // From well before, the card shows the turn: neither the caution at it nor a point of interest leads.
  assert.equal(nextAction(model, 300)?.kind, "turn");
  // A caution on its own leads.
  const alone = rideModel(sampleRoute(), [], new Map(), new Map(), [caution]);
  assert.equal(nextAction(alone, 600)?.note?.text, caution.text);
});
