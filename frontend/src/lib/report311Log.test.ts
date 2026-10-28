// The 311 log (Stephen, 2026-10-20): logged anywhere, a checklist by website, checking archives it, kept on
// the device and merged with the account's.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  ACCOUNT_LOG_KEY,
  JURISDICTIONS,
  LOG_DIRTY_KEY,
  LOG_KEY,
  LOG_MAX_BYTES,
  MAX_ENTRIES,
  NOTE_MAX,
  STALE_DAYS,
  Report311LogStore,
  WHERE_PENDING,
  archived,
  capLog,
  entryText,
  isStale,
  lookUpWhere,
  mergeLogs,
  newEntry,
  openGroups,
  panelLoggedSaid,
  panelPlace,
  parseLog,
  type LogEntry,
  type Store,
} from "./report311Log.ts";

const DC_SPOT = { words: "on R Street Northeast", point: [-77.00709, 38.9126] as [number, number] };
const MOCO_SPOT = { words: "on Capital Crescent Trail at about mile 3.2", point: [-77.0957, 38.9851] as [number, number] };
const NOON = new Date("2026-10-20T16:00:00Z");
const MOCO_AT = { lat: 38.9851, lon: -77.0957 };

function memory(): Store & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return { data, getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v), removeItem: (k) => void data.delete(k) };
}

function fakeFetch(answer: (url: string, init?: RequestInit) => { status: number; body?: unknown } | "throw") {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fn = (async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const next = answer(url, init);
    if (next === "throw") throw new TypeError("offline");
    return { ok: next.status >= 200 && next.status < 300, status: next.status, json: async () => next.body } as Response;
  }) as unknown as typeof fetch;
  return { fn, calls };
}

function entry(over: Partial<LogEntry> = {}): LogEntry {
  return { ...newEntry("pothole", DC_SPOT, NOON), ...over };
}

test("an entry: the problem, the place words, the GPS position to 5 places and the time; DC known at once, elsewhere looked up", () => {
  const dc = newEntry("pothole", DC_SPOT, NOON);
  assert.equal(dc.where, "dc");
  assert.equal(dc.lat, 38.9126);
  assert.equal(dc.lon, -77.00709);
  assert.equal(dc.at, "2026-10-20T16:00:00.000Z");
  assert.equal(dc.reported, null);
  assert.equal(newEntry("tree", MOCO_SPOT, NOON).where, null, "outside DC: waits for the server's lookup");
  assert.notEqual(newEntry("pothole", DC_SPOT, NOON).id, dc.id);
});

test("the report to paste: what, where, the area, GPS and when (Eastern time), then the note", () => {
  assert.equal(entryText(entry()), "Pothole. Location: on R Street Northeast, Washington, DC. GPS 38.91260, -77.00709. Seen Oct 20, 12:00 PM.");
  assert.equal(
    entryText(entry({ kind: "tree", where: "moco", place: MOCO_SPOT.words, lat: 38.9851, lon: -77.0957, note: "  across the  trail " })),
    "Downed tree. Location: on Capital Crescent Trail at about mile 3.2, Montgomery County. GPS 38.98510, -77.09570. Seen Oct 20, 12:00 PM. across the trail.",
  );
  assert.equal(entryText(entry({ place: null, where: "va" })), "Pothole. Location: GPS 38.91260, -77.00709. Seen Oct 20, 12:00 PM.", "a state's roads add no area name");
});

test("the checklist: open entries by website, newest first; not looked up last; checked ones archived", () => {
  const a = entry({ id: "a", where: "moco", at: "2026-10-19T10:00:00.000Z" });
  const b = entry({ id: "b", where: "dc", at: "2026-10-19T11:00:00.000Z" });
  const c = entry({ id: "c", where: "dc", at: "2026-10-20T11:00:00.000Z" });
  const d = entry({ id: "d", where: null });
  const e = entry({ id: "e", where: "dc", reported: "2026-10-20T12:00:00.000Z" });
  const groups = openGroups([a, b, c, d, e]);
  assert.deepEqual(
    groups.map((g) => [g.heading, g.entries.map((x) => x.id)]),
    [
      ["Washington, DC", ["c", "b"]],
      ["Montgomery County", ["a"]],
      [WHERE_PENDING, ["d"]],
    ],
  );
  assert.equal(groups[0].site?.url, "https://311.dc.gov/citizen/s/");
  assert.deepEqual(archived([a, e]).map((x) => x.id), ["e"]);
});

