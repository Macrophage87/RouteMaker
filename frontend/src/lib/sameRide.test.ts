// "Same ride or a new one?" (SameRideDialog; lib/rideGroup.ts asksSameRide): a Group or Mass Ride plan's link that
// went out more than 12 hours ago is asked about before it goes out again or its ride starts.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as rideGroup from "./rideGroup.ts";
import { newRideSecret } from "./rideSeal.ts";

const source = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const HOUR = 3600_000;

function memoryStore() {
  const kept = new Map<string, string>();
  return { getItem: (k: string) => kept.get(k) ?? null, setItem: (k: string, v: string) => void kept.set(k, v), kept };
}

test("a Group Ride plan's link copied again a day later asks whether it is the same ride; within 12 hours it does not", () => {
  const { asksSameRide, markRideSent, SAME_RIDE_ASK_MS } = rideGroup;
  assert.equal(SAME_RIDE_ASK_MS, 12 * HOUR);
  const store = memoryStore();
  const secret = newRideSecret();
  const monday = Date.UTC(2026, 10, 2, 18);
  // Never sent: nothing to ask.
  assert.equal(asksSameRide(secret, monday, store), false);
  markRideSent(secret, monday, false, store);
  assert.equal(asksSameRide(secret, monday + 11 * HOUR, store), false);
  // Copied again the same evening keeps Monday's time: it is when the link first went out.
  markRideSent(secret, monday + 2 * HOUR, false, store);
  assert.equal(asksSameRide(secret, monday + 13 * HOUR, store), true);
  assert.equal(asksSameRide(secret, monday + 7 * 24 * HOUR, store), true);
  // Another secret (a new ride) is not asked about.
  assert.equal(asksSameRide(newRideSecret(), monday + 7 * 24 * HOUR, store), false);
});

test("the organiser saying Same ride is not asked again for 12 hours; only a digest and a time are kept", () => {
  const { asksSameRide, markRideSent, RIDE_SENT_KEY } = rideGroup;
  const store = memoryStore();
  const secret = newRideSecret();
  const monday = Date.UTC(2026, 10, 2, 18);
  markRideSent(secret, monday, false, store);
  const thursday = monday + 3 * 24 * HOUR;
  markRideSent(secret, thursday, true, store);
  assert.equal(asksSameRide(secret, thursday + HOUR, store), false);
  assert.equal(asksSameRide(secret, thursday + 13 * HOUR, store), true);
  const kept = store.kept.get(RIDE_SENT_KEY)!;
  assert.ok(!kept.includes(secret));
  assert.deepEqual(Object.values(JSON.parse(kept)), [thursday]);
  // No storage (a private window): never asked.
  markRideSent(secret, monday, false, null);
  assert.equal(asksSameRide(secret, thursday, null), false);
});


