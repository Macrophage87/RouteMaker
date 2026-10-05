// The accessibility switch, shown as "High contrast" since OWNER-DECISIONS 384 (208, 209, 211, 212): where it
// starts (stored > the system's request for more contrast > off), the palette
// it chooses (?palette= > the switch > the default), what happens when storage
// or matchMedia fails, and that a flip reaches every place the stress colours
// and lines are drawn without a reload.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { parseSync } from "vite";
import { paintAt } from "../testSupport/paintAt.ts";
import {
  ACCESSIBILITY_PALETTE,
  BUSY_MIN_TIER,
  ACCESSIBILITY_STORAGE_KEY,
  CASING_EXTRA_PX,
  CONTRAST_MEDIA,
  DEFAULT_PALETTE,
  FACILITIES,
  PALETTES,
  STRONG_CASING_EXTRA_PX,
  STRONG_WIDTH_EXTRA,
  accessibilityOn,
  accessibilitySource,
  currentPalette,
  currentTiers,
  facilityWidthAt,
  furthTiers,
  legend,
  legendWidths,
  queryPalette,
  rememberAccessibility,
  resolveAccessibility,
  resolvePalette,
  setAccessibility,
  storedAccessibility,
  stressCasingLayers,
  gapLayers,
  stressLayers,
  styleKey,
  subscribePalette,
  tiersFor,
} from "../stressStyle.js";
import { ROUTE_STRESS_SOURCE_ID, setRouteSections, setStressPalette } from "./mapGlue.ts";
import { ROUTE_BLUE, ROUTE_CASING_CVD, routeCasing, routeClasses, routeLegend, routePaint, spanClass } from "./routeColours.ts";
import { UNRATED, UNRATED_CVD_COLOUR, stressSegments, unrated } from "./stressBar.ts";
import {
  ACCESSIBILITY_ADDRESS_NOTE,
  ACCESSIBILITY_CLASS,
  ACCESSIBILITY_CONTRAST_NOTE,
  ACCESSIBILITY_HINT,
  ACCESSIBILITY_LABEL,
  AccessibilitySwitch,
  followAccessibility,
  setRootClass,
} from "./accessibilitySwitch.ts";

const TIERS = [1, 2, 3, 4, 5] as const;
const colours = (name: "blended" | "twotone" | "cvd") => TIERS.map((n) => PALETTES[name][n].color);
const casings = (name: "blended" | "twotone" | "cvd") => TIERS.map((n) => PALETTES[name][n].casing);

/** A Storage stand-in. */
function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
  };
}

const throwing = {
  getItem: (): string | null => {
    throw new Error("SecurityError: storage is blocked");
  },
  setItem: (): void => {
    throw new Error("QuotaExceededError");
  },
};

/** A matchMedia stand-in for one query, whose answer a test can change and announce. */
function fakeMatchMedia(initial: boolean, kind: "events" | "legacy" = "events") {
  let matches = initial;
  const listeners = new Set<(event: { matches: boolean }) => void>();
  const asked: string[] = [];
  const query = {
    get matches() {
      return matches;
    },
    ...(kind === "events"
      ? {
          addEventListener: (type: string, fn: (event: { matches: boolean }) => void) => {
            assert.equal(type, "change");
            listeners.add(fn);
          },
          removeEventListener: (_type: string, fn: (event: { matches: boolean }) => void) => void listeners.delete(fn),
        }
      : {
          addListener: (fn: (event: { matches: boolean }) => void) => void listeners.add(fn),
          removeListener: (fn: (event: { matches: boolean }) => void) => void listeners.delete(fn),
        }),
  };
  return {
    matchMedia: (text: string) => {
      asked.push(text);
      return query;
    },
    asked,
    listeners,
    fire(next: boolean) {
      matches = next;
      for (const fn of [...listeners]) fn({ matches: next });
    },
  };
}

// The module's own state is shared by the tests that use it directly; each
// that changes it puts it back.
function withSwitch(on: boolean, body: () => void) {
  const before = accessibilityOn();
  setAccessibility(on, { remember: false });
  try {
    body();
  } finally {
    setAccessibility(before, { remember: false });
  }
}

type Module = typeof import("../stressStyle.js");

let instance = 0;
/**
 * A fresh copy of stressStyle.js, evaluated as a page load would with these
 * globals (location, localStorage, matchMedia), which are put back afterwards.
 */
async function loadedWith(
  globals: { search?: string; storage?: unknown; matchMedia?: unknown | "throws"; storageGetterThrows?: boolean },
): Promise<Module> {
  const g = globalThis as Record<string, unknown>;
  const saved = new Map<string, PropertyDescriptor | undefined>();
  for (const key of ["location", "localStorage", "matchMedia"]) saved.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
  const set = (key: string, descriptor: PropertyDescriptor) => Object.defineProperty(globalThis, key, { configurable: true, ...descriptor });
  const unset = (key: string) => delete g[key];
  if (globals.search !== undefined) set("location", { value: { search: globals.search } });
  else unset("location");
  if (globals.storageGetterThrows) {
    set("localStorage", {
      get() {
        throw new Error("SecurityError");
      },
    });
  } else if (globals.storage !== undefined) set("localStorage", { value: globals.storage });
  else unset("localStorage");
  if (globals.matchMedia === "throws") {
    set("matchMedia", {
      value: () => {
        throw new Error("matchMedia is not allowed");
      },
    });
  } else if (globals.matchMedia !== undefined) set("matchMedia", { value: globals.matchMedia });
  else unset("matchMedia");
  try {
    instance += 1;
    const url = `../stressStyle.js?load=${instance}`;
    return (await import(url)) as Module;
  } finally {
    for (const [key, descriptor] of saved) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else unset(key);
    }
  }
}

