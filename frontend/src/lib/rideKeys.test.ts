// The page's own Group and Mass Ride secrets (lib/rideGroup.ts planSecrets, isOwnSecret) and the leader's prepared
// key, as the page wires them (App.tsx): each plan is its own ride, and a ride's end makes the next one new.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { LonLat } from "./geo.ts";
import * as rideGroup from "./rideGroup.ts";
import { newRideSecret } from "./rideSeal.ts";

const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
const { OWN_SECRETS_KEY, isOwnSecret, markOwnSecret, planSecrets, ridePlanKey } = rideGroup;
const A: LonLat[] = [[-77.03, 38.9], [-77.0, 38.95]];
const B: LonLat[] = [[-77.03, 38.9], [-76.9, 39.0]];

function memoryStore() {
  const kept = new Map<string, string>();
  return { getItem: (k: string) => kept.get(k) ?? null, setItem: (k: string, v: string) => void kept.set(k, v), kept };
}

test("two Group Ride plans made in one tab are different rides, and the same plan again is the same ride", () => {
  const secrets = planSecrets();
  const a = secrets.secretFor(ridePlanKey("group-ride", A), false);
  secrets.keep(ridePlanKey("group-ride", A), a);
  const b = secrets.secretFor(ridePlanKey("group-ride", B), false);
  secrets.keep(ridePlanKey("group-ride", B), b);
  assert.notEqual(a, b);
  assert.equal(secrets.secretFor(ridePlanKey("group-ride", A), false), a, "copied again, the same link");
  // The same points as another ride type are another ride.
  assert.notEqual(secrets.secretFor(ridePlanKey("mass-ride", A), false), a);
});

test("Clear starts a new ride: no earlier plan's secret comes back", () => {
  const secrets = planSecrets();
  const a = secrets.secretFor(ridePlanKey("group-ride", A), false);
  secrets.keep(ridePlanKey("group-ride", A), a);
  const cleared = secrets.secretFor(ridePlanKey("group-ride", []), true);
  assert.notEqual(cleared, a);
  assert.notEqual(secrets.secretFor(ridePlanKey("group-ride", A), false), a);
});

test("a ride's end gives a new secret, and no plan that had the ridden one keeps it", () => {
  const secrets = planSecrets();
  const ridden = secrets.secretFor(ridePlanKey("group-ride", A), false);
  secrets.keep(ridePlanKey("group-ride", A), ridden);
  secrets.keep(ridePlanKey("group-ride", B), ridden);
  const next = secrets.renew(ridden);
  assert.notEqual(next, ridden);
  assert.notEqual(secrets.secretFor(ridePlanKey("group-ride", A), false), ridden);
  assert.notEqual(secrets.secretFor(ridePlanKey("group-ride", B), false), ridden);
});

test("a secret the page made is still its own after a reload in the same tab; a link's is not; the tab keeps no secret", () => {
  const store = memoryStore();
  const mine = newRideSecret();
  const linked = newRideSecret();
  markOwnSecret(mine, store);
  assert.equal(isOwnSecret(mine, store), true);
  assert.equal(isOwnSecret(linked, store), false);
  assert.ok(!store.kept.get(OWN_SECRETS_KEY)!.includes(mine), "only a digest is kept");
  // No storage (a private window): taken as a link's, as before.
  assert.equal(isOwnSecret(mine, null), false);
});

test("the page gives each plan of its own its own secret, and Clear a new one, but keeps a ride's while it goes", () => {
  assert.match(app, /const PLAN_SECRET_OWN = PLAN_SECRET === null \|\| isOwnSecret\(PLAN_SECRET\);/);
  assert.match(app, /const groupSecretOwn = useRef\(PLAN_SECRET_OWN\);/);
  assert.match(
    app,
    /if \(riding\) return;\s*const empty = points\.length === 0;\s*if \(empty\) groupSecretOwn\.current = true;\s*if \(groupSecretOwn\.current\) setGroupSecret\(ownSecrets\.current!\.secretFor\(ridePlanKey\(preset, points\), empty\)\);\s*\/\/[^\n]*\n\s*\}, \[points\]\);/,
  );
  assert.match(app, /ownSecrets\.current!\.keep\(ridePlanKey\(preset, secretPlan\.current\), groupSecret\);\s*markOwnSecret\(groupSecret\);\s*\}, \[groupSecret, preset\]\);/);
  // A link opened in the tab: its own secret, and no plan before it keeps one.
  assert.match(app, /groupSecretOwn\.current = linked === null;\s*setGroupSecret\(linked \?\? newRideSecret\(\)\);\s*ownSecrets\.current!\.forget\(\);/);
});

test("a ride link sent whose line was not kept still gives the next ride shared a new leader key and secret", () => {
  assert.match(
    app,
    /if \(done !== "failed" && done !== "cancelled"\) said = SHARED_INPUTS_ONLY;\s*\/\/[^\n]*\n\s*if \(ride && done === "shared" && lead && lead === leadPrep\.current\) prepareLead\(\);/,
  );
  // Roam's broadcast likewise, when Roam ended while the sheet was open.
  assert.match(app, /if \(!roamingNow\.current\) \{\s*prepareLead\(\);\s*return "";\s*\}/);
});
