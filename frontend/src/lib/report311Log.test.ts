// The 311 log (Stephen, 2026-10-20): logged anywhere, a checklist by website, checking archives it, kept on
// the device and merged with the account's.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  JURISDICTIONS,
  LOG_DIRTY_KEY,
  LOG_KEY,
  MAX_ENTRIES,
  Report311LogStore,
  WHERE_PENDING,
  archived,
  capLog,
  entryText,
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

test("the store: logged, noted and checked off on the device; signed in, saved to the account; lookups fill the website", async () => {
  const store = memory();
  const net = fakeFetch((url, init) => {
    if (url.includes("/api/report311/where")) return { status: 200, body: { where: "moco" } };
    if (url.endsWith("/api/me/report311-log") && init?.method === "POST") return { status: 200, body: {} };
    if (url.endsWith("/api/me/report311-log")) return { status: 200, body: { entries: [] } };
    return { status: 404 };
  });
  const log = new Report311LogStore(store, "https://x", net.fn);
  let heard = 0;
  log.subscribe(() => heard++);
  const added = log.add("tree", MOCO_SPOT, NOON);
  assert.equal(log.list()[0].id, added.id);
  assert.ok(heard >= 1);
  assert.equal(store.data.get(LOG_DIRTY_KEY), "1", "signed out: the account has not taken it");
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(log.list()[0].where, "moco", "looked up at once");
  assert.match(net.calls[0].url, /^https:\/\/x\/api\/report311\/where\?lat=38\.98510&lon=-77\.09570$/);
  log.setNote(added.id, "across the trail", new Date("2026-10-20T16:01:00Z"));
  log.setReported(added.id, true, new Date("2026-10-20T16:02:00Z"));
  assert.equal(log.list()[0].reported, "2026-10-20T16:02:00.000Z");
  assert.equal(JSON.parse(store.data.get(LOG_KEY) ?? "[]")[0].note, "across the trail");
  await log.signIn();
  const posts = net.calls.filter((c) => c.init?.method === "POST");
  assert.equal(posts.length, 1, "the account had none: this device's log went up");
  assert.equal(JSON.parse(String(posts[0].init?.body)).entries[0].id, added.id);
  assert.equal(store.data.get(LOG_DIRTY_KEY), undefined);
  log.setReported(added.id, false);
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(net.calls.filter((c) => c.init?.method === "POST").length, 2, "signed in: each change is saved");
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

test("the road panel's Log for 311: the road's name and its nearest point; an unnamed way is the GPS alone", () => {
  assert.deepEqual(panelPlace("R Street Northeast", [-77, 38.9]), { words: "on R Street Northeast", point: [-77, 38.9] });
  assert.equal(panelPlace("unnamed path", [-77, 38.9]).words, null);
  assert.equal(panelPlace(null, [-77, 38.9]).words, null);
  assert.equal(panelLoggedSaid(entry()), "Logged for 311: Pothole on R Street Northeast. It is in your 311 checklist in Suggest.");
  const panel = readFileSync(new URL("../RoadInfoDialog.tsx", import.meta.url), "utf8");
  assert.match(panel, /aria-expanded=\{logMenu\} aria-controls=\{logMenuId\} onClick=\{\(\) => setLogMenu\(!logMenu\)\}>\s*\{LOG_311_TEXT\}/);
  assert.match(panel, /report311Log\(\)\.add\(k\.kind, panelPlace\(ready\?\.title \?\? null, ready\?\.on_way \?\? request\.point\)\)/);
  assert.match(panel, /logButton\.current\?\.focus\(\);/, "the focus goes back to Log for 311 as its list hides");
});

test("the checklist in Suggest: a heading per website with its Open link, checkboxes, Archived folded", () => {
  const sheets = readFileSync(new URL("../app/Sheets.tsx", import.meta.url), "utf8");
  assert.match(sheets, /<Report311Log \/>/);
  const view = readFileSync(new URL("../Report311Log.tsx", import.meta.url), "utf8");
  assert.match(view, /<input type="checkbox" checked=\{done\} aria-describedby=\{`\$\{id\}-place`\} onChange=\{\(event\) => report311Log\(\)\.setReported\(entry\.id, event\.target\.checked\)\} \/>/);
  assert.match(view, /<details className="fold log311-archived">/);
  assert.match(view, /<h3 id="suggest-311-heading">\{LOG_HEADING\}<\/h3>/);
  assert.match(view, /\{`Open \$\{group\.site\.site\} \(new tab\)`\}/);
  assert.match(view, /target="_blank" rel="noopener noreferrer"/);
});