test("the module starts plain where there is no address, no storage and no request for contrast", () => {
  assert.equal(accessibilityOn(), false);
  assert.equal(currentPalette(), DEFAULT_PALETTE);
  assert.equal(accessibilitySource(), "default");
  assert.equal(DEFAULT_PALETTE, "twotone", "two-tone is the default since OWNER-DECISIONS 351");
});

test("palette precedence: the address, then the switch, then the default", () => {
  assert.equal(resolvePalette("", false), DEFAULT_PALETTE);
  assert.equal(resolvePalette("", true), ACCESSIBILITY_PALETTE);
  assert.equal(resolvePalette("?palette=twotone", true), "twotone", "the address beats the switch");
  assert.equal(resolvePalette("?palette=blended", true), "blended", "or the warm palette, an option since 351");
  assert.equal(resolvePalette("?palette=cvd", false), "cvd");
  assert.equal(resolvePalette("?palette=nonsense", true), ACCESSIBILITY_PALETTE, "an unknown name is no address choice");
  assert.equal(resolvePalette("?palette=__proto__", false), DEFAULT_PALETTE);
  assert.equal(resolvePalette(undefined), DEFAULT_PALETTE);
  assert.equal(queryPalette("?a=b&palette=cvd&c=d"), "cvd");
  assert.equal(queryPalette("?palette=nonsense"), null);
  assert.equal(queryPalette(""), null);
});

test("the switch's starting state: stored, then the request for more contrast, then off", () => {
  assert.equal(resolveAccessibility(null, false), false);
  assert.equal(resolveAccessibility(null, true), true, "more contrast turns it on when nothing is stored");
  assert.equal(resolveAccessibility(true, false), true);
  assert.equal(resolveAccessibility(false, true), false, "a stored off beats the request");
  assert.equal(resolveAccessibility(true, true), true);
});

test("what is stored is on, off, or nothing: anything else, and storage that throws, are nothing", () => {
  assert.equal(storedAccessibility(memoryStorage({ [ACCESSIBILITY_STORAGE_KEY]: "on" })), true);
  assert.equal(storedAccessibility(memoryStorage({ [ACCESSIBILITY_STORAGE_KEY]: "off" })), false);
  assert.equal(storedAccessibility(memoryStorage()), null);
  assert.equal(storedAccessibility(memoryStorage({ [ACCESSIBILITY_STORAGE_KEY]: "true" })), null);
  assert.equal(storedAccessibility(memoryStorage({ [ACCESSIBILITY_STORAGE_KEY]: "" })), null);
  assert.equal(storedAccessibility(throwing), null);
  assert.equal(storedAccessibility(null), null);
});

test("a flip is remembered under one key, on or off", () => {
  const storage = memoryStorage();
  withSwitch(false, () => {
    setAccessibility(true, { storage });
    assert.equal(storage.data.get(ACCESSIBILITY_STORAGE_KEY), "on");
    assert.equal(storedAccessibility(storage), true);
    setAccessibility(false, { storage });
    assert.equal(storage.data.get(ACCESSIBILITY_STORAGE_KEY), "off");
    assert.equal(storedAccessibility(storage), false);
    setAccessibility(true, { storage, remember: false });
    assert.equal(storage.data.get(ACCESSIBILITY_STORAGE_KEY), "off", "remember: false leaves the stored choice alone");
  });
  assert.equal(rememberAccessibility(true, storage), true);
});

test("storage that throws or is absent does not break a flip: it holds for the visit", () => {
  assert.equal(rememberAccessibility(true, throwing), false);
  assert.equal(rememberAccessibility(true, null), false);
  withSwitch(false, () => {
    setAccessibility(true, { storage: throwing });
    assert.equal(accessibilityOn(), true);
    assert.equal(currentPalette(), ACCESSIBILITY_PALETTE);
  });
});

test("load: nothing set means off and the default palette", async () => {
  const m = await loadedWith({ search: "", storage: memoryStorage(), matchMedia: fakeMatchMedia(false).matchMedia });
  assert.equal(m.accessibilityOn(), false);
  assert.equal(m.currentPalette(), "twotone");
  assert.equal(m.accessibilitySource(), "default");
});

test("load: a device that asks for more contrast starts on, with nothing stored, and the panel says why", async () => {
  const media = fakeMatchMedia(true);
  const m = await loadedWith({ search: "", storage: memoryStorage(), matchMedia: media.matchMedia });
  assert.deepEqual(media.asked, [CONTRAST_MEDIA]);
  assert.equal(CONTRAST_MEDIA, "(prefers-contrast: more)");
  assert.equal(m.accessibilityOn(), true);
  assert.equal(m.currentPalette(), "cvd");
  assert.equal(m.accessibilitySource(), "contrast");
  assert.equal(m.currentTiers()[0].width, 2.5 + STRONG_WIDTH_EXTRA);
});

test("load: a stored choice always wins over the request for contrast, both ways", async () => {
  const off = await loadedWith({ storage: memoryStorage({ [ACCESSIBILITY_STORAGE_KEY]: "off" }), matchMedia: fakeMatchMedia(true).matchMedia });
  assert.equal(off.accessibilityOn(), false);
  assert.equal(off.currentPalette(), "twotone");
  assert.equal(off.accessibilitySource(), "chosen");
  const on = await loadedWith({ storage: memoryStorage({ [ACCESSIBILITY_STORAGE_KEY]: "on" }), matchMedia: fakeMatchMedia(false).matchMedia });
  assert.equal(on.accessibilityOn(), true);
  assert.equal(on.currentPalette(), "cvd");
  assert.equal(on.accessibilitySource(), "chosen");
});

