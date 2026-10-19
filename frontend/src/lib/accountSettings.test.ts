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
  saveSettings,
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
  assert.doesNotMatch(plan, /[#&]p=/);
  assert.doesNotMatch(plan, /s1|90/);
  const back = planFromSetting(plan);
  assert.equal(back?.preset, "group-ride");
  assert.equal(back?.dials.stress, 85);
  assert.equal(back?.dials.pickupStation, undefined);
  // A value with points is a route, not a setting.
  assert.equal(planFromSetting("#p=-77,38.9;-77.1,38.8&preset=default"), null);
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
  // Cleared on the device: the next save carries none, so the account's is cleared too.
  new WeightStore(laptop).clear();
  assert.equal(deviceSettings(null, laptop).weight, undefined);
});
