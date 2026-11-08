/** The ride screen's walks and stations (Stephen, 2026-11-08, a walk and Metro ride): arrows on walks, the exit said. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");

test("a walk's next turn shows with its arrow, as a ride's: before the line and after it", () => {
  assert.match(ride, /<CueShape shape=\{cue\.movement \? arrowFor\(cue\) : "cross"\} \/>/);
  assert.match(ride, /<WalkTurnCard model=\{approach\.walk\} state=\{tripRef\.current\.walk \?\? null\} weak=\{!!gps\} \/>/);
  assert.match(ride, /<WalkTurnCard model=\{onwardPart\.model\} state=\{onward\?\.walk \?\? null\} weak=\{!!gps\} \/>/);
});

test("off a train, the exit is said once and shown till the walk is under way", () => {
  assert.match(ride, /part\.kind === "walk" && isRailPart\(onwardParts\[i - 1\]\) \? exitAt\(METRO_EXITS, part\.model\.coordinates\[0\]\)/);
  assert.match(ride, /const exit = out\.state\.index !== state\.index \? onwardExits\[out\.state\.index\] : null;\s*if \(exit\) notify\(exit\);/);
  assert.match(ride, /\{exitShown && <p className="cue-text">\{onwardExit\}<\/p>\}/);
});