test("after New ride the next Share ride or Broadcast goes out with a new leader key and secret, and the plan with a new key", async () => {
  const { asksSameRide, markRideSent, newRide, planSecrets, rideLeadFor, ridePlanKey } = rideGroup;
  const { asRideLink, withSharedId } = await import("./sharedRoutes.ts");
  const { secretFrom, withSecret } = await import("./rideSeal.ts");
  const store = memoryStore();
  const monday = Date.UTC(2026, 10, 2, 18);
  const saturday = monday + 5 * 24 * HOUR;
  type Lead = { token: string; key: string; secret: string };
  const lead = (key: string): Lead => ({ token: `t-${key}`, key, secret: newRideSecret() });
  // Monday: Share ride for this line went out under `monday`'s leader; Roam broadcast a leader of its own.
  const mondayLead = lead("a".repeat(32));
  const roamLead = lead("c".repeat(32));
  const prepared = lead("b".repeat(32));
  const leads = new Map<string, Lead>([["line-1", mondayLead], ["roam|r1", roamLead]]);
  let sent: { lead: Lead | null } | null = { lead: mondayLead };
  markRideSent(mondayLead.secret, monday, false, store);
  const secrets = planSecrets();
  const planKey = ridePlanKey("group-ride", [[-77.03, 38.9], [-77.0, 38.95]]);
  const planSecret = secrets.secretFor(planKey, false);
  secrets.keep(planKey, planSecret);
  // Saturday's Broadcast would reuse Monday's leader: asked first.
  assert.equal(rideLeadFor(sent, "line-1", leads, prepared), mondayLead);
  assert.equal(rideLeadFor(null, "line-1", leads, prepared), mondayLead);
  assert.equal(asksSameRide(rideLeadFor(sent, "line-1", leads, prepared)!.secret, saturday, store), true);
  // New ride: the link sent and the line's leader are dropped, the plan gets a new key.
  sent = null;
  const fresh = newRide(leads, secrets, planSecret);
  const next = rideLeadFor(sent, "line-1", leads, prepared)!;
  assert.equal(next, prepared);
  assert.equal(leads.get("roam|r1"), roamLead, "Roam's leader goes with Roam");
  assert.notEqual(fresh, planSecret);
  assert.notEqual(secrets.secretFor(planKey, false), planSecret);
  assert.equal(asksSameRide(next.secret, saturday, store), false);
  // The link as shareRoute builds it carries the new leader and secret, not Monday's.
  const base = withSharedId("https://routemaker.example/#p=-77.03,38.9;-77,38.95&preset=group-ride&v=2", "0123456789abcdef0123456789abcdef");
  const link = new URL(withSecret(asRideLink(base, next.key), next.secret));
  assert.equal(secretFrom(link.hash), prepared.secret);
  assert.notEqual(secretFrom(link.hash), mondayLead.secret);
  assert.doesNotMatch(link.hash, new RegExp(mondayLead.key));
  assert.equal(secretFrom(new URL(withSecret(base, fresh)).hash), fresh);
});

test("after New ride a plain Start ride goes under the new key, not the leader key an earlier Share ride went out with", () => {
  const { asksSameRide, markRideSent, newRide, planSecrets, rideSecretOf, sharedAfterRide } = rideGroup;
  const store = memoryStore();
  const monday = Date.UTC(2026, 10, 2, 18);
  const saturday = monday + 5 * 24 * HOUR;
  const mondaySecret = newRideSecret();
  const planSecret = newRideSecret();
  // Monday's Share ride: this page leads the line under its leader's key and secret.
  const led = { answer: "route", ride: true, own: true, id: "line-1", lead: "a".repeat(32), secret: mondaySecret };
  markRideSent(mondaySecret, monday, false, store);
  assert.equal(rideSecretOf(led, planSecret), mondaySecret);
  assert.equal(asksSameRide(rideSecretOf(led, planSecret)!, saturday, store), true, "Start ride asks first");
  // New ride: the led line is dropped, and the ride goes under the plan's new key.
  const fresh = newRide(new Map(), planSecrets(), planSecret);
  const after = sharedAfterRide(led);
  assert.equal(after, null);
  assert.equal(rideSecretOf(after, fresh), fresh);
  assert.notEqual(rideSecretOf(after, fresh), mondaySecret);
  // A link someone else shared, opened here, is theirs: kept, and its ride is theirs.
  const received = { ...led, own: false, secret: newRideSecret() };
  assert.equal(sharedAfterRide(received), received);
  assert.equal(rideSecretOf(sharedAfterRide(received), fresh), received.secret);
});

