import { test } from "node:test";
import assert from "node:assert/strict";
import { segmentClass, segmentStyle, stressSegments } from "./stressBar.ts";
import { appSource } from "../testSupport/appSource.mjs";

const sample = { "1": 1800, "2": 0, "3": 2630, "4": 1040, unknown: 10 };

test("fractions sum to one and follow the metres", () => {
  const segments = stressSegments(sample);
  const total = segments.reduce((sum, s) => sum + s.fraction, 0);
  assert.ok(Math.abs(total - 1) < 1e-9, `fractions sum to ${total}`);
  for (const s of segments) {
    assert.ok(Math.abs(s.fraction - s.metres / 5480) < 1e-9, s.key);
  }
});

test("rounded percentages always add up to one hundred", () => {
  const awkward = [
    { "1": 1, "2": 1, "3": 1, "4": 0, unknown: 0 },
    { "1": 333, "2": 333, "3": 334, "4": 0, unknown: 0 },
    { "1": 0.4, "2": 0.4, "3": 0.2, "4": 99, unknown: 0.1 },
    { "1": 255, "2": 255, "3": 490, "4": 0, unknown: 0 },
    sample,
  ];
  for (const stress of awkward) {
    const sum = stressSegments(stress).reduce((acc, s) => acc + s.percent, 0);
    assert.equal(sum, 100, JSON.stringify(stress));
  }
});

test("every tier and the unrated remainder are present, in tier order", () => {
  const keys = stressSegments(sample).map((s) => s.key);
  assert.deepEqual(keys, ["1", "2", "3", "4", "5", "unknown"]);
});