test("load: ?palette= decides the palette whatever the switch says, and the switch still strengthens the lines", async () => {
  const stored = memoryStorage({ [ACCESSIBILITY_STORAGE_KEY]: "on" });
  const twotone = await loadedWith({ search: "?palette=twotone", storage: stored });
  assert.equal(twotone.currentPalette(), "twotone");
  assert.equal(twotone.accessibilityOn(), true);
  assert.equal(twotone.paletteSetByAddress(), true);
  assert.equal(twotone.currentTiers()[2].color, PALETTES.twotone[3].color);
  assert.equal(twotone.currentTiers()[2].width, 4.75, "LTS 3's 4.25 and the switch's half a pixel");
  const blended = await loadedWith({ search: "?x=1&palette=blended", storage: stored });
  assert.equal(blended.currentPalette(), "blended");
  // And a flip does not move a palette the address chose, but it does change what is drawn (and so what re-renders).
  const keyOn = twotone.styleKey();
  const tiersOn = twotone.currentTiers();
  twotone.setAccessibility(false, { remember: false });
  assert.equal(twotone.currentPalette(), "twotone");
  assert.notEqual(twotone.styleKey(), keyOn, "the style key moves though the palette does not");
  assert.notEqual(twotone.currentTiers(), tiersOn);
  assert.equal(twotone.currentTiers()[2].width, 4.25);
  const plain = await loadedWith({ search: "?palette=nonsense", storage: stored });
  assert.equal(plain.currentPalette(), "cvd", "an address name the page does not have is ignored");
  assert.equal(plain.paletteSetByAddress(), false);
});

test("load: blocked storage, or a matchMedia that throws or is missing, falls back to off", async () => {
  const blocked = await loadedWith({ storageGetterThrows: true, matchMedia: fakeMatchMedia(false).matchMedia });
  assert.equal(blocked.accessibilityOn(), false);
  assert.equal(blocked.currentPalette(), "twotone");
  const throwingStorage = await loadedWith({ storage: throwing });
  assert.equal(throwingStorage.accessibilityOn(), false);
  const noMedia = await loadedWith({ storage: memoryStorage() });
  assert.equal(noMedia.accessibilityOn(), false);
  const badMedia = await loadedWith({ storage: memoryStorage(), matchMedia: "throws" });
  assert.equal(badMedia.accessibilityOn(), false);
  // Blocked storage with a contrast request: the request still decides.
  const requested = await loadedWith({ storageGetterThrows: true, matchMedia: fakeMatchMedia(true).matchMedia });
  assert.equal(requested.accessibilityOn(), true);
});

test("live: with nothing chosen the switch follows the request for contrast as it changes, with no reload", async () => {
  const media = fakeMatchMedia(false);
  const m = await loadedWith({ storage: memoryStorage(), matchMedia: media.matchMedia });
  const heard: string[] = [];
  m.subscribePalette((name: string) => heard.push(name));
  assert.equal(m.accessibilityOn(), false);
  media.fire(true);
  assert.equal(m.accessibilityOn(), true);
  assert.equal(m.currentPalette(), "cvd");
  assert.deepEqual(heard, ["cvd"], "subscribers are told");
  media.fire(true);
  assert.deepEqual(heard, ["cvd"], "an unchanged answer tells nobody");
  media.fire(false);
  assert.equal(m.accessibilityOn(), false);
  assert.equal(m.currentPalette(), "twotone");
  assert.deepEqual(heard, ["cvd", "twotone"]);
});

test("live: once the rider has chosen, the request for contrast no longer moves the switch", async () => {
  const media = fakeMatchMedia(false);
  const storage = memoryStorage();
  const m = await loadedWith({ storage, matchMedia: media.matchMedia });
  m.setAccessibility(false, { storage });
  media.fire(true);
  assert.equal(m.accessibilityOn(), false, "the rider's off stands");
  assert.equal(m.accessibilitySource(), "chosen");
  m.setAccessibility(true, { storage });
  media.fire(false);
  assert.equal(m.accessibilityOn(), true, "the rider's on stands");
  // A choice that could not be stored still stands for the visit.
  const second = fakeMatchMedia(true);
  const n = await loadedWith({ storage: throwing, matchMedia: second.matchMedia });
  assert.equal(n.accessibilityOn(), true);
  n.setAccessibility(false, { storage: throwing });
  second.fire(false);
  second.fire(true);
  assert.equal(n.accessibilityOn(), false);
});

test("live: a trial flip (remember: false) is not a choice, so the request still moves it", async () => {
  const media = fakeMatchMedia(false);
  const m = await loadedWith({ storage: memoryStorage(), matchMedia: media.matchMedia });
  m.setAccessibility(true, { remember: false });
  assert.equal(m.accessibilitySource(), "default");
  media.fire(true);
  media.fire(false);
  assert.equal(m.accessibilityOn(), false);
});

test("live: older browsers' addListener is used when addEventListener is missing, and stopping removes the listener", async () => {
  const legacy = fakeMatchMedia(false, "legacy");
  const m = await loadedWith({ storage: memoryStorage(), matchMedia: legacy.matchMedia });
  assert.equal(legacy.listeners.size, 1);
  legacy.fire(true);
  assert.equal(m.accessibilityOn(), true);
  const modern = fakeMatchMedia(false);
  const stop = m.watchContrast(modern.matchMedia as never);
  assert.equal(modern.listeners.size, 1);
  assert.equal(legacy.listeners.size, 0, "watching again lets go of the first query");
  stop();
  assert.equal(modern.listeners.size, 0);
  modern.fire(true);
  assert.equal(m.accessibilityOn(), false, "no longer listening, and the answer at the last watch (off) holds");
});

