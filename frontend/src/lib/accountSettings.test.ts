// Saved settings and the Home offer on sign-in (v0.7.0 plan, "Discord sign-in on, with saved settings and
// routes" item 2, and "Home without signing in": the account side).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  SIGN_IN_LINE,
  applyToDevice,
  deviceSettings,
  fetchSettings,
  hasSettings,
  onSignIn,
  parseSettings,
  planFromSetting,
  planSetting,
  retryUntil,
  saveSettings,
  saveUnitsUnsynced,
  setUnitsPending,
  signInLate,
  unitsPending,
} from "./accountSettings.ts";
import { startDials } from "./dials.ts";
import { HOME_OFFER_KEY, answerHomeOffer, deviceHome, homeOffer } from "./homeMove.ts";
import { DEVICE_KEY } from "./myGo.ts";
import { WEIGHT_STORAGE_KEY, WeightStore } from "./weight.ts";

class Memory {
  map = new Map<string, string>();
  getItem(key: string) {
    return this.map.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.map.set(key, value);
  }
  removeItem(key: string) {
    this.map.delete(key);
  }
}

test("the ride type and dials are kept without points, trip picks or the weight", () => {
  const dials = { ...startDials("group-ride"), stress: 85, pickupStation: "s1", systemWeightKg: 90, targetDistanceM: 40000 };
  const plan = planSetting("group-ride", dials);
  assert.doesNotMatch(plan, /(^|[#&])[pq]=/);
  assert.doesNotMatch(plan, /s1|90/);
  const back = planFromSetting(plan);
  assert.equal(back?.preset, "group-ride");
  assert.equal(back?.dials.stress, 85);
  assert.equal(back?.dials.pickupStation, undefined);
  // A value with points is a route, not a setting.
  assert.equal(planFromSetting("#p=-77,38.9;-77.1,38.8&preset=default"), null);
  assert.equal(planFromSetting("#q=nmm2OwmttHqrFtwB&preset=default"), null, "nor in the short form");
});

test("the device's settings are read from what it keeps, and an account's are written back", () => {
  const store = new Memory();
  store.setItem("routemaker.waterLayer", JSON.stringify({ on: true, basic: false, untreated: true }));
  store.setItem("routemaker.climbs", "1");
  store.setItem("routemaker.climbsFrom", "3");
  store.setItem("routemaker.topoLines", "off");
  store.setItem("routemaker.layerSections", JSON.stringify({ terrain: ["topo"] }));
  const doc = deviceSettings({ preset: "default", dials: startDials("default") }, store);
  assert.deepEqual(doc.water, { on: true, basic: false, untreated: true });
  assert.equal(doc.climbs, true);
  assert.equal(doc.climbsFrom, "3");
  assert.equal(doc.topo, false);
  assert.deepEqual(doc.sections, { terrain: ["topo"] });
  assert.match(doc.plan ?? "", /preset=default/);

  const other = new Memory();
  applyToDevice(doc, other);
  assert.deepEqual(deviceSettings({ preset: "default", dials: startDials("default") }, other), doc);
});

test("on sign-in an empty account takes the device's settings and a set account wins", () => {
  const device = { v: 1, topo: true };
  assert.deepEqual(onSignIn(null, device), { kind: "push-device", doc: device });
  assert.deepEqual(onSignIn({ v: 1 }, device), { kind: "push-device", doc: device });
  const account = { v: 1, topo: false, climbs: true };
  assert.deepEqual(onSignIn(account, device), { kind: "use-account", doc: account });
  assert.equal(hasSettings({ v: 1 }), false);
});

test("only settings that make sense are taken from an answer", () => {
  assert.equal(parseSettings([]), null);
  assert.deepEqual(parseSettings({ v: 1, topo: "yes", climbsFrom: "9", home: { lon: 1 }, water: { on: true } }), { v: 1 });
});

test("the settings are read and saved with the CSRF token, and a failure is not a save", async () => {
  let sent: RequestInit | undefined;
  const post = (async (_u: string, init?: RequestInit) => {
    sent = init;
    return new Response("{}", { status: 200 });
  }) as unknown as typeof fetch;
  assert.equal(await saveSettings("https://x.test", { v: 1, topo: true }, post, "csrftoken=abc"), true);
  assert.equal((sent?.headers as Record<string, string>)["X-CSRFToken"], "abc");
  assert.deepEqual(JSON.parse(String(sent?.body)), { settings: { v: 1, topo: true } });
  const refused = (async () => new Response("{}", { status: 401 })) as unknown as typeof fetch;
  assert.equal(await saveSettings("https://x.test", { v: 1 }, refused, ""), false);
  assert.equal(await fetchSettings("https://x.test", refused), undefined);
  const empty = (async () => new Response(JSON.stringify({ settings: null }), { status: 200 })) as unknown as typeof fetch;
  assert.equal(await fetchSettings("https://x.test", empty), null);
});

test("signing in offers to move the device's Home, never silently, and asks once", () => {
  const store = new Memory();
  assert.equal(homeOffer(deviceHome(store), null, store), null);
  store.setItem(DEVICE_KEY, JSON.stringify({ open_in: "", ride: "", home: { lon: -77.03, lat: 38.9, label: "Home" } }));
  const device = deviceHome(store);
  assert.ok(device);
  const offer = homeOffer(device, null, store);
  assert.match(offer?.question ?? "", /Move it into your account/);
  // The account already has another Home: replacing it is asked, not done.
  const other = { point: [-77.1, 38.95] as [number, number], label: "Work" };
  assert.match(homeOffer(device, other, store)?.question ?? "", /Replace your account's Home \(Work\)/);
  // The same Home in both: nothing to ask.
  assert.equal(homeOffer(device, { point: [-77.03, 38.9], label: "Home" }, store), null);
  answerHomeOffer(device!, store);
  assert.ok(store.getItem(HOME_OFFER_KEY));
  assert.equal(homeOffer(device, null, store), null);
});

test("Plan's Settings sheet says the one line, and only where sign-in is on", () => {
  const sheets = readFileSync(new URL("../app/Sheets.tsx", import.meta.url), "utf8");
  assert.ok(sheets.includes("SIGN_IN_LINE"));
  assert.doesNotMatch(sheets, /Saving routes and\s+peer review are coming/);
  assert.equal(SIGN_IN_LINE, "Sign in with Discord to save routes and sync settings across devices.");
  assert.match(sheets, /signInAvailable/);
});

test("signed in, the rider and bike weight goes with the account and comes back on another device (the owner, 2026-10-19)", () => {
  const weight = { name: "My weight", totalKg: 93.4, parts: { riderKg: 78.4, bikeKg: 15, cargoKg: 0 }, setAt: 1_760_000_000_000 };
  const phone = new Memory();
  phone.setItem(WEIGHT_STORAGE_KEY, JSON.stringify(weight));
  const doc = deviceSettings(null, phone);
  assert.deepEqual(doc.weight, weight);
  // Never in the plan setting.
  assert.equal(doc.plan, undefined);
  // An answered document keeps a usable weight and drops one that is not.
  assert.deepEqual(parseSettings({ v: 1, weight })?.weight, weight);
  assert.equal(parseSettings({ v: 1, weight: { totalKg: "heavy" } })?.weight, undefined);
  assert.equal(parseSettings({ v: 1, weight: { totalKg: 5000 } })?.weight, undefined);
  // Another device, signed in: the account's weight is put where the weight dialog reads it.
  const laptop = new Memory();
  const step = onSignIn(parseSettings(JSON.parse(JSON.stringify(doc))), deviceSettings(null, laptop));
  assert.equal(step.kind, "use-account");
  applyToDevice(step.doc, laptop);
  assert.deepEqual(new WeightStore(laptop).load(), weight);
  // Cleared on the laptop: the account gets weight null, and the phone, signed in again, clears its copy
  // instead of putting it back.
  new WeightStore(laptop).clear();
  const cleared = deviceSettings(null, laptop);
  assert.equal(cleared.weight, null);
  const back = parseSettings(JSON.parse(JSON.stringify(cleared)));
  assert.equal(back?.weight, null);
  const again = onSignIn(back, deviceSettings(null, phone));
  assert.equal(again.kind, "use-account");
  applyToDevice(again.doc, phone);
  assert.equal(new WeightStore(phone).load(), null);
  assert.equal(deviceSettings(null, phone).weight, null, "and the phone's next save keeps it cleared");
  // An account from before the weight was kept leaves the device's, which its next save adds.
  const tablet = new Memory();
  tablet.setItem(WEIGHT_STORAGE_KEY, JSON.stringify(weight));
  applyToDevice({ v: 1, topo: true }, tablet);
  assert.deepEqual(deviceSettings(null, tablet).weight, weight);
  // Where the browser refuses storage, the weight App holds is the one sent.
  assert.deepEqual(deviceSettings(null, null, weight).weight, weight);
});

/** A clock and window events a test drives by hand (retryUntil's RetryEnv). */
class FakeWindow {
  now = 0;
  next = 1;
  timers = new Map<number, { at: number; run: () => void }>();
  listeners = new Map<string, Set<() => void>>();
  setTimeout(run: () => void, ms: number) {
    const id = this.next++;
    this.timers.set(id, { at: this.now + ms, run });
    return id;
  }
  clearTimeout(id: number) {
    this.timers.delete(id);
  }
  addEventListener(type: string, run: () => void) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)?.add(run);
  }
  removeEventListener(type: string, run: () => void) {
    this.listeners.get(type)?.delete(run);
  }
  async advance(ms: number) {
    this.now += ms;
    for (const [id, timer] of [...this.timers]) {
      if (timer.at <= this.now) {
        this.timers.delete(id);
        timer.run();
      }
    }
    await settle();
  }
  async fire(type: string) {
    for (const run of [...(this.listeners.get(type) ?? [])]) run();
    await settle();
  }
}

const settle = () => new Promise((done) => setImmediate(done));

test("a settings read that fails at sign-in is tried again, a few times and then on the next focus or online", async () => {
  const win = new FakeWindow();
  let tries = 0;
  let answer = false;
  const stop = retryUntil(
    async () => {
      tries++;
      return answer;
    },
    win,
    [2000, 8000],
  );
  await settle();
  assert.equal(tries, 1, "tried at once");
  await win.advance(2000);
  assert.equal(tries, 2, "again after the first wait");
  await win.advance(8000);
  assert.equal(tries, 3, "again after the second");
  await win.advance(60000);
  assert.equal(tries, 3, "then no more timed tries");
  await win.fire("focus");
  assert.equal(tries, 4, "the page's next focus tries again");
  answer = true;
  await win.fire("online");
  assert.equal(tries, 5, "back online tries again");
  await win.fire("focus");
  await win.advance(60000);
  assert.equal(tries, 5, "once read, it stops");
  assert.equal(win.listeners.get("focus")?.size, 0);
  stop();
});

test("a settings retry stops when the page is done with it", async () => {
  const win = new FakeWindow();
  let tries = 0;
  const stop = retryUntil(
    async () => {
      tries++;
      return false;
    },
    win,
    [1000],
  );
  await settle();
  stop();
  await win.advance(1000);
  await win.fire("focus");
  assert.equal(tries, 1);
  assert.equal(win.timers.size, 0);
});

test("Units chosen before the account's settings could be read still apply, and a readable account gets only the units", async () => {
  const unreadable = (async () => new Response("{}", { status: 503 })) as unknown as typeof fetch;
  let posted = 0;
  const post = (async () => {
    posted++;
    return new Response("{}", { status: 200 });
  }) as unknown as typeof fetch;
  assert.equal(await saveUnitsUnsynced("https://x.test", "metric", unreadable, post, ""), true, "kept on this device");
  assert.equal(posted, 0, "nothing replaces the account's settings unread");
  let sent: RequestInit | undefined;
  const account = (async () => new Response(JSON.stringify({ settings: { v: 1, topo: true, units: "us" } }), { status: 200 })) as unknown as typeof fetch;
  const record = (async (_u: string, init?: RequestInit) => {
    sent = init;
    return new Response("{}", { status: 200 });
  }) as unknown as typeof fetch;
  assert.equal(await saveUnitsUnsynced("https://x.test", "metric", account, record, ""), true);
  assert.deepEqual(JSON.parse(String(sent?.body)), { settings: { v: 1, topo: true, units: "metric" } });
  const refused = (async () => new Response("{}", { status: 500 })) as unknown as typeof fetch;
  assert.equal(await saveUnitsUnsynced("https://x.test", "metric", account, refused, ""), false, "a failed save is said as one");
});

test("App tries the sign-in settings read again, and an unread account does not undo a Units change", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /retryUntil\(\(\) => syncSettingsOnSignIn\(origin, \(\) => live\), window\)/);
  assert.match(app, /!settingsSynced\s*\?\s*\(\) => saveUnitsUnsynced\(/);
  assert.doesNotMatch(app, /!settingsSynced\s*\?\s*async \(\) => false/);
});

test("a settings read that comes late keeps what was changed on this device since load, and saves it to the account", () => {
  const atLoad = { v: 1, topo: false, speed: 12, units: "us" as const };
  const account = { v: 1, topo: true, speed: 14, climbs: true, units: "metric" as const };
  // Nothing changed here since load: the account wins, as at any sign-in, and nothing is saved.
  assert.deepEqual(signInLate(account, atLoad, atLoad), { kind: "use-account", doc: account, save: null });
  // The riding speed changed mid-ride: kept, the rest the account's, and the result saved.
  const device = { ...atLoad, speed: 16 };
  const late = signInLate(account, device, atLoad);
  assert.equal(late.kind, "use-account");
  assert.deepEqual(late.doc, { v: 1, topo: true, speed: 16, climbs: true, units: "metric" });
  assert.deepEqual(late.save, late.doc);
  // A setting cleared here since load is cleared in the account too.
  const cleared = signInLate(account, { v: 1, topo: false, units: "us" as const }, atLoad);
  assert.equal("speed" in cleared.doc, false);
  // An empty account still takes the device's.
  assert.deepEqual(signInLate(null, device, atLoad), { kind: "push-device", doc: device, save: device });
});

test("a Units choice made while the account could not be read is kept by the next read, not undone", async () => {
  const store = new Memory();
  const unreadable = (async () => new Response("{}", { status: 503 })) as unknown as typeof fetch;
  const post = (async () => new Response("{}", { status: 200 })) as unknown as typeof fetch;
  assert.equal(await saveUnitsUnsynced("https://x.test", "metric", unreadable, post, "", store), true);
  assert.equal(unitsPending(store), true, "marked pending");
  // The page reloaded in Metric; the account, read now, still says Miles: the device's Metric stays and is saved.
  const device = { v: 1, topo: true, units: "metric" as const };
  const step = signInLate({ v: 1, topo: true, units: "us" }, device, device, unitsPending(store));
  assert.equal(step.doc.units, "metric");
  assert.deepEqual(step.save, { v: 1, topo: true, units: "metric" });
  setUnitsPending(false, store);
  assert.equal(unitsPending(store), false);
  // Saved to a readable account: nothing left pending.
  setUnitsPending(true, store);
  const account = (async () => new Response(JSON.stringify({ settings: { v: 1, units: "us" } }), { status: 200 })) as unknown as typeof fetch;
  assert.equal(await saveUnitsUnsynced("https://x.test", "metric", account, post, "", store), true);
  assert.equal(unitsPending(store), false);
});

test("App: a late settings read keeps this device's changes, and in a ride or Roam switches units without a reload", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /const step = signInLate\(account, device, settingsAtLoad\.current \?\? device, unitsPending\(\)\);/);
  assert.match(app, /if \(ridingNow\.current \|\| roamingNow\.current\) void switchUnitsInRide\(step\.doc\.units\);\s*else void chooseUnits\(step\.doc\.units\);/);
  assert.match(app, /void saveSettings\(origin, step\.save\)/);
});

