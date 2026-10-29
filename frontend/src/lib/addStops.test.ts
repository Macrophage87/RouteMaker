/** v0.7.0 "Keep adding stops by search": Plan's search adds stops, Go's route sheet has "Add a stop". */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { LonLat } from "./geo.ts";
import { ViaMarks, addStopWhereShortest, stopAddedSaid } from "./pointKinds.ts";
import { applyPlace, choiceInForce, placeEffect } from "./geocode.ts";

const source = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const p = (lon: number, lat = 38.9): LonLat => [lon, lat];

test("with a route, a searched place is a stop where it adds the least distance", () => {
  const start = p(-77.0);
  const end = p(-77.1);
  const choice = choiceInForce(null, 2, false);
  assert.equal(choice, "via");
  assert.equal(placeEffect(2, choice), "via");
  const near = p(-77.05, 38.901);
  assert.deepEqual(applyPlace([start, end], near, choice), [start, near, end]);
  // Go's "Add a stop" puts it in the same place, and says which stop it is, and that Undo removes it.
  const marks = new ViaMarks();
  const added = addStopWhereShortest([start, end], near);
  assert.deepEqual(added.points, [start, near, end]);
  assert.equal(stopAddedSaid(added.points, added.index, marks.isVia, false, "Union Market"), "Stop 1, Union Market, added. Undo removes it.");
});

test("each result row offers 'Make this the destination' as an option of its own", () => {
  const search = source("../PlaceSearch.tsx");
  assert.match(search, /export const MAKE_DESTINATION = t\("Make this the destination"\);/);
  // Plan's Add a stop box offers it too (Plan streamline, 2026-10-17).
  // In a loop too, where it ends the loop (the owner, 2026-10-22: "Setting a destination should end the loop").
  assert.match(search, /const offersDestination = \(variant === "plan" \|\| variant === "add"\) && effect === "via";/);
  assert.match(search, /offered\.flatMap\(\(place\) => \[place, \{ destination: place \}\]\)/);
  // An option in the listbox, reached by the arrows and said with its place.
  assert.match(search, /aria-label=\{`\$\{MAKE_DESTINATION\}: \$\{item\.destination\.name\}`\}/);
  assert.match(search, /onClick=\{\(\) => pick\(item\.destination, "end"\)\}/);
  // Go's field adds a stop; Plan's From, To and Add a stop each pass their own choice.
  assert.match(search, /onPick\(place, as \?\? boxChoice \?\? \(variant === "stop" \? "via" : single \? "end" : choice\)\);/);
});

test("a destination picked from search on a loop ends the loop there, in one edit", () => {
  const app = source("../App.tsx");
  assert.match(app, /const endsLoop = loopVias && choice === "end" && pointsRef\.current\.length >= 1;/);
  assert.match(app, /commit\(next, endsLoop \? \{ \.\.\.ride, dials: withLoop\(ride\.dials, false\) \} : undefined\);/);
  assert.match(app, /if \(endsLoop\) announce\(LOOP_ENDED_BY_SEARCH\);/);
});

test("Go's route sheet keeps one 'Add a stop' field, under the route card, with Best order, never during a ride", () => {
  const go = source("../app/Go.tsx");
  assert.match(go, /<PlaceSearch variant="stop"/);
  assert.doesNotMatch(go, /addStop/);
  // The edit-route redesign (Stephen 2026-10-18, "Keep stop box in Go"): the field stays one tap away, under the
  // route card, whose Edit route holds the rest (change the start or the destination, remove a stop).
  const panel = source("../app/RoutePanel.tsx");
  assert.match(panel, /\{!go\.peek && go\.routeCard\}\s*\{!go\.peek && go\.addStop\}/);
  assert.match(source("../App.tsx"), /addStop: goStops \? \(\s*<GoAddStop/);
  assert.match(source("../App.tsx"), /routeCard:\s*!riding && points\.length >= 2 \? \(\s*<GoRouteCard/);
  assert.match(source("../App.tsx"), /onEdit=\{\(opener\) => openView\("points", opener\)\}/);
  assert.match(go, /\{orderShown && \(\s*<button[^>]*onClick=\{onBestOrder\}/);
  const app = source("../App.tsx");
  assert.match(app, /const goStops = mode === "go" && !riding && points\.length >= 2 && !twoPointsOnly\(preset\) && !isMassRide\(preset\);/);
  // One edit, so Undo removes it; the route follows at once, as every Go edit does.
  assert.match(app, /const added = addStopWhereShortest\(current, VIA_MARKS\.named\(\[point\[0\], point\[1\]\], name\), loop\);\s*setNotice\(null\);\s*commit\(added\.points\);/);
  // A place's card (water, a restroom, food: lib/stopCard.ts) offers Add as stop once there is a route.
  assert.match(app, /if \(!goStops\) return \{ text: ROUTE_HERE, run: \(\) => goToLettered\(point, name\) \};/);
});

test("Go's Add a stop is '+ Add a stop', which opens the field with the focus in it; its hint is said, not shown (the owner's P1)", () => {
  const go = source("../app/Go.tsx");
  const stop = go.slice(go.indexOf("export function GoAddStop"), go.indexOf("export function GoRouteCard"));
  assert.match(stop, /<button ref=\{opener\} type="button" className="link go-add-stop-open" aria-expanded=\{open\} aria-controls=\{fieldId\} onClick=\{\(\) => setOpen\(!open\)\}>\s*<Icon name="plus" size=\{18\} \/>\s*\{t\("Add a stop"\)\}/);
  assert.match(stop, /useEffect\(\(\) => \{\s*if \(open\) input\.current\?\.focus\(\);\s*\}, \[open\]\);/);
  assert.match(stop, /<div id=\{fieldId\} className="go-add-stop-field" hidden=\{!open\}>\s*\{open && \(\s*<PlaceSearch variant="stop"[^\n]*inputRef=\{input\} onDismiss=\{close\}/);
  // A pick, or Escape on the empty box, puts it away with the focus back on the button.
  assert.match(stop, /const close = \(\) => \{\s*setOpen\(false\);\s*opener\.current\?\.focus\(\);\s*\};/);
  // Go's boxes say what a pick does to a screen reader only (Where to?'s already did): Add a stop's, the start's,
  // Home's and Favorites'. Plan's own Find a place keeps its line.
  const search = source("../PlaceSearch.tsx");
  assert.match(search, /className=\{variant === "go" \? "visually-hidden go-from" : planBox \? \(full && planBox === "add" \? "hint" : "visually-hidden"\) : variant === "plan" \? "hint" : "visually-hidden"\}/);
  assert.match(search, /aria-describedby=\{`\$\{id\}-hint`\}/);
});

test("under a route, Go's Where to? and place chips fold into one New destination row (the owner's P1)", () => {
  const go = source("../app/Go.tsx");
  assert.match(go, /\{routeShown && \(\s*<button type="button" className="secondary go-new-destination" aria-expanded=\{newOpen\} aria-controls=\{newId\} onClick=\{\(\) => setNewOpen\(!newOpen\)\}>/);
  assert.match(go, /const whereShown = !routeShown \|\| newOpen;/);
  assert.match(go, /<div id=\{newId\} className="go-new-body" hidden=\{!whereShown\}>\s*<PlaceSearch variant="go"/);
  // A place picked folds it again.
  assert.match(go, /const pickWhereTo = \(place: Place\) => \{\s*setNewOpen\(false\);\s*onPick\(place\);\s*\};/);
});