test("the strong widths are the figures the owner's switch promises: half a pixel more line, a casing 3 px wider than it", () => {
  assert.equal(STRONG_WIDTH_EXTRA, 0.5);
  assert.equal(STRONG_CASING_EXTRA_PX, 3);
  assert.equal(CASING_EXTRA_PX, 2);
  assert.deepEqual(tiersFor("cvd", true).map((t: { width: number }) => t.width), [3, 3.75, 4.75, 5.5, 7]);
  assert.deepEqual(tiersFor("cvd").map((t: { width: number }) => t.width), [2.5, 3.25, 4.25, 5, 6.5]);
  // A casing is a halo, not a band: no wider on the two sides together than the line itself (stressStyle.test.mjs holds the plain ones to it).
  for (const tier of tiersFor("cvd", true)) assert.ok(tier.casingExtra <= tier.width, `LTS ${tier.tier}`);
});

test("the tiers: strong draws lines half a pixel wider, the calm tiers' casings black or white, every casing wider, in the same palette", () => {
  for (const name of ["blended", "twotone", "cvd"]) {
    const plain = tiersFor(name);
    const strong = tiersFor(name, true);
    strong.forEach((tier: (typeof strong)[number], i: number) => {
      assert.equal(tier.width, plain[i].width + STRONG_WIDTH_EXTRA);
      assert.equal(tier.color, plain[i].color, "the colour is the palette's");
      assert.equal(tier.casingExtra, STRONG_CASING_EXTRA_PX);
      assert.equal(plain[i].casingExtra, CASING_EXTRA_PX);
      assert.equal(tier.strong, true);
      assert.equal(plain[i].strong, false);
      assert.deepEqual(tier.dash, plain[i].dash);
      if (tier.tier >= BUSY_MIN_TIER || tier.tier === 2) {
        // A busy tier's casing is what its dash gaps show: the switch leaves it, so the gaps are no
        // harsher (OWNER-DECISIONS 292), and Avoid's red is a colour of its own (274). LTS 2's edge is a blue,
        // kept (356: "a blue instead of black"); its gaps show its own gap colour.
        assert.equal(tier.casing, plain[i].casing, `${name} LTS ${tier.tier}`);
        return;
      }
      assert.match(tier.casing, /^#(000000|ffffff)$/, `${name} LTS ${tier.tier}`);
      assert.equal(tier.casing, plain[i].casing === "#ffffff" ? "#ffffff" : "#000000", "a light casing stays light and a dark one goes black");
      assert.deepEqual(tier.dash, plain[i].dash);
    });
  }
  assert.ok(STRONG_CASING_EXTRA_PX > CASING_EXTRA_PX);
});

test("a flip changes what every consumer of the tiers reads: overlay, route, legend, bar", () => {
  withSwitch(true, () => {
    assert.equal(currentPalette(), "cvd");
    assert.deepEqual(currentTiers().map((t: { color: string }) => t.color), colours("cvd"));
    assert.deepEqual(furthTiers().map((t: { tier: number }) => t.tier), [1, 2, 3, 4]);
    // The overlay's layers, built after the flip.
    // A paved road's colour (an unpaved one's is the brown ramp, unpavedBrown.test.ts).
    assert.deepEqual(stressLayers().map((l: { id: string; paint: Record<string, unknown> }) => paintAt(l, "line-color", { unpaved: false })), colours("cvd"));
    assert.deepEqual(
      stressCasingLayers().map((l) => paintAt(l, "line-color")),
      tiersFor("cvd", true).map((t: { casing: string }) => t.casing),
    );
    // The route's classes and spans.
    assert.equal(spanClass({ tier: 3, facility: "none" }).color, PALETTES.cvd[3].color);
    assert.deepEqual(routeClasses().filter((c) => /^[1-5]$/.test(c.key)).map((c) => c.color), colours("cvd"));
    const spans = [{ from_m: 0, to_m: 100, tier: 4, facility: "none" }] as unknown as Parameters<typeof routeLegend>[0];
    assert.equal(routeLegend(spans)[0].color, PALETTES.cvd[4].color);
    // The legend and the stress bar.
    assert.deepEqual(legend().map((e: { color: string }) => e.color), colours("cvd"));
    const bar = stressSegments({ "1": 10, "2": 10, "3": 10, "4": 10, "5": 10 });
    assert.deepEqual(bar.filter((s) => s.key !== "unknown").map((s) => s.color), colours("cvd"));
  });
  // And back, with nothing left over.
  assert.deepEqual(stressLayers().map((l: { id: string; paint: Record<string, unknown> }) => paintAt(l, "line-color", { unpaved: false })), colours("twotone"));
  assert.deepEqual(stressCasingLayers().map((l) => paintAt(l, "line-color")), casings("twotone"));
  assert.equal(spanClass({ tier: 3, facility: "none" }).color, PALETTES.twotone[3].color);
  assert.equal(stressSegments({ "5": 1 }).find((s) => s.key === "5")?.color, PALETTES.twotone[5].color);
});

test("a flip widens the lines, the casings and the facility rails, and nothing else about the shapes", () => {
  const widthAt14 = (layer: { paint: Record<string, unknown> }) => {
    const expression = layer.paint["line-width"] as unknown[];
    // ["step", ["zoom"], thin(10), 11, thin(11), 12, at(13), 14, at(14), ...]: the value from zoom 14 follows the stop 14; a tier-1 road is the plain branch.
    const at14 = expression[expression.indexOf(14) + 1] as unknown[];
    const road = at14[3] as unknown;
    return typeof road === "number" ? road : (road as unknown[])[3];
  };
  const plain = { lines: stressLayers().map(widthAt14), casings: stressCasingLayers().map(widthAt14), rail: JSON.stringify(facilityWidthAt(FACILITIES[0])) };
  const shapes = currentTiers().map((t: { dash: number[]; label: string }) => [t.dash, t.label]);
  withSwitch(true, () => {
    const strong = { lines: stressLayers().map(widthAt14), casings: stressCasingLayers().map(widthAt14), rail: JSON.stringify(facilityWidthAt(FACILITIES[0])) };
    plain.lines.forEach((w: number, i: number) => {
      assert.equal(strong.lines[i], w + STRONG_WIDTH_EXTRA, `line ${i + 1}`);
      assert.equal(strong.casings[i] - strong.lines[i], STRONG_CASING_EXTRA_PX);
    });
    assert.notEqual(strong.rail, plain.rail, "the rails sit outside the casing, so they follow");
    assert.deepEqual(currentTiers().map((t: { dash: number[]; label: string }) => [t.dash, t.label]), shapes);
  });
});

test("the legend's widths are the map's: each tier's line and casing, and the facility legend's casing and rails, plain and strong", () => {
  const plain = legendWidths(tiersFor("blended"));
  assert.deepEqual(plain.tiers.map((t: { line: number }) => t.line), [2.5, 3.25, 4.25, 5, 6.5]);
  assert.deepEqual(plain.tiers.map((t: { casing: number }) => t.casing), [4.5, 5.25, 6.25, 7, 8.5]);
  assert.equal(plain.facilityCasing, 4.5);
  assert.deepEqual(plain.rails, { path: 9.5, protected: 12.5, lane: 6.5 });
  const strong = legendWidths(tiersFor("cvd", true));
  assert.deepEqual(strong.tiers.map((t: { line: number }) => t.line), [3, 3.75, 4.75, 5.5, 7]);
  assert.deepEqual(strong.tiers.map((t: { casing: number }) => t.casing), [6, 6.75, 7.75, 8.5, 10], "the switch's casing is 3 px wider than its line");
  assert.equal(strong.facilityCasing, 6);
  assert.deepEqual(strong.rails, { path: 11, protected: 14, lane: 9 }, "the rails sit outside the wider casing, and the painted rail is 1.5 px");
  // Without an argument, the tiers in use.
  assert.deepEqual(legendWidths(), plain);
  withSwitch(true, () => assert.deepEqual(legendWidths(), strong));
});

test("a facility's rails for a tier the style has no entry for are LTS 1's, casing included, plain and strong", () => {
  // The full-width branch of the zoom step (from z12), then its match's fallback.
  const full = (width: unknown) => ((width as unknown[]).at(-1) as unknown[]).at(-1);
  const fallback = (tiers: ReturnType<typeof tiersFor>) => full(facilityWidthAt(FACILITIES[0], undefined, tiers));
  assert.equal(fallback(tiersFor("blended")), 9.5);
  assert.equal(fallback(tiersFor("cvd", true)), 11);
  withSwitch(true, () => assert.equal(full(facilityWidthAt(FACILITIES[0])), 11));
  // The painted rail's own strong width reaches the fallback too.
  const lane = FACILITIES.find((f: { facility: string }) => f.facility === "lane");
  assert.equal(full(facilityWidthAt(lane, undefined, tiersFor("cvd", true))), 9);
});

test("the route's casing and the unrated grey follow the palette: the colour-blind-friendly one has its own", () => {
  assert.equal(routeCasing(), ROUTE_BLUE);
  assert.equal(routePaint(true, false).casingColor, ROUTE_BLUE);
  assert.equal(unrated().color, UNRATED.color);
  assert.equal(spanClass({ tier: null, facility: null }).color, UNRATED.color);
  withSwitch(true, () => {
    assert.equal(routeCasing(), ROUTE_CASING_CVD);
    assert.equal(routePaint(true, false).casingColor, ROUTE_CASING_CVD);
    assert.equal(routePaint(false, false).casingColor, "#ffffff", "a one-colour route keeps its white casing");
    assert.equal(unrated().color, UNRATED_CVD_COLOUR);
    assert.equal(unrated().short, UNRATED.short, "only the colour changes");
    assert.equal(spanClass({ tier: null, facility: null }).color, UNRATED_CVD_COLOUR, "the route line");
    assert.equal(stressSegments({ unknown: 5, "1": 5 }).find((seg) => seg.key === "unknown")?.color, UNRATED_CVD_COLOUR, "and the stress bar");
    assert.equal(routeClasses().find((c) => c.key === "unknown")?.color, UNRATED_CVD_COLOUR);
  });
  assert.equal(spanClass({ tier: null, facility: null }).color, UNRATED.color, "and back after the flip");
  assert.equal(routeCasing("cvd"), ROUTE_CASING_CVD);
  assert.equal(routeCasing("twotone"), ROUTE_BLUE);
  assert.equal(unrated("cvd").color, UNRATED_CVD_COLOUR);
  assert.match(
    readFileSync(fileURLToPath(new URL("../FacilityBreakdown.tsx", import.meta.url)), "utf8"),
    /const casing = routeCasing\(\);[\s\S]*stroke=\{casing\} strokeWidth=\{ROUTE_CASING_WIDTH\}/,
    "the route colour legend draws the same casing",
  );
});

test("the style key, and so a component's re-render, changes with the flip and not otherwise", () => {
  const before = styleKey();
  assert.equal(styleKey(), before);
  withSwitch(true, () => assert.notEqual(styleKey(), before));
  assert.equal(styleKey(), before);
  const tiers = currentTiers();
  assert.equal(currentTiers(), tiers, "the same array until the style changes");
});

test("subscribers hear a flip once, not when it changes nothing, and not after they stop", () => {
  const seen: string[] = [];
  const stop = subscribePalette((name: string) => seen.push(name));
  try {
    setAccessibility(false, { remember: false });
    assert.deepEqual(seen, []);
    setAccessibility(true, { remember: false });
    setAccessibility(true, { remember: false });
    assert.deepEqual(seen, ["cvd"]);
    stop();
    setAccessibility(false, { remember: false });
    assert.deepEqual(seen, ["cvd"]);
  } finally {
    stop();
    setAccessibility(false, { remember: false });
  }
});

test("the warm palette is unchanged by the new ones, and the tiers in use are the default two-tone (OWNER-DECISIONS 351)", () => {
  assert.deepEqual(PALETTES.blended, {
    1: { color: "#9ed3ac", casing: "#2f5d47" },
    2: { color: "#57a06c", casing: "#1a2638", gap: "#7a8fa3" },
    3: { color: "#bf730b", casing: "#45290a" },
    4: { color: "#c80018", casing: "#ffffff" },
    5: { color: "#14040a", casing: "#ee3b2c" },
  });
  assert.deepEqual(
    currentTiers().map((t: { color: string; casing: string; casingExtra: number }) => [t.color, t.casing, t.casingExtra]),
    TIERS.map((n) => [PALETTES.twotone[n].color, PALETTES.twotone[n].casing, CASING_EXTRA_PX]),
  );
});

// What a map records.
function recordingMap(layers: string[], source: { setData(data: object): void } | undefined) {
  const paint: Array<[string, string, unknown]> = [];
  return {
    paint,
    map: {
      getLayer: (id: string) => (layers.includes(id) ? { id } : undefined),
      getSource: (id: string) => (id === ROUTE_STRESS_SOURCE_ID ? source : undefined),
      setPaintProperty: (id: string, name: string, value: unknown) => void paint.push([id, name, value]),
    },
  };
}

test("repaint wiring: the overlay's lines and casings, in colour and width, and the rails, are repainted in place", () => {
  const ids = [
    ...TIERS.flatMap((n) => [`stress-${n}`, `stress-casing-${n}`]),
    ...FACILITIES.map((f: { facility: string }) => `facility-${f.facility}`),
  ];
  const { map, paint } = recordingMap(ids, undefined);
  withSwitch(true, () => setStressPalette(map as never));
  const strong = tiersFor("cvd", true);
  const lines = stressLayers("stress", undefined, strong) as Array<{ id: string; paint: Record<string, unknown> }>;
  const edges = stressCasingLayers("stress", undefined, strong) as Array<{ id: string; paint: Record<string, unknown> }>;
  for (const layer of [...edges, ...lines]) {
    assert.deepEqual(
      paint.filter(([id]) => id === layer.id).map(([, name, value]) => [name, JSON.stringify(value)]),
      [
        ["line-color", JSON.stringify(layer.paint["line-color"])],
        ["line-width", JSON.stringify(layer.paint["line-width"])],
        ...("line-gap-width" in layer.paint ? [["line-gap-width", JSON.stringify(layer.paint["line-gap-width"])]] : []),
      ],
      layer.id,
    );
  }
  for (const facility of FACILITIES) {
    assert.equal(paint.filter(([id]) => id === `facility-${facility.facility}`).length, 1, "each rail's width is set once");
  }
  assert.equal(paint.length, TIERS.length * 5 + FACILITIES.length);
  // Every call set a colour or a width (a casing's gap included) and nothing else.
  assert.ok(paint.every(([, name]) => name === "line-color" || name === "line-width" || name === "line-gap-width"));
});

test("repaint wiring: two-tone LTS 3's ring layer (OWNER-DECISIONS 371) is repainted with the rest, transparent in a palette with no ring", () => {
  const { map, paint } = recordingMap(["stress-ring-3"], undefined);
  withSwitch(true, () => setStressPalette(map as never));
  assert.deepEqual(paint.map(([id, name, value]) => [id, name, value]).filter(([, name]) => name === "line-color"), [["stress-ring-3", "line-color", "rgba(0, 0, 0, 0)"]], "cool has no ring");
  assert.ok(paint.some(([id, name]) => id === "stress-ring-3" && name === "line-width"));
});

test("repaint wiring: LTS 2's gap layer (OWNER-DECISIONS 356) is repainted with the rest, in its colour and width", () => {
  const { map, paint } = recordingMap(["stress-gap-2"], undefined);
  withSwitch(true, () => setStressPalette(map as never));
  const gap = (gapLayers("stress", undefined, tiersFor("cvd", true)) as Array<{ id: string; paint: Record<string, unknown> }>).find((l) => l.id === "stress-gap-2")!;
  assert.deepEqual(
    paint.map(([id, name, value]) => [id, name, JSON.stringify(value)]),
    [
      ["stress-gap-2", "line-color", JSON.stringify(gap.paint["line-color"])],
      ["stress-gap-2", "line-width", JSON.stringify(gap.paint["line-width"])],
    ],
  );
});

test("repaint wiring: a layer the map does not have (the overlay unavailable) is skipped, not an error", () => {
  const { map, paint } = recordingMap(["stress-2", "stress-casing-2"], undefined);
  withSwitch(true, () => setStressPalette(map as never));
  assert.deepEqual([...new Set(paint.map(([id]) => id))].sort(), ["stress-2", "stress-casing-2"]);
  const none = recordingMap([], undefined);
  setStressPalette(none.map as never);
  assert.deepEqual(none.paint, []);
});

const ROUTE = {
  geometry: {
    type: "LineString" as const,
    coordinates: [
      [-77.0, 38.9],
      [-77.0, 38.91],
      [-77.0, 38.92],
    ],
  },
  stress_spans: [
    { from_m: 0, to_m: 1112, tier: 2, facility: "none" },
    { from_m: 1112, to_m: 2224, tier: 3, facility: "none" },
  ],
} as unknown as Parameters<typeof setRouteSections>[1];

test("repaint wiring: the route's sections are cut again in the palette in use, with the casing and opacities set", () => {
  let data: { features: Array<{ properties: { key: string; color: string; halo: string } }> } | undefined;
  const source = { setData: (d: object) => void (data = d as typeof data) };
  const { map, paint } = recordingMap([], source);
  withSwitch(true, () => setRouteSections(map as never, ROUTE, false));
  assert.deepEqual(
    data?.features.map((f) => [f.properties.key, f.properties.color, f.properties.halo]),
    [
      // LTS 2 keeps its own edge with the switch on (OWNER-DECISIONS 356).
      ["2", PALETTES.cvd[2].color, PALETTES.cvd[2].casing],
      // A busy tier's casing is its own with the switch on (OWNER-DECISIONS 292), and its halo with it.
      ["3", PALETTES.cvd[3].color, PALETTES.cvd[3].casing],
    ],
  );
  assert.deepEqual(
    paint.map(([id, name]) => `${id} ${name}`),
    ["route-line line-opacity", "route-stress line-opacity", "route-halo line-opacity", "route-ring line-opacity", "route-casing line-color", "route-unpaved line-opacity"],
  );
  assert.equal(paint[1][2], 1, "the sections are shown, fully");
  assert.equal(paint[2][2], 1, "and so are their halos");
  assert.equal(paint[3][2], 1, "and their rings (371)");
  assert.equal(paint[4][2], ROUTE_CASING_CVD, "under the colour-blind-friendly palette's own casing, not the blue its LTS 2 matches");
  assert.equal(paint[0][2], 0, "and the one-colour line is hidden");
  assert.equal(paint[5][2], 1, "the unpaved sections' dots with them");
  setRouteSections(map as never, ROUTE, true);
  assert.equal(paint[7][2], 0.45, "a stale route is still dimmed after a flip");
  assert.equal(paint[8][2], 0.45, "its halos too");
  assert.equal(paint[9][2], 0.45, "and its rings");
  assert.equal(paint[10][2], ROUTE_BLUE, "and back in the default palette, the blue casing");
  assert.equal(paint[11][2], 0.45, "and the unpaved dots");
});

test("repaint wiring: no route puts no sections in, and does not throw", () => {
  let data: { features: unknown[] } | undefined;
  const { map } = recordingMap([], { setData: (d: object) => void (data = d as typeof data) });
  setRouteSections(map as never, null, false);
  assert.deepEqual(data?.features, []);
});

test("the map and the panel are wired to the switch: MapView repaints on it, the components follow it", () => {
  const src = (name: string) => readFileSync(new URL(`../${name}`, import.meta.url), "utf8");
  const mapView = src("MapView.tsx");
  assert.match(mapView, /setStressPalette\(map, callbacks\.current\.when\)/);
  assert.match(mapView, /setRouteSections\(map, callbacks\.current\.route, callbacks\.current\.stale\)/);
  // The subscription is the effect's return value, so it is stopped with the component.
  assert.match(mapView, /useEffect\(\s*\(\) =>\s*subscribePalette\(/);
  for (const name of ["App.tsx", "FacilityBreakdown.tsx"]) assert.match(src(name), /useStressStyle\(\)/, name);
  const app = src("App.tsx");
  assert.match(app, /<AccessibilitySwitch/);
  assert.match(app, /setAccessibility\(on\)/);
  assert.match(src("main.tsx"), /followAccessibility\(document\.documentElement\)/);
  assert.match(src("lib/mapGlue.ts"), /export function setStressPalette/);
});

/** Every source file that ships: not a test, not the test support. */
function shippedSources(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      if (entry !== "testSupport" && entry !== "rail-data" && entry !== "licences") out.push(...shippedSources(path));
    } else if (/\.(ts|tsx|js|mjs)$/.test(entry) && !/\.test\./.test(entry)) out.push(path);
  }
  return out;
}

/** The readers of the tiers in use; one called at a module's top level runs once, at import, and keeps the colours of that moment. */
const TIER_READERS = new Set(["currentTiers", "furthTiers", "routeClasses", "legend"]);

/**
 * The calls to a tier reader that run when the module is imported: any not
 * inside a function (a declaration, expression, arrow or method, whose body
 * and default parameters run only when it is called). Parsed, not matched by
 * pattern, so `const T = currentTiers()` is caught and `(tiers = currentTiers())`
 * as a default parameter is not.
 */
function importTimeReads(file: string, source: string): string[] {
  const { program, errors } = parseSync(file, source);
  assert.deepEqual(errors.map((e: { message: string }) => e.message), [], `${file} parses`);
  const found: string[] = [];
  const visit = (node: unknown, inFunction: boolean): void => {
    if (Array.isArray(node)) {
      for (const child of node) visit(child, inFunction);
      return;
    }
    if (!node || typeof node !== "object") return;
    const n = node as { type?: string; callee?: { type: string; name?: string; property?: { name?: string } }; start?: number };
    const isFunction = n.type === "FunctionDeclaration" || n.type === "FunctionExpression" || n.type === "ArrowFunctionExpression";
    if (!inFunction && n.type === "CallExpression" && n.callee) {
      const name = n.callee.type === "Identifier" ? n.callee.name : n.callee.type === "MemberExpression" ? n.callee.property?.name : undefined;
      if (name && TIER_READERS.has(name)) found.push(`${name}() at ${n.start}`);
    }
    for (const [key, child] of Object.entries(node)) {
      if (key !== "parent" && child && typeof child === "object") visit(child, inFunction || isFunction);
    }
  };
  visit(program, false);
  return found;
}

test("the scan for import-time reads catches a top-level call, and leaves calls that run later alone", () => {
  const caught = [
    "const T = currentTiers();",
    "export const ROWS = routeClasses().map((c) => c.key);",
    "const L = { entries: legend() };",
    "const F = style.furthTiers();",
    "let x; x = furthTiers();",
  ];
  for (const source of caught) assert.equal(importTimeReads("a.ts", source).length, 1, source);
  const later = [
    "function f() { return currentTiers(); }",
    "export function g(tiers = currentTiers()) { return tiers; }",
    "const h = () => legend();",
    "const k = function () { return routeClasses(); };",
    "const o = { m() { return furthTiers(); } };",
    "class C { draw() { return currentTiers(); } }",
    "const n = currentTiersLater();",
  ];
  for (const source of later) assert.deepEqual(importTimeReads("b.ts", source), [], source);
  assert.equal(importTimeReads("c.tsx", "const E = <ul>{legend().map((e) => <li>{e.short}</li>)}</ul>;").length, 1, "in TSX too");
});

test("nothing keeps the tiers from import time: a flip would not reach it", () => {
  const dir = fileURLToPath(new URL("..", import.meta.url));
  const files = shippedSources(dir);
  assert.ok(files.length > 20, "the scan found the source");
  const offenders = files.filter((file) =>
    /\b(STRESS_TIERS|FURTH_TIERS|ROUTE_CLASSES)\b/.test(readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "")),
  );
  assert.deepEqual(offenders, []);
  const reads = files.flatMap((file) => importTimeReads(file, readFileSync(file, "utf8")).map((at) => `${file}: ${at}`));
  assert.deepEqual(reads, []);
});