test("Copy link, Share, Share ride, Broadcast and Start ride ask first; New ride makes new keys, going back sends nothing", () => {
  const app = source("../App.tsx");
  // A plan's link by the plan's key; a ride link by the leader's it would go out with.
  assert.match(app, /const lead = ride && followedInRide\(\) === null \? rideLeadNow\(\) : null;/);
  assert.match(
    app,
    /const asked = ride\s*\? lead && asksSameRide\(lead\.secret, now\)\s*\? lead\.secret\s*: null\s*: led && led !== groupSecret && asksSameRide\(led, now\)\s*\? led\s*: !riding && isRideLink\(preset, points\) && groupSecretOwn\.current && asksSameRide\(groupSecret, now\)\s*\? groupSecret\s*: null;\s*const edited = [^\n]*\n\s*if \(asked\) setSameRideAsk\(\{ then: go, secret: asked, cancel \}\);\s*else if \(edited\) setSameRideAsk\(\{ then: go, secret: edited, cancel, edited: true \}\);\s*else go\(groupSecret\);/,
  );
  // Start ride: by the led line's secret where this page shared one for the route shown, else the plan's.
  assert.match(app, /const led = start && !riding && sharedOpenNow\.current\?\.own && sharedOpenNow\.current\.answer === shown \? rideSecretOf\(sharedOpenNow\.current, groupSecret\) : null;/);
  // New ride: the line this page led is dropped too, never a received link's.
  assert.match(app, /rideLinkSent\.current = null;\s*\/\/[^\n]*\n\s*const after = sharedAfterRide\(sharedOpenNow\.current\);\s*if \(after !== sharedOpenNow\.current\) \{\s*sharedOpenNow\.current = after;\s*setSharedOpen\(after\);\s*\}\s*const fresh = newRide/);
  assert.match(app, /return rideLeadFor\(sent, line, leads\.current, leadPrep\.current\);/);
  assert.match(app, /const lead = ride && kept \? rideLeadFor\(again, sharedId, leads\.current, leadPrep\.current\) : null;/);
  assert.match(app, /const copyLink = \(\) => sameRideFirst\(\(secret\) => void copyLinkWith\(secret\)\);/);
  assert.match(app, /shareRoute=\{\(ride\) => \(ride \? sameRideFirst\(\(\) => void shareRoute\(true\), true\) : sameRideFirst\(\(secret\) => void shareRoute\(false, shareNav, secret\)\)\)\}/);
  assert.match(app, /const startRideChecked = \(\) => sameRideFirst\(\(\) => startRideNoted\(""\), false, undefined, true\);/);
  assert.match(app, /const broadcastRide = \(\) => sameRideFirst\(broadcastRideNow, true\);/);
  assert.match(app, /const broadcastQr = \(\) => sameRideFirst\(broadcastQrNow, true\);/);
  assert.match(app, /const broadcastFromRide = \(\) => sameRideThen\(broadcastFromRideNow\);/);
  assert.match(app, /const broadcastQrFromRide = \(\) => sameRideThen\(broadcastQrFromRideNow\);/);
  // When each link first went out: the plan's, and a ride link's leader.
  assert.match(app, /const \{ link, kept \} = sharedLinkNow\(secret\);\s*const done = await copyText\(link, navigator\.clipboard, selectionCopy\);\s*if \(done\) planLinkSent\(secret\);/);
  assert.match(app, /if \(!ride && done === "shared"\) planLinkSent\(secret\);/);
  assert.match(app, /if \(ride && lead && done === "shared"\) markRideSent\(lead\.secret, Date\.now\(\)\);/);
  // Same ride: kept, and not asked again for 12 hours. New ride: no link sent or leader kept, a new prepared leader.
  assert.match(app, /markRideSent\(ask\.secret, Date\.now\(\), true\);\s*return ask\.then\(groupSecret\);/);
  assert.match(app, /const fresh = newRide\(leads\.current, ownSecrets\.current!, groupSecret\);\s*prepareLead\(\);\s*setGroupSecret\(fresh\);\s*ask\.then\(fresh\);/);
  // Going back: nothing goes, and the ride screen's press says nothing.
  assert.match(app, /if \(same === null\) return ask\.cancel\?\.\(\);/);
  assert.match(app, /new Promise\(\(resolve\) => sameRideFirst\(\(\) => void go\(\)\.then\(resolve\), true, \(\) => resolve\(""\)\)\);/);
  assert.match(app, /<SameRideDialog open=\{sameRideAsk !== null\} lead=\{sameRideAsk\?\.edited \? SAME_RIDE_EDITED_LEAD : undefined\} onSame=\{\(\) => answerSameRide\(true\)\} onNew=\{\(\) => answerSameRide\(false\)\} onCancel=\{\(\) => answerSameRide\(null\)\} \/>/);
});