test("each segment carries a label, so the bar does not rely on colour", () => {
  for (const s of stressSegments(sample)) {
    assert.ok(s.label.length > 0 && s.short.length > 0, s.key);
    assert.match(s.color, /^#[0-9a-f]{6}$/i);
  }
});

test("a route with no metres gives no segments rather than NaN", () => {
  assert.deepEqual(stressSegments({ "1": 0, "2": 0, "3": 0, "4": 0, unknown: 0 }), []);
});

test("missing, negative or non-numeric values count as zero", () => {
  const segments = stressSegments({ "1": 100, "2": -50, "3": Number.NaN } as never);
  const byKey = Object.fromEntries(segments.map((s) => [s.key, s]));
  assert.equal(byKey["1"].fraction, 1);
  assert.equal(byKey["2"].metres, 0);
  assert.equal(byKey["3"].metres, 0);
  assert.equal(byKey["4"].metres, 0);
});

test("the tier colours are the overlay's own, but Avoid is the route's magenta (397)", async () => {
  const { currentTiers } = await import("../stressStyle.js");
  const segments = stressSegments(sample);
  for (const tier of currentTiers().filter((t: { tier: number }) => t.tier < 5)) {
    const segment = segments.find((s) => s.key === String(tier.tier));
    assert.equal(segment?.color, tier.color);
  }
});

test("each percent is its own share rounded, and an empty tier reads 0%", () => {
  const cases = [
    sample,
    { "1": 255, "2": 255, "3": 490, "4": 0, unknown: 0 },
    { "1": 1, "2": 1, "3": 1, "4": 0, unknown: 0 },
    { "1": 994, "2": 3, "3": 3, "4": 0, unknown: 0 },
  ];
  for (const stress of cases) {
    for (const s of stressSegments(stress)) {
      assert.ok(Math.abs(s.percent - s.fraction * 100) < 1, `${JSON.stringify(stress)} ${s.key}`);
      if (s.metres === 0) assert.equal(s.percent, 0, `${JSON.stringify(stress)} ${s.key}`);
    }
  }
});

test("Avoid in the route panel's bar is the route's magenta in every palette, with a near-black hatch 3:1 from it (397; r3 spec SF-1)", async () => {
  const { contrastRatio, currentTiers, setAccessibility } = await import("../stressStyle.js");
  const { ROUTE_AVOID_HALO, ROUTE_AVOID_MAGENTA, routeClasses } = await import("./routeColours.ts");
  const { readFileSync } = await import("node:fs");
  for (const on of [false, true]) {
    setAccessibility(on, { remember: false });
    try {
      const segments = stressSegments({ "2": 100, "5": 50 });
      const avoid = segments.find((s) => s.key === "5")!;
      assert.equal(avoid.color, ROUTE_AVOID_MAGENTA, on ? "high contrast" : "default");
      assert.equal(avoid.color, routeClasses().find((c) => c.key === "5")?.color, "the route line's Avoid");
      assert.equal(avoid.casing, ROUTE_AVOID_HALO, "the hatch, as the route chart's strip draws it");
      assert.ok(contrastRatio(avoid.casing, avoid.color) >= 3, `${contrastRatio(avoid.casing, avoid.color).toFixed(2)}:1`);
      // The other tiers keep the palette's colours.
      for (const tier of currentTiers().filter((t: { tier: number }) => t.tier < 5)) {
        assert.equal(segments.find((s) => s.key === String(tier.tier))?.color, tier.color);
      }
    } finally {
      setAccessibility(false, { remember: false });
    }
  }
  // The cue that is not colour: the bar's Avoid segment is cross-hatched in its accent.
  const css = readFileSync(new URL("../styles.css", import.meta.url), "utf8");
  const body = css.match(/\n\.stress-seg-5 \{([^}]*)\}/)?.[1] ?? "";
  assert.match(body, /repeating-linear-gradient\(45deg, var\(--seg-accent/);
  assert.match(body, /repeating-linear-gradient\(-45deg, var\(--seg-accent/);
  // And App gives the bar's segments their accent.
  assert.match(appSource(), /stress-seg \$\{segmentClass\(s\)\}`\}\s*style=\{\{ width: `\$\{s\.fraction \* 100\}%`, \.\.\.segmentStyle\(s\) \}\}/);
  assert.equal(segmentStyle({ color: "#000000", casing: "#111111" })["--seg-accent"], "#111111");
});

test("a route with no Avoid lists Avoid at 0% in the palette's own colour, the magenta only where the palette's Avoid is it (397 \"only if a route uses it\"; r4 spec S-SF1; 2026-10-31)", async () => {
  const { currentTiers, setAccessibility } = await import("../stressStyle.js");
  const { ROUTE_AVOID_HALO, ROUTE_AVOID_MAGENTA } = await import("./routeColours.ts");
  for (const on of [false, true]) {
    setAccessibility(on, { remember: false });
    try {
      const palette = currentTiers().find((t: { tier: number }) => t.tier === 5)!;
      for (const stress of [{ "1": 100, "2": 50 }, { "1": 100, "5": 0 }, { "2": 10, "5": -3 }]) {
        const avoid = stressSegments(stress).find((s) => s.key === "5")!;
        assert.equal(avoid.percent, 0, JSON.stringify(stress));
        // The default palette's Avoid is the route's magenta since 2026-10-31; the cool palette's is its own.
        assert.equal(avoid.color === ROUTE_AVOID_MAGENTA, !on, JSON.stringify(stress));
        assert.equal(avoid.color, palette.color, JSON.stringify(stress));
        assert.equal(avoid.casing, palette.casing);
        assert.notEqual(avoid.casing, ROUTE_AVOID_HALO);
      }
      // A metre of Avoid is enough for the magenta.
      assert.equal(stressSegments({ "1": 100_000, "5": 1 }).find((s) => s.key === "5")!.color, ROUTE_AVOID_MAGENTA);
    } finally {
      setAccessibility(false, { remember: false });
    }
  }
});

// The owner, 2026-10-31 ("Yes, own colours in bar"): "The bar under a route, the ride summary and post pages get the
// half-step colours, so a 3.5 stretch is orange there too."
const span = (from_m: number, to_m: number, tier: number | null, half?: boolean) => ({ from_m, to_m, tier, facility: null, ...(half ? { half } : {}) });
const halfSpans = [span(0, 400, 1), span(400, 500, 1, true), span(500, 700, 2, true), span(700, 900, 3), span(900, 1500, 3, true), span(1500, 1700, 4, true), span(1700, 1800, 5), span(1800, 1850, null)];

test("a 3.5 stretch is orange in the bar, as on the line", async () => {
  const { spanClass } = await import("./routeColours.ts");
  // stress_m counts the 3.5 as LTS 3; the sections say it is a half step.
  const segments = stressSegments({ "1": 500, "2": 200, "3": 800, "4": 200, "5": 100, unknown: 50 }, halfSpans);
  const bar = segments.find((s) => s.key === "3h")!;
  assert.equal(bar.color, "#f28c28", "the default palette's 3.5 orange");
  assert.equal(bar.color, spanClass(span(900, 1500, 3, true)).color, "the route line's colour for it");
  assert.equal(bar.metres, 600);
  assert.equal(segments.find((s) => s.key === "3")!.metres, 200, "LTS 3 holds only the whole-level stretch");
});

test("every level in the bar is the route line's colour for it, half steps too, in the default and the colour-blind-friendly palettes", async () => {
  const { routeClasses } = await import("./routeColours.ts");
  const { setAccessibility } = await import("../stressStyle.js");
  for (const on of [false, true]) {
    setAccessibility(on, { remember: false });
    try {
      const classes = new Map(routeClasses().map((c) => [c.key as string, c]));
      const segments = stressSegments({}, halfSpans);
      for (const key of ["1", "1h", "2h", "3", "3h", "4h", "5", "unknown"]) {
        const seg = segments.find((s) => s.key === key)!;
        assert.equal(seg.color, classes.get(key)!.color, `${on ? "colour-blind" : "default"} ${key}`);
        if (key.endsWith("h")) {
          // The colour-blind palette's cue that is not colour: the next level's dash, as the line has it.
          assert.equal(seg.dash, classes.get(key)!.halfDash, `${key}'s dash`);
          assert.equal(seg.dashOutline, classes.get(key)!.halfOutline, `${key}'s dash outline`);
          assert.equal(segmentClass(seg).includes("stress-seg-dashed"), on, `${key} dashed only where it has no colour of its own`);
        }
      }
    } finally {
      setAccessibility(false, { remember: false });
    }
  }
});

test("half steps sit after their lower level in the bar, and only those ridden are listed", () => {
  const keys = stressSegments({}, [span(0, 100, 2), span(100, 300, 3, true), span(300, 400, 4)]).map((s) => s.key);
  assert.deepEqual(keys, ["1", "2", "3", "3h", "4", "5", "unknown"]);
  // No sections (an older API or answer): the whole-level totals, as before.
  assert.deepEqual(stressSegments(sample, undefined).map((s) => s.key), ["1", "2", "3", "4", "5", "unknown"]);
  assert.deepEqual(stressSegments(sample, []).map((s) => s.metres), stressSegments(sample).map((s) => s.metres));
});

test("the bar's key and screen-reader text name a half step (LTS 3.5)", async () => {
  const { stressBarKey, stressBarLabel } = await import("./quickFigures.ts");
  const segments = stressSegments({}, [span(0, 400, 3), span(400, 1000, 3, true)]);
  assert.equal(stressBarKey(segments), "LTS 3: 40%, LTS 3.5: 60%");
  assert.equal(stressBarLabel(segments), "LTS 3, for experienced cyclists: 40 percent; LTS 3.5, stressful even for experienced cyclists: 60 percent");
});

test("a dashed half step's stripe takes the segment's own dash colours (styles.css .stress-seg-dashed)", async () => {
  assert.deepEqual(segmentStyle({ color: "#111111", casing: "#222222", dash: "#123456", dashOutline: "#ffffff" }), {
    backgroundColor: "#111111",
    "--seg-accent": "#222222",
    "--seg-dash": "#123456",
    "--seg-dash-outline": "#ffffff",
  });
  const { readFileSync } = await import("node:fs");
  const css = readFileSync(new URL("../styles.css", import.meta.url), "utf8");
  assert.match(css, /\n\.stress-seg-dashed \{[^}]*var\(--seg-dash\)[^}]*var\(--seg-dash-outline, transparent\)/);
  // A half step keeps its lower level's pattern.
  for (const level of [2, 3, 4]) assert.match(css, new RegExp(`\\n\\.stress-seg-${level},\\n\\.stress-seg-${level}h \\{`));
});

test("the post page's bar is built from the answer's sections, and it and the ride summary draw half steps as the panel does", async () => {
  const { readFileSync } = await import("node:fs");
  const post = readFileSync(new URL("../post/postPage.tsx", import.meta.url), "utf8");
  assert.match(post, /stressSegments\(answer\.stress_m, answer\.stress_spans\)/);
  const summary = readFileSync(new URL("../RideSummaryCard.tsx", import.meta.url), "utf8");
  for (const [name, source] of [["post", post], ["summary", summary]]) {
    assert.match(source, /className=\{`stress-seg \$\{segmentClass\(s\)\}`\}\s*style=\{\{ width: `\$\{s\.fraction \* 100\}%`, \.\.\.segmentStyle\(s\) \}\}/, name);
  }
});