test("the High contrast switch is a labelled role=switch button, with its state in words and a one-line description", () => {
  const off = renderToStaticMarkup(createElement(AccessibilitySwitch, { on: false, source: "default", paletteFromAddress: false, onChange: () => {} }));
  assert.match(off, /<button type="button" role="switch" id="a11y-switch" class="switch" aria-checked="false" aria-labelledby="a11y-label" aria-describedby="a11y-hint">/);
  assert.match(off, /<span id="a11y-label" class="switch-label">High contrast<\/span>/);
  assert.equal(ACCESSIBILITY_LABEL, "High contrast");
  assert.match(off, /<span class="switch-state" aria-hidden="true">Off<\/span>/);
  assert.match(off, new RegExp(`<p class="hint" id="a11y-hint">${ACCESSIBILITY_HINT.replace(/[.]/g, "\\.").replace(/'/g, "&#x27;")}</p>`));
  assert.ok(!ACCESSIBILITY_HINT.includes("\n") && ACCESSIBILITY_HINT.length < 120, "one line");
  const on = renderToStaticMarkup(createElement(AccessibilitySwitch, { on: true, source: "chosen", paletteFromAddress: false, onChange: () => {} }));
  assert.match(on, /aria-checked="true"/);
  assert.match(on, />On<\/span>/);
  assert.ok(!on.includes(ACCESSIBILITY_CONTRAST_NOTE) && !on.includes(ACCESSIBILITY_ADDRESS_NOTE));
});

