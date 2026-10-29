// End-to-end encryption of a ride's live data (Stephen 2026-10-29: "Would E2E encryption be hard/worth it?", then
// "yes"): the secret in the link's fragment, the ride id and key from it, sealing, and what the phone now does in
// the server's place. Every ride has a key, and positions go as the phone has them (Stephen 2026-10-29: "Encrypted
// rides send GPS accurate numbers. All rides should have a key.").
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { LonLat } from "./geo.ts";
import { isRideLinkType, OTHER_MAX, PATH_MAX_POINTS, presetSecret, readRide, rideOf, sendAlert, sendPath, sendPosition } from "./rideGroup.ts";
import { roamLink, roamLinkFrom } from "./roam.ts";
import {
  isRideSecret,
  mergeAlerts,
  newRideSecret,
  openValue,
  padded,
  PAD_BYTES,
  rideSeal,
  sealValue,
  secretFrom,
  sealedSpot,
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
  const secret = newRideSecret();
  const mass = await rideOf(secret);
  assert.ok(mass?.seal, "sealed");
  assert.equal(mass.id, mass.seal.ride, "known to the server only by the id the secret gives");
  assert.equal(isRideLinkType("mass-ride"), true);
  assert.equal(isRideLinkType("group-ride"), true);
  assert.equal(isRideLinkType("commute"), false);
});