test("stale: an open entry older than 30 days goes to Archived by itself, not reported; nothing is deleted", () => {
  const now = new Date("2026-11-25T12:00:00Z");
  const old = entry({ id: "old", at: "2026-10-20T12:00:00.000Z" });
  const fresh = entry({ id: "fresh", at: "2026-11-20T12:00:00.000Z" });
  const done = entry({ id: "done", at: "2026-11-24T12:00:00.000Z", reported: "2026-11-24T13:00:00.000Z" });
  assert.equal(STALE_DAYS, 30);
  assert.ok(isStale(old, now) && !isStale(fresh, now) && !isStale(done, now));
  assert.deepEqual(openGroups([old, fresh, done], now).flatMap((g) => g.entries.map((e) => e.id)), ["fresh"]);
  assert.deepEqual(archived([old, fresh, done], now).map((e) => e.id), ["done", "old"], "newest to Archived first");
  assert.equal(old.reported, null, "kept as not reported");
  const view = readFileSync(new URL("../Report311Log.tsx", import.meta.url), "utf8");
  assert.match(view, /` Not reported; archived after \$\{STALE_DAYS\} days\.`/);
  assert.match(view, /` Reported \$\{whenWords\(entry\.reported\)\}\.`/);
});

test("every website is an https address with a short name; Virginia's VDOT counties go to VDOT", () => {
  for (const [id, site] of Object.entries(JURISDICTIONS)) {
    assert.match(site.url, /^https:\/\//, id);
    assert.ok(site.site.length <= 30 && site.name.length <= 30, id);
  }
  assert.equal(JURISDICTIONS.va.url, "https://my.vdot.virginia.gov/");
  // The ids match the server's (core/report_log.py JURISDICTION_IDS).
  const server = readFileSync(new URL("../../../src/core/report_log.py", import.meta.url), "utf8");
  for (const id of Object.keys(JURISDICTIONS)) assert.ok(server.includes(`"${id}"`), `${id} is one the server names`);
});

test("merge by entry: the newer copy wins; nothing is lost; past the cap the oldest archived go first", () => {
  const account = [entry({ id: "x", changed: "2026-10-20T10:00:00.000Z" }), entry({ id: "y", at: "2026-10-19T00:00:00.000Z", changed: "2026-10-19T00:00:00.000Z" })];
  const device = [entry({ id: "x", reported: "2026-10-20T11:00:00.000Z", changed: "2026-10-20T11:00:00.000Z" }), entry({ id: "z" })];
  const merged = mergeLogs(account, device);
  assert.deepEqual(merged.map((e) => e.id).sort(), ["x", "y", "z"]);
  assert.equal(merged.find((e) => e.id === "x")?.reported, "2026-10-20T11:00:00.000Z", "checked off on the device later: archived");
  const many = Array.from({ length: MAX_ENTRIES + 2 }, (_, n) =>
    entry({ id: `e${n}`, at: new Date(NOON.getTime() + n * 1000).toISOString(), reported: n < 5 ? NOON.toISOString() : null }),
  );
  const capped = capLog(many);
  assert.equal(capped.length, MAX_ENTRIES);
  assert.ok(!capped.some((e) => e.id === "e0" || e.id === "e1"), "the oldest archived went");
  assert.ok(capped.some((e) => e.id === `e${MAX_ENTRIES + 1}`));
});

test("a damaged or old copy is read safely", () => {
  assert.deepEqual(parseLog("nope"), []);
  assert.deepEqual(parseLog([{ id: "bad id!" }, null, 3]), []);
  const kept = parseLog([{ ...entry({ id: "a" }), where: "atlantis" }, entry({ id: "a" })]);
  assert.equal(kept.length, 1);
  assert.equal(kept[0].where, null, "an unknown website is looked up again");
});

/** A fake account server: it merges each save by entry, as core/report_log.py merge_logs does, and tags the account. */
function fakeAccount(owner: string, start: LogEntry[] = []) {
  const server = { owner, entries: start, posts: 0, gets: 0, signedIn: true };
  const net = fakeFetch((url, init) => {
    if (url.includes("/api/report311/where")) return { status: 200, body: { where: "moco" } };
    if (!url.endsWith("/api/me/report311-log")) return { status: 404 };
    if (!server.signedIn) return { status: 401 };
    if (init?.method === "POST") {
      server.posts++;
      server.entries = mergeLogs(server.entries, JSON.parse(String(init.body)).entries);
    } else server.gets++;
    return { status: 200, body: { entries: server.entries, owner: server.owner } };
  });
  return { server, net };
}

const tick = (ms = 0) => new Promise((r) => setTimeout(r, ms));

test("the store: logged, noted and checked off on the device; signed in, moved to the account; lookups fill the website", async () => {
  const store = memory();
  const { server, net } = fakeAccount("owner-a");
  const log = new Report311LogStore(store, "https://x", net.fn, 0);
  let heard = 0;
  log.subscribe(() => heard++);
  const added = log.add("tree", MOCO_SPOT, NOON);
  assert.equal(log.list()[0].id, added.id);
  assert.ok(heard >= 1);
  await tick();
  assert.equal(log.list()[0].where, "moco", "looked up at once");
  assert.match(net.calls[0].url, /^https:\/\/x\/api\/report311\/where\?lat=38\.98510&lon=-77\.09570$/);
  log.setNote(added.id, "across the trail", new Date("2026-10-20T16:01:00Z"));
  log.setReported(added.id, true, new Date("2026-10-20T16:02:00Z"));
  assert.equal(log.list()[0].reported, "2026-10-20T16:02:00.000Z");
  assert.equal(JSON.parse(store.data.get(LOG_KEY) ?? "[]")[0].note, "across the trail");
  assert.equal(server.posts, 0, "signed out: nothing is sent");
  await log.signIn();
  assert.equal(server.posts, 1, "the account had none: this device's entries went up");
  assert.equal(server.entries[0].id, added.id);
  assert.equal(store.data.get(LOG_KEY), undefined, "moved: no longer this device's own");
  assert.equal(JSON.parse(store.data.get(ACCOUNT_LOG_KEY) ?? "{}").owner, "owner-a");
  assert.equal(store.data.get(LOG_DIRTY_KEY), undefined);
  log.setReported(added.id, false);
  assert.equal(store.data.get(LOG_DIRTY_KEY), "1", "until the account takes it");
  await tick(5);
  assert.equal(server.posts, 2, "signed in: the change is saved");
  assert.equal(server.entries[0].reported, null);
  assert.equal(store.data.get(LOG_DIRTY_KEY), undefined);
});

test("typing a note saves once, after the typing settles, and saves go one at a time", async () => {
  const { server, net } = fakeAccount("owner-a");
  const log = new Report311LogStore(memory(), "https://x", net.fn, 20);
  await log.signIn();
  const entry = log.add("pothole", DC_SPOT, NOON);
  for (const note of ["a", "ac", "acr", "across", "across the lane"]) log.setNote(entry.id, note);
  assert.equal(server.posts, 0, "not at each key");
  await tick(60);
  assert.equal(server.posts, 1);
  assert.equal(server.entries[0].note, "across the lane");
});

test("another account on the same device: the first one's copy is neither shown signed out nor merged into the second's", async () => {
  const store = memory();
  const a = fakeAccount("owner-a", [entry({ id: "a1" })]);
  const first = new Report311LogStore(store, "https://x", a.net.fn, 0);
  await first.signIn();
  assert.deepEqual(first.list().map((e) => e.id), ["a1"]);
  first.signOut();
  assert.deepEqual(first.list(), [], "signed out: this device's own, which is empty");
  assert.equal(store.data.get(ACCOUNT_LOG_KEY), undefined, "the account's copy went");
  // The next page load, signed in as someone else.
  const b = fakeAccount("owner-b", [entry({ id: "b1" })]);
  const second = new Report311LogStore(store, "https://x", b.net.fn, 0);
  await second.signIn();
  assert.deepEqual(second.list().map((e) => e.id), ["b1"]);
  assert.equal(b.server.posts, 0, "nothing of the first account's was sent");
});

test("a copy with unsaved changes waits, unshown, for its own account; a different account drops it", async () => {
  const store = memory();
  const a = fakeAccount("owner-a");
  const log = new Report311LogStore(store, "https://x", a.net.fn, 1_000_000);
  await log.signIn();
  log.add("pothole", DC_SPOT, NOON);
  log.signOut();
  assert.deepEqual(log.list(), []);
  assert.equal(JSON.parse(store.data.get(ACCOUNT_LOG_KEY) ?? "{}").waiting, true);
  assert.deepEqual(new Report311LogStore(store, "https://x", a.net.fn).list(), [], "a reload signed out does not show it");
  const b = fakeAccount("owner-b");
  const other = new Report311LogStore(store, "https://x", b.net.fn, 0);
  await other.signIn();
  assert.deepEqual(other.list(), []);
  assert.equal(b.server.posts, 0);
  const own = fakeAccount("owner-a");
  store.data.set(ACCOUNT_LOG_KEY, JSON.stringify({ owner: "owner-a", entries: [entry({ id: "w1" })], waiting: true }));
  const back = new Report311LogStore(store, "https://x", own.net.fn, 0);
  await back.signIn();
  assert.deepEqual(own.server.entries.map((e) => e.id), ["w1"], "its own account takes it at sign-in");
});

test("a save keeps what the server merged in: entries another device logged appear", async () => {
  const { server, net } = fakeAccount("owner-a");
  const log = new Report311LogStore(memory(), "https://x", net.fn, 0);
  await log.signIn();
  server.entries = [entry({ id: "phone", at: "2026-10-20T17:00:00.000Z" })];
  log.add("tree", MOCO_SPOT, NOON);
  await tick(5);
  assert.ok(log.list().some((e) => e.id === "phone"));
});

test("the cap counts bytes too: a long log loses its oldest archived entries first", () => {
  const long = (n: number, reported: string | null) => entry({ id: `e${n}`, at: new Date(NOON.getTime() + n * 1000).toISOString(), note: "é".repeat(NOTE_MAX), reported });
  const log = Array.from({ length: 200 }, (_, n) => long(n, n < 100 ? NOON.toISOString() : null));
  const capped = capLog(log);
  assert.ok(new TextEncoder().encode(JSON.stringify(capped)).length <= LOG_MAX_BYTES);
  assert.ok(capped.length < 200 && !capped.some((e) => e.id === "e0"), "the oldest archived went");
  assert.ok(capped.some((e) => e.id === "e199"));
});

test("no signal: the lookup waits, the entry stays under Website not looked up yet", async () => {
  const net = fakeFetch(() => "throw");
  assert.equal(await lookUpWhere("https://x", MOCO_SPOT.point, net.fn), undefined);
  const log = new Report311LogStore(memory(), "https://x", net.fn);
  log.add("pothole", MOCO_SPOT, NOON);
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(log.list()[0].where, null);
  assert.equal(await lookUpWhere("https://x", MOCO_SPOT.point, fakeFetch(() => ({ status: 200, body: { where: null } })).fn), "none");
});

test("a website looked up is not a change: it never outranks a check-off from another device, and the merge keeps it", async () => {
  const store = memory();
  const open = entry({ id: "p", where: null, ...MOCO_AT, changed: "2026-10-20T16:00:00.000Z" });
  store.data.set(LOG_KEY, JSON.stringify([open]));
  const log = new Report311LogStore(store, "https://x", fakeFetch(() => ({ status: 200, body: { where: "moco" } })).fn);
  await log.lookUp();
  assert.equal(log.list()[0].where, "moco");
  assert.equal(log.list()[0].changed, open.changed, "its time is kept");
  const checked = { ...open, reported: "2026-10-20T17:00:00.000Z", changed: "2026-10-20T17:00:00.000Z" };
  const merged = mergeLogs([checked], log.list());
  assert.equal(merged[0].reported, checked.reported, "the check-off stands");
  assert.equal(merged[0].where, "moco", "and the website is kept");
});

test("one lookup with no answer does not stop the others", async () => {
  let asked = 0;
  const net = fakeFetch(() => (asked++ === 0 ? { status: 429 } : { status: 200, body: { where: "moco" } }));
  const store = memory();
  store.data.set(LOG_KEY, JSON.stringify([entry({ id: "a", where: null, ...MOCO_AT }), entry({ id: "b", where: null, ...MOCO_AT })]));
  const log = new Report311LogStore(store, "https://x", net.fn);
  await log.lookUp();
  assert.deepEqual(log.list().map((e) => e.where).sort(), ["moco", null]);
});

test("the road panel's Log for 311: the road's name and its nearest point; an unnamed way is the GPS alone", () => {
  assert.deepEqual(panelPlace("R Street Northeast", [-77, 38.9]), { words: "on R Street Northeast", point: [-77, 38.9] });
  assert.equal(panelPlace("unnamed path", [-77, 38.9]).words, null);
  assert.equal(panelPlace(null, [-77, 38.9]).words, null);
  assert.equal(panelLoggedSaid(entry()), "Logged for 311: Pothole on R Street Northeast. It is in your 311 checklist in Reports.");
  const panel = readFileSync(new URL("../RoadInfoDialog.tsx", import.meta.url), "utf8");
  assert.match(panel, /aria-expanded=\{logMenu\} aria-controls=\{logMenuId\} onClick=\{\(\) => setLogMenu\(!logMenu\)\}>\s*\{LOG_311_TEXT\}/);
  assert.match(panel, /report311Log\(\)\.add\(k\.kind, panelPlace\(ready\?\.title \?\? null, ready\?\.on_way \?\? request\.point\)\)/);
  assert.match(panel, /logButton\.current\?\.focus\(\);/, "the focus goes back to Log for 311 as its list hides");
});

test("the checklist in Reports: a heading per website with its Open link, checkboxes, Archived folded", () => {
  const sheets = readFileSync(new URL("../app/Sheets.tsx", import.meta.url), "utf8");
  assert.match(sheets, /<Report311Log \/>/);
  const view = readFileSync(new URL("../Report311Log.tsx", import.meta.url), "utf8");
  assert.match(view, /<input type="checkbox" checked=\{done\} data-entry=\{entry\.id\} aria-describedby=\{`\$\{id\}-place`\} onChange=\{\(event\) => onCheck\(entry, event\.target\.checked\)\} \/>/);
  assert.match(view, /report311Log\(\)\.setReported\(entry\.id, checked\);/);
  assert.match(view, /<details className="fold log311-archived">/);
  assert.match(view, /<h3 id="suggest-311-heading" tabIndex=\{-1\}>\s*\{LOG_HEADING\}\s*<\/h3>/);
  assert.match(view, /\{t\("Open \{site\} \(new tab\)", \{ site: group\.site\.site \}\)\}/);
  assert.match(view, /target="_blank" rel="noopener noreferrer"/);
});

test("after End ride: how many are still to report, where Reports is, and Open Reports (Stephen, 2026-10-21)", async () => {
  const { openCount, outstandingSaid, OPEN_REPORTS, REPORTS_WHERE } = await import("./report311Log.ts");
  const now = new Date("2026-10-21T12:00:00Z");
  const fresh = { ...entry(), id: "a", at: "2026-10-20T12:00:00Z", reported: null };
  const done = { ...entry(), id: "b", at: "2026-10-20T12:00:00Z", reported: "2026-10-20T13:00:00Z" };
  const old = { ...entry(), id: "c", at: "2026-08-01T12:00:00Z", reported: null };
  assert.equal(openCount([fresh, done, old], now), 1);
  assert.equal(outstandingSaid(1), "1 problem still to report to 311.");
  assert.equal(outstandingSaid(3), "3 problems still to report to 311.");
  assert.equal(REPORTS_WHERE, "Reports is in Go's Menu and Plan's bottom bar.");
  assert.equal(OPEN_REPORTS, "Open Reports");
  const { readFileSync } = await import("node:fs");
  const card = readFileSync(new URL("../RideSummaryCard.tsx", import.meta.url), "utf8");
  assert.match(card, /\{owes && \(/);
  // Unchecking an old reported entry: it is stale once unreported, so it stays in Archived (the review of #339).
  const reportedLongAgo = { ...entry(), id: "d", at: "2026-09-01T12:00:00Z", reported: "2026-09-05T12:00:00Z" };
  assert.equal(isStale(reportedLongAgo, now), false);
  assert.equal(isStale({ ...reportedLongAgo, reported: null }, now), true);
  const list = readFileSync(new URL("../Report311Log.tsx", import.meta.url), "utf8");
  assert.match(list, /isStale\(\{ \.\.\.entry, reported: null \}, now\)/);
  assert.match(list, /openGroups\(entries, now\)/);
  assert.match(list, /archived\(entries, now\)/);
  assert.match(card, /onClick=\{onReports\}>\s*\{OPEN_REPORTS\}/);
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /onReports=\{rideEndReports\}/);
  assert.match(app, /const opener = go \? document\.querySelector<HTMLElement>\("\.go-menu"\)/);
  assert.match(app, /clearPlan\(\);\s*focusAfterRemove\.current = null;/);
  // Reports opens on the checklist: it comes first in the sheet.
  const sheets = readFileSync(new URL("../app/Sheets.tsx", import.meta.url), "utf8");
  const sheet = sheets.slice(sheets.indexOf('id="sheet-suggest"'));
  assert.ok(sheet.indexOf("<Report311Log />") < sheet.indexOf('aria-labelledby="suggest-map-heading"'));
  assert.match(app, /announce\(\[RIDE_ENDED_SAID, note, owed > 0/);
});
