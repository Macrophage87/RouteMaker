// End-to-end encryption of a ride's live data (Stephen 2026-10-29: "Would E2E encryption be hard/worth it?", then
// "yes"): the secret in the link's fragment, the ride id and key from it, sealing, and what the phone now does in
// the server's place.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { LonLat } from "./geo.ts";
import { isRideLinkType, readRide, rideOf, sendAlert, sendPath, sendPosition } from "./rideGroup.ts";
import { roamLink, roamLinkFrom } from "./roam.ts";
import {
  gridded,
  isRideSecret,
  mergeAlerts,
  newRideSecret,
  openValue,
  padded,
  PAD_BYTES,
  rideSeal,
  sealValue,
  secretFrom,
  sendable,
  sendableLine,
  withSecret,
  withoutSecret,
  type OpenedAlert,
} from "./rideSeal.ts";

const SPOT: LonLat = [-77.03651, 38.89768];

test("a ride's secret is 32 random bytes in 43 link-safe characters, different each time", () => {
  const a = newRideSecret();
  const b = newRideSecret();
  assert.ok(isRideSecret(a) && isRideSecret(b));
  assert.notEqual(a, b);
  assert.match(a, /^[A-Za-z0-9_-]{43}$/);
});

test("the secret rides in the fragment only, replacing any the link had, and is read from there only", () => {
  const s = newRideSecret();
  const link = withSecret("https://example.org/?route=abc#p=1,2;3,4&preset=group-ride", s);
  assert.equal(link, `https://example.org/?route=abc#p=1,2;3,4&preset=group-ride&k=${s}`);
  const other = newRideSecret();
  assert.equal(withSecret(link, other), `https://example.org/?route=abc#p=1,2;3,4&preset=group-ride&k=${other}`);
  assert.equal(withSecret("https://example.org/", s), `https://example.org/#k=${s}`);
  assert.equal(withSecret("#preset=group-ride", s), `#preset=group-ride&k=${s}`);
  assert.equal(withSecret("https://example.org/#a=1", null), "https://example.org/#a=1");
  assert.equal(secretFrom(new URL(link).hash), s);
  assert.equal(secretFrom("#k=short"), null);
  assert.equal(secretFrom(""), null);
});

test("a Mass Ride link with a secret is sealed end to end, as a Group Ride's is", async () => {
  const points: LonLat[] = [
    [-77.0365, 38.8977],
    [-77.0091, 38.8899],
  ];
  const secret = newRideSecret();
  const mass = await rideOf({ type: "mass-ride", points, secret });
  assert.ok(mass.seal, "sealed");
  assert.equal(mass.id, mass.seal.ride, "known to the server only by the id the secret gives");
  const plain = await rideOf({ type: "mass-ride", points });
  assert.equal(plain.seal, null, "no secret: by its points, as before");
  assert.notEqual(plain.id, mass.id);
  assert.equal(isRideLinkType("mass-ride"), true);
  assert.equal(isRideLinkType("group-ride"), true);
  assert.equal(isRideLinkType("commute"), false);
});

test("a ride link without a leader of its own carries no secret", () => {
  const s = newRideSecret();
  assert.equal(withoutSecret(`https://example.org/#p=1,2&k=${s}&ride=1`), "https://example.org/#p=1,2&ride=1");
  assert.equal(withoutSecret("https://example.org/"), "https://example.org/");
});

test("each value is padded to its kind's size, so the sealed length says nothing of role, kind or words", async () => {
  const seal = (await rideSeal(newRideSecret()))!;
  assert.equal(padded("dot", { lon: 1, lat: 2, role: "participant" }).length, PAD_BYTES.dot);
  const lengths = new Set<number>();
  for (const role of ["participant", "lead", "sweep", "corker"]) lengths.add((await sealValue(seal, "dot", { lon: SPOT[0], lat: SPOT[1], role })).length);
  assert.equal(lengths.size, 1);
  const alerts = new Set<number>();
  for (const [kind, text] of [["crash", ""], ["other", "x"], ["other", "ጥ".repeat(80)]]) alerts.add((await sealValue(seal, "alert", { kind, text, lon: SPOT[0], lat: SPOT[1] })).length);
  assert.equal(alerts.size, 1);
  // Still opens to the value itself.
  const text = await sealValue(seal, "alert", { kind: "crash", text: "", lon: 1, lat: 2 });
  assert.deepEqual(await openValue(seal, "alert", text), { kind: "crash", text: "", lon: 1, lat: 2 });
  // The longest path the page sends fits the server's bound (core.ride_presence.SEALED_PATH_MAX).
  const line: LonLat[] = Array.from({ length: 600 }, (_, i) => [-77.12345 + i * 1e-5, 38.12345]);
  assert.ok((await sealValue(seal, "path", { route: line, trail: line })).length <= 48 * 1024 - 256);
});