test("a late read merges the favorite ride stars one by one: a star here is added, an unstar here removed, another device's kept", () => {
  const atLoad = { v: 1, favorites: ["gravel" as const, "cargo" as const] };
  const account = { v: 1, favorites: ["gravel" as const, "cargo" as const, "novice" as const] };
  // Starred Trailmaxxing and unstarred Cargo on this device since load; Novice was starred on another device.
  const device = { v: 1, favorites: ["gravel" as const, "trailmaxxing" as const] };
  const late = signInLate(account, device, atLoad);
  assert.deepEqual(late.doc.favorites, ["gravel", "novice", "trailmaxxing"]);
  assert.deepEqual(late.save?.favorites, ["gravel", "novice", "trailmaxxing"]);
  // A ride unstarred on another device since load stays unstarred, though this device still shows its star.
  const elsewhere = signInLate({ v: 1, favorites: ["gravel" as const] }, { v: 1, favorites: ["gravel" as const, "cargo" as const, "novice" as const] }, atLoad);
  assert.deepEqual(elsewhere.doc.favorites, ["gravel", "novice"]);
  // The Layers sections: the one changed here is this device's, the account's others are kept.
  const sectionsAtLoad = { v: 1, sections: { water: ["a"] } };
  const merged = signInLate({ v: 1, sections: { water: ["a"], rail: ["r"] } }, { v: 1, sections: { water: ["a", "b"] } }, sectionsAtLoad);
  assert.deepEqual(merged.doc.sections, { water: ["a", "b"], rail: ["r"] });
});

test("App: the baseline is the device's settings at page load, and a failed save keeps a Units choice pending", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /if \(settingsAtLoad\.current === null\) settingsAtLoad\.current = deviceSettings\(\{ preset, dials \}/);
  assert.doesNotMatch(app, /settingsAtLoad\.current \?\?= /);
  assert.match(app, /if \(saved\) setUnitsPending\(false\);\s*else lastSettings\.current = account;/);
  assert.match(app, /saveSettings\(window\.location\.origin, doc\)\.then\(\(saved\) => saved && setUnitsPending\(false\)\)/);
});

test("units switched during Roam (a late settings read, or Settings) bring the rest of the page round when Roam ends", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  const body = (name: string) => {
    const at = app.indexOf(`const ${name} = `);
    assert.ok(at > 0, name);
    return app.slice(at, app.indexOf("\n  };", at));
  };
  for (const name of ["endRoam", "roamLocationOff", "finishRide"]) assert.match(body(name), /reloadIfUnitsOwed\(\);/, name);
  assert.match(app, /function reloadIfUnitsOwed\(\) \{\s*if \(unitsReloadOwed\(\)\) window\.setTimeout\(\(\) => window\.location\.reload\(\), 300\);/);
});