test("changing ride type keeps a link's secret, and makes a new one when the page's own moves between the two", () => {
  const make = () => "new";
  // Not a ride, or no change: as it was.
  assert.deepEqual(presetSecret("group-ride", "commute", "k", true, make), { secret: "k", own: true });
  assert.deepEqual(presetSecret("mass-ride", "mass-ride", "k", false, make), { secret: "k", own: false });
  // The page's own into a ride type from a plain plan: kept.
  assert.deepEqual(presetSecret("commute", "mass-ride", "k", true, make), { secret: "k", own: true });
  // The page's own between Group and Mass Ride: a new one, as they are different rides.
  assert.deepEqual(presetSecret("group-ride", "mass-ride", "k", true, make), { secret: "new", own: true });
  assert.deepEqual(presetSecret("mass-ride", "group-ride", "k", true, make), { secret: "new", own: true });
  // A link's own secret is kept whatever the type: it names the ride its sender leads.
  assert.deepEqual(presetSecret("group-ride", "mass-ride", "k", false, make), { secret: "k", own: false });
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

test("the longest dot, alert and path the phone sends stay in their padding and the server's bounds", async () => {
  const seal = (await rideSeal(newRideSecret()))!;
  // The most digits a position in the map's area has at 6 decimals, a negative longitude, the longest role.
  const far: LonLat = [-77.123457, 39.123457];
  assert.equal(padded("dot", { lon: far[0], lat: far[1], role: "participant" }).length, PAD_BYTES.dot);
  // Other's words at their longest, each character as long as JSON makes it (3 bytes, an escaped quote, a control
  // character or half an emoji, which the phone writes as a space or a replacement character).
  const sent: string[] = [];
  const fetcher = (async (_u: string, init?: RequestInit) => {
    sent.push(String((JSON.parse(String(init?.body)) as { sealed: string }).sealed));
    return new Response(JSON.stringify({ id: "a1" }), { status: 200 });
  }) as typeof fetch;
  for (const words of ["ጥ".repeat(OTHER_MAX), '"'.repeat(OTHER_MAX), "\u0001".repeat(OTHER_MAX), "\ud83d".repeat(OTHER_MAX), "x\ud83d\ude00".repeat(40)]) {
    const out = await sendAlert("https://x", seal.ride, "1".repeat(32), "group-ride", "other", `x${words}`, far, fetcher, seal);
    assert.ok(out.ok);
  }
  for (const text of sent) {
    assert.equal(text.length, Math.ceil(((12 + PAD_BYTES.alert + 16) * 4) / 3), "one pad's worth, whatever the words");
    assert.ok(text.length <= 1400, "core.ride_presence.SEALED_MAX");
  }
  // A full path, route and ridden path both at the server's most points: whole pads, under the server's bound.
  const full: LonLat[] = Array.from({ length: PATH_MAX_POINTS }, (_, i) => [-77.12345 - (i % 9) * 1e-5, 39.12345]);
  const pathBytes = padded("path", { route: full, trail: full }).length;
  assert.equal(pathBytes % PAD_BYTES.path, 0);
  assert.ok((await sealValue(seal, "path", { route: full, trail: full })).length <= 48 * 1024 - 256, "core.ride_presence.SEALED_PATH_MAX");
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

test("a sealed dot keeps the phone's exact position, to 6 decimals, and none outside the map's area is sent", () => {
  assert.deepEqual(sendable(SPOT), SPOT);
  assert.deepEqual(sendable([-76.6121937, 39.2903849]), [-76.612194, 39.290385]);
  assert.deepEqual(sendable([-77.5, 38.5]), [-77.5, 38.5]);
  assert.deepEqual(sealedSpot([-77.0000004, 38.9000006]), [-77, 38.900001]);
  assert.equal(sendable([-80, 38.5]), null);
  assert.equal(sendable([Number.NaN, 38.5]), null);
  assert.equal(sendable([-77, Number.POSITIVE_INFINITY]), null);
  // Two readings a metre apart stay two points; a repeat and a point outside the area are left out.
  const near: LonLat = [SPOT[0] + 0.00001, SPOT[1]];
  assert.deepEqual(sendableLine([SPOT, SPOT, near, [-80, 38.5], [-77.03, 38.9]]), [SPOT, near, [-77.03, 38.9]]);
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
  const on = await rideOf(s);
  assert.ok(on);
  const { id, seal } = on;
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
  // The dot that does not open (another key's, or none) is left out; the one that does is where the phone was.
  assert.deepEqual(got.dots, [{ lon: SPOT[0], lat: SPOT[1], age_s: 3, role: "sweep", leader: true }]);
  assert.equal(got.alerts.length, 1);
  assert.equal(got.alerts[0].label, "Other");
  assert.equal(got.alerts[0].text, "glass on the trail");
  assert.equal(got.alerts[0].count, 1);
  assert.ok(got.leaderPath);
  assert.equal(got.leaderPath.age_s, 9);
  assert.deepEqual(got.leaderPath.route, route);
  // The first stretch of the ridden path stays off it (PRIVATE_START_M); the rest is as the phone rode it.
  assert.deepEqual(got.leaderPath.trail, [[-77.0, 38.9], [-76.99, 38.91]]);
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

test("the phone never sends a position in plain: without a ride's key nothing is sent or read", async () => {
  // No ride by its points, its shared line or its Roam id: only by a secret, and a bad secret is none.
  assert.equal(await rideOf(null), null);
  assert.equal(await rideOf(undefined), null);
  assert.equal(await rideOf("bad"), null);
  const calls: string[] = [];
  const fetcher = (async (url: string | URL) => {
    calls.push(String(url));
    return new Response(JSON.stringify({ dots: [{ lon: SPOT[0], lat: SPOT[1], age_s: 1 }], alerts: [], id: "a1" }), { status: 200 });
  }) as typeof fetch;
  const ride = "f".repeat(64);
  const token = "1".repeat(32);
  assert.equal(await sendPosition("https://x", ride, token, SPOT, "sweep", fetcher, null), false);
  assert.equal(await sendPosition("https://x", ride, token, SPOT, "sweep", fetcher), false);
  assert.equal(await sendPath("https://x", ride, token, [SPOT, [-77.0, 38.9]], [SPOT, [-76.99, 38.91]], fetcher), false);
  assert.equal((await sendAlert("https://x", ride, token, "group-ride", "crash", "", SPOT, fetcher)).ok, false);
  assert.equal(await readRide("https://x", ride, token, fetcher), null);
  assert.deepEqual(calls, [], "no request at all");
  // And with the key, a dot in plain numbers on the server (an older page's) is not shown.
  const seal = (await rideSeal(newRideSecret()))!;
  assert.deepEqual(await readRide("https://x", seal.ride, token, fetcher, null, seal), { dots: [], alerts: [] });
  // Nothing in the phone's code posts a position, a path or an alert outside a sealed body.
  const group = readFileSync(new URL("./rideGroup.ts", import.meta.url), "utf8");
  assert.doesNotMatch(group, /lon: p\[0\], lat: p\[1\]/);
  assert.doesNotMatch(group, /route: thinLine\(route\), trail:/);
  assert.equal((group.match(/await post\(origin, `\/api\/rides\/\$\{ride\}\/(here|path|alerts)`, \{ token, sealed \}, send\)/g) ?? []).length, 3);
});

test("a ride link opened without a key gets a new key, the opener's own ride", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  // On opening: the link's secret, or a new one (never none).
  assert.match(app, /useState<string>\(\(\) => PLAN_SECRET \?\? newRideSecret\(\)\)/);
  assert.match(app, /const groupSecretOwn = useRef\(PLAN_SECRET === null\);/);
  // A link opened in the tab: its secret; without one, a new one, the page's own.
  assert.match(app, /const linked = own \? null : secretFrom\(window\.location\.hash\);\s*groupSecretOwn\.current = linked === null;\s*setGroupSecret\(linked \?\? newRideSecret\(\)\);/);
  // A broadcast or Roam link without one: the ride page makes its own.
  const group = readFileSync(new URL("../RideGroup.tsx", import.meta.url), "utf8");
  assert.match(group, /const \[ownSecret\] = useState\(newRideSecret\);\s*const rideSecret = \(broadcast \? broadcast\.secret : secret\) \?\? ownSecret;/);
  // That link, once the plan is written back, carries the new key.
  const s = newRideSecret();
  assert.equal(secretFrom(new URL(withSecret("https://example.org/#p=1,2;3,4&preset=group-ride", s)).hash), s);
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
  // A saved or kept route the page opens is the rider's own: a new secret; a link from outside: its own, or a new one.
  assert.equal((app.match(/ownHashOpen\.current = true;\s*window\.location\.hash = /g) ?? []).length, 2);
  assert.match(app, /roamLink\(window\.location\.origin, id, lead\.key, lead\.secret\)/);
  assert.match(app, /roamLink\(window\.location\.origin, roamBroadcast\.id, roamBroadcast\.lead, roamBroadcast\.secret\)/);
  assert.match(app, /withSecret\(encodePlan\([^\n]*isRideLinkType\(preset\) \? groupSecret : null\)/);
  assert.match(app, /withSecret\(linkToCopy\([^\n]*isRideLinkType\(preset\) \? groupSecret : null\)/);
  // The leader's answer is kept under the sealed ride's id, the one its page reads.
  assert.match(app, /if \(lead && sharedId\) \{\s*const on = await rideOf\(lead\.secret\);\s*if \(on\) leadConsent\(on\.id, lead\.token\);/);
  // A Group or Mass Ride plan carries the page's secret (Stephen 2026-10-29: "Mass rides should be encrypted too."),
  // and moving from one to the other makes a new one, so they are never the same ride.
  assert.match(app, /secret=\{rideGroupType !== null && !onShared \? groupSecret : null\}/);
  assert.match(app, /const next = presetSecret\(was, preset, s, groupSecretOwn\.current\);/);
  // A link opened in the tab brings its own ride type and secret: not a change of type that makes one.
  assert.match(app, /presetBefore\.current = plan\.preset;\s*setPreset\(plan\.preset\);/);
});