test("the ride id comes from the secret one way, and is the server's ride id shape", async () => {
  const s = newRideSecret();
  const a = await rideSeal(s);
  const b = await rideSeal(s);
  const c = await rideSeal(newRideSecret());
  assert.ok(a && b && c);
  assert.match(a.ride, /^[0-9a-f]{64}$/);
  assert.equal(a.ride, b.ride);
  assert.notEqual(a.ride, c.ride);
  assert.equal(await rideSeal("not a secret"), null);
});

test("sealed text opens with the same ride's key, as the same kind, and nothing else", async () => {
  const s = newRideSecret();
  const seal = (await rideSeal(s))!;
  const again = (await rideSeal(s))!;
  const other = (await rideSeal(newRideSecret()))!;
  const text = await sealValue(seal, "dot", { lon: SPOT[0], lat: SPOT[1], role: "sweep" });
  assert.match(text, /^[A-Za-z0-9_-]+$/);
  assert.ok(!text.includes("77.03") && !text.includes("sweep"));
  assert.deepEqual(await openValue(again, "dot", text), { lon: SPOT[0], lat: SPOT[1], role: "sweep" });
  // Another ride's key, or the same text passed off as an alert, or a changed character: nothing.
  assert.equal(await openValue(other, "dot", text), null);
  assert.equal(await openValue(seal, "alert", text), null);
  const flipped = text.slice(0, 20) + (text[20] === "A" ? "B" : "A") + text.slice(21);
  assert.equal(await openValue(seal, "dot", flipped), null);
  assert.equal(await openValue(seal, "dot", "!!"), null);
  assert.equal(await openValue(seal, "dot", 7), null);
  // A fresh nonce each time: the same dot twice is two different texts.
  assert.notEqual(await sealValue(seal, "dot", { a: 1 }), await sealValue(seal, "dot", { a: 1 }));
});

test("positions go on the server's 20 m grid before sealing, and none outside the map's area is sent", () => {
  // core.ride_presence.rounded's answers for the same points.
  assert.deepEqual(gridded(SPOT), [-77.036589, 38.897612]);
  assert.deepEqual(gridded([-76.61219, 39.29038]), [-76.612165, 39.290436]);
  assert.deepEqual(sendable([-77.5, 38.5]), [-77.499998, 38.499933]);
  assert.equal(sendable([-80, 38.5]), null);
  assert.equal(sendable([Number.NaN, 38.5]), null);
  const line = sendableLine([SPOT, [SPOT[0] + 0.00001, SPOT[1]], [-80, 38.5], [-77.03, 38.9]], true);
  assert.deepEqual(line, [[-77.036589, 38.897612], gridded([-77.03, 38.9])]);
  assert.deepEqual(sendableLine([SPOT, [-80, 38.5]], false), [SPOT]);
});

const alert = (over: Partial<OpenedAlert>): OpenedAlert => ({ id: "a", kind: "crash", text: "", lon: SPOT[0], lat: SPOT[1], age_s: 0, mine: false, ...over });

test("the same issue near the same spot within 2 minutes is one alert, as the server merged plain ones", () => {
  const merged = mergeAlerts([alert({ id: "new", age_s: 10 }), alert({ id: "old", age_s: 100 }), alert({ id: "far", age_s: 50, lat: SPOT[1] + 0.01 })]);
  assert.deepEqual(
    merged.map((a) => [a.id, a.count, a.age_s]),
    [["old", 2, 10], ["far", 1, 50]],
  );
  // Another kind, other words for Other, or past 2 minutes from the latest report: apart.
  assert.equal(mergeAlerts([alert({ id: "1" }), alert({ id: "2", kind: "mechanical" })]).length, 2);
  assert.equal(mergeAlerts([alert({ id: "1", kind: "other", text: "glass" }), alert({ id: "2", kind: "other", text: "dog" })]).length, 2);
  assert.equal(mergeAlerts([alert({ id: "1", kind: "other", text: "glass" }), alert({ id: "2", kind: "other", text: "glass", age_s: 30 })]).length, 1);
  assert.equal(mergeAlerts([alert({ id: "1", age_s: 200 }), alert({ id: "2", age_s: 10 })]).length, 2);
  // One's own stays apart, so Clear clears only that.
  assert.equal(mergeAlerts([alert({ id: "1" }), alert({ id: "2", mine: true })]).length, 2);
});