test("the switch says so when the device's request turned it on, and when the address chose the colours", () => {
  const byContrast = renderToStaticMarkup(createElement(AccessibilitySwitch, { on: true, source: "contrast", paletteFromAddress: false, onChange: () => {} }));
  assert.ok(byContrast.includes(ACCESSIBILITY_CONTRAST_NOTE));
  const offByContrastSource = renderToStaticMarkup(createElement(AccessibilitySwitch, { on: false, source: "contrast", paletteFromAddress: false, onChange: () => {} }));
  assert.ok(!offByContrastSource.includes(ACCESSIBILITY_CONTRAST_NOTE), "no note on a switch that is off");
  const pinned = renderToStaticMarkup(createElement(AccessibilitySwitch, { on: true, source: "chosen", paletteFromAddress: true, onChange: () => {} }));
  assert.ok(pinned.includes(ACCESSIBILITY_ADDRESS_NOTE));
});

test("pressing the switch asks for the opposite state", () => {
  const got: boolean[] = [];
  for (const on of [false, true]) {
    const element = AccessibilitySwitch({ on, source: "chosen", paletteFromAddress: false, onChange: (next) => void got.push(next) });
    const button = (element.props.children as Array<{ type?: string; props?: { onClick?: () => void } }>).find((c) => c?.type === "button");
    button?.props?.onClick?.();
  }
  assert.deepEqual(got, [true, false]);
});

test("the page's root carries the class while the switch is on, and loses it when it goes off", () => {
  const calls: Array<[string, boolean]> = [];
  const root = { classList: { toggle: (name: string, force: boolean) => void calls.push([name, force]) } };
  setRootClass(root, true);
  setRootClass(root, false);
  assert.deepEqual(calls, [[ACCESSIBILITY_CLASS, true], [ACCESSIBILITY_CLASS, false]]);
  assert.equal(ACCESSIBILITY_CLASS, "a11y");
  calls.length = 0;
  const stop = followAccessibility(root);
  try {
    assert.deepEqual(calls, [["a11y", false]], "set at once, from the state at the time");
    setAccessibility(true, { remember: false });
    setAccessibility(false, { remember: false });
    assert.deepEqual(calls.slice(1), [["a11y", true], ["a11y", false]], "and kept in step");
    stop();
    setAccessibility(true, { remember: false });
    assert.equal(calls.length, 3, "stopped");
  } finally {
    stop();
    setAccessibility(false, { remember: false });
  }
});