test("the question is a modal dialog named by its heading: New ride takes the focus, Escape goes back, also without showModal", () => {
  const dialog = source("../SameRideDialog.tsx");
  // Open or not by the attribute, which a browser without the modal dialog also sets.
  assert.match(dialog, /const shown = dialog\.hasAttribute\("open"\);\s*if \(open && !shown\) \{/);
  assert.match(dialog, /\} else if \(!open && shown\) \{/);
  assert.doesNotMatch(dialog, /dialog\.open\b/);
  assert.match(dialog, /if \(typeof dialog\.showModal === "function"\) dialog\.showModal\(\);\s*else dialog\.setAttribute\("open", ""\);\s*newRef\.current\?\.focus\(\);/);
  assert.match(dialog, /if \(typeof dialog\.close === "function"\) dialog\.close\(\);\s*else dialog\.removeAttribute\("open"\);/);
  assert.match(dialog, /aria-labelledby=\{headingId\}\s*aria-describedby=\{leadId\}/);
  assert.match(dialog, /onCancel=\{\(event\) => \{\s*event\.preventDefault\(\);\s*onCancel\(\);\s*\}\}/);
  assert.match(dialog, /if \(event\.key === "Escape" && typeof dialogRef\.current\?\.showModal !== "function"\) \{\s*event\.preventDefault\(\);\s*onCancel\(\);/);
  assert.match(dialog, /<h2 id=\{headingId\}>\{SAME_RIDE_QUESTION\}<\/h2>/);
});

test("a Group Ride plan changed after its link went out is asked about, Same ride keeping the link that went out", () => {
  const { editedFromNext, markRideSent, wasRideSent } = rideGroup;
  const store = memoryStore();
  const sent = (secret: string) => wasRideSent(secret, store);
  const monday = newRideSecret();
  const edited = newRideSecret();
  const again = newRideSecret();
  // Not sent: a change asks nothing.
  assert.equal(editedFromNext(null, monday, edited, false, sent), null);
  markRideSent(monday, Date.UTC(2026, 10, 2, 20), false, store);
  // Sent, then changed: asked about by Monday's secret, and still after a second change.
  assert.equal(editedFromNext(null, monday, edited, false, sent), monday);
  assert.equal(editedFromNext(monday, edited, again, false, sent), monday);
  // Back to the plan whose own link went out, or cleared: nothing to ask.
  assert.equal(editedFromNext(monday, edited, monday, false, sent), null);
  assert.equal(editedFromNext(monday, edited, newRideSecret(), true, sent), null);
  // The question is asked only for the page's own plan, not for a ride link, and only while the new key is unsent.
  const app = source("../App.tsx");
  assert.match(app, /const edited = !asked && !ride && !led && !riding && isRideLink\(preset, points\) && groupSecretOwn\.current && !wasRideSent\(groupSecret\) \? editedFrom\.current : null;/);
  // Same ride: the changed plan goes out under the secret that went out; New ride: under its own new one.
  assert.match(app, /if \(ask\.edited\) \{\s*editedFrom\.current = null;\s*if \(!same\) return ask\.then\(groupSecret\);\s*\/\/[^\n]*\n\s*markRideSent\(ask\.secret, Date\.now\(\), true\);\s*setGroupSecret\(ask\.secret\);\s*return ask\.then\(ask\.secret\);/);
  assert.match(source("../SameRideDialog.tsx"), /<p id=\{leadId\}>\{lead\}<\/p>/);
});