/** A server in memory that keeps what it is sent, as core.ride_presence keeps sealed values. */
function fakeServer() {
  const sent: { path: string; body: Record<string, unknown> }[] = [];
  const fetcher = (async (url: string | URL, init?: RequestInit) => {
    const path = String(url).replace(/^https:\/\/x/, "");
    if (init?.method === "POST") {
      const body = JSON.parse(String(init.body)) as Record<string, unknown>;
      sent.push({ path, body });
      const answer = path.endsWith("/alerts") ? { id: `al${sent.length}`, sealed: body.sealed, age_s: 0, mine: true } : { ok: true };
      return new Response(JSON.stringify(answer), { status: 200 });
    }
    const dot = sent.find((s) => s.path.endsWith("/here"))?.body.sealed;
    const path2 = sent.find((s) => s.path.endsWith("/path"))?.body.sealed;
    const alerts = sent.filter((s) => s.path.endsWith("/alerts")).map((s, i) => ({ id: `al${i}`, sealed: s.body.sealed, age_s: 5, mine: false }));
    return new Response(JSON.stringify({ dots: dot ? [{ sealed: dot, age_s: 3, leader: true }, { sealed: "AAAAAAAAAAAAAAAAAAAAAAAAAAAA", age_s: 1 }] : [], alerts, leader_path: path2 ? { sealed: path2, age_s: 9 } : undefined }), { status: 200 });
  }) as typeof fetch;
  return { sent, fetcher };
}

test("on a sealed ride the server is sent no position, role, route or words, and riders read them back", async () => {
  const s = newRideSecret();
  const { id, seal } = await rideOf({ broadcast: { id: "f".repeat(32) }, secret: s });
  assert.ok(seal);
  assert.equal(id, seal.ride);
  const { sent, fetcher } = fakeServer();
  const token = "1".repeat(32);
  assert.ok(await sendPosition("https://x", id, token, SPOT, "sweep", fetcher, seal));
  const route: LonLat[] = [SPOT, [-77.03, 38.9], [-77.02, 38.91]];
  const trail: LonLat[] = [SPOT, [-77.0, 38.9], [-76.99, 38.91]];
  assert.ok(await sendPath("https://x", id, token, route, trail, fetcher, seal));
  const out = await sendAlert("https://x", id, token, "group-ride", "other", "glass on the trail", SPOT, fetcher, seal);
  assert.ok(out.ok && out.alert.mine && out.alert.text === "glass on the trail");
  for (const { body } of sent) {
    assert.deepEqual(Object.keys(body).sort(), ["sealed", "token"]);
    const raw = JSON.stringify(body);
    for (const leak of ["77.0", "38.8", "38.9", "sweep", "glass", "other"]) assert.ok(!raw.includes(leak), leak);
  }
  const reader = (await rideSeal(s))!;
  const got = await readRide("https://x", id, "2".repeat(32), fetcher, "a".repeat(32), reader);
  assert.ok(got);
  // The dot that does not open (another key's, or none) is left out.
  assert.deepEqual(got.dots, [{ lon: -77.036589, lat: 38.897612, age_s: 3, role: "sweep", leader: true }]);
  assert.equal(got.alerts.length, 1);
  assert.equal(got.alerts[0].label, "Other");
  assert.equal(got.alerts[0].text, "glass on the trail");
  assert.equal(got.alerts[0].count, 1);
  assert.ok(got.leaderPath);
  assert.equal(got.leaderPath.age_s, 9);
  assert.deepEqual(got.leaderPath.route, route);
  // The first stretch of the ridden path stays off it (PRIVATE_START_M), and it is on the grid.
  assert.deepEqual(got.leaderPath.trail, [gridded([-77.0, 38.9]), gridded([-76.99, 38.91])]);
  // Without the key: nothing opens.
  const stranger = (await rideSeal(newRideSecret()))!;
  const none = await readRide("https://x", id, "3".repeat(32), fetcher, null, stranger);
  assert.deepEqual(none, { dots: [], alerts: [] });
});

test("a sealed alert of a kind the ride type does not send, or Other with no words, is not sent", async () => {
  const seal = (await rideSeal(newRideSecret()))!;
  const { sent, fetcher } = fakeServer();
  assert.equal((await sendAlert("https://x", seal.ride, "1".repeat(32), "group-ride", "spread", "", SPOT, fetcher, seal)).ok, false);
  assert.equal((await sendAlert("https://x", seal.ride, "1".repeat(32), "group-ride", "other", "  ", SPOT, fetcher, seal)).ok, false);
  assert.equal((await sendPosition("https://x", seal.ride, "1".repeat(32), [-80, 38], "participant", fetcher, seal)), false);
  assert.equal(sent.length, 0);
});

test("a link without a secret is the ride it always was, in plain numbers", async () => {
  const before = await rideOf({ broadcast: { id: "f".repeat(32) } });
  const roam = await rideOf({ broadcast: { id: "f".repeat(32), roam: true } });
  const group = await rideOf({ type: "group-ride", points: [SPOT, [-77.0, 38.9]] });
  for (const r of [before, roam, group]) {
    assert.equal(r.seal, null);
    assert.match(r.id, /^[0-9a-f]{64}$/);
  }
  assert.notEqual(before.id, roam.id);
  // A bad secret is no secret.
  assert.equal((await rideOf({ broadcast: { id: "f".repeat(32) }, secret: "bad" })).id, before.id);
});

test("a Roam broadcast's link carries its secret, and an older one without it still opens", () => {
  const s = newRideSecret();
  const link = roamLink("https://example.org", "a".repeat(32), "b".repeat(32), s);
  assert.deepEqual(roamLinkFrom(new URL(link).hash), { id: "a".repeat(32), lead: "b".repeat(32), secret: s });
  assert.deepEqual(roamLinkFrom(`#roam=${"a".repeat(32)}&lead=${"b".repeat(32)}`), { id: "a".repeat(32), lead: "b".repeat(32), secret: null });
});

test("the page puts each ride's secret in its links: Share ride, Broadcast, Roam and a Group Ride plan", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /lead \? withSecret\(asRideLink\(now!\.link, lead\.key\), lead\.secret\) : withoutSecret\(asRideLink\(now!\.link\)\)/);
  // The secret of a plan kept over a sign-in or another page is read from the plan as opened, not the bare address.
  assert.match(app, /const OPENED_HASH = planToOpen\(tabSession\(\), window\.location\.hash\);\s*const initialPlan = decodePlan\(OPENED_HASH\);/);
  assert.match(app, /const PLAN_SECRET = SHARED_RIDE \|\| ROAM_FOLLOW \? null : secretFrom\(OPENED_HASH\);/);
  // A saved or kept route the page opens is the rider's own: a new secret; a link from outside: its own, or none.
  assert.equal((app.match(/ownHashOpen\.current = true;\s*window\.location\.hash = /g) ?? []).length, 2);
  assert.match(app, /setGroupSecret\(own \? newRideSecret\(\) : secretFrom\(window\.location\.hash\)\);/);
  assert.match(app, /roamLink\(window\.location\.origin, id, lead\.key, lead\.secret\)/);
  assert.match(app, /roamLink\(window\.location\.origin, roamBroadcast\.id, roamBroadcast\.lead, roamBroadcast\.secret\)/);
  assert.match(app, /withSecret\(encodePlan\([^\n]*isRideLinkType\(preset\) \? groupSecret : null\)/);
  assert.match(app, /withSecret\(linkToCopy\([^\n]*isRideLinkType\(preset\) \? groupSecret : null\)/);
  // The leader's answer is kept under the sealed ride's id, the one its page reads.
  assert.match(app, /leadConsent\(\(await rideOf\(\{ broadcast: \{ id: sharedId \}, secret: lead\.secret \}\)\)\.id, lead\.token\)/);
  // A Group or Mass Ride plan carries the page's secret (Stephen 2026-10-29: "Mass rides should be encrypted too."),
  // and moving from one to the other makes a new one, so they are never the same ride.
  assert.match(app, /secret=\{rideGroupType !== null && !onShared \? groupSecret : null\}/);
  assert.match(app, /if \(isRideLinkType\(preset\) && was !== preset\)/);
  assert.match(app, /if \(s !== null && \(!isRideLinkType\(was\) \|\| !groupSecretOwn\.current\)\) return s;/);
});
