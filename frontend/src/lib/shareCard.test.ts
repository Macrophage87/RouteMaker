// Share as image (v0.7.0): the card's sizes, layout, words, Home rule, QR rules and elevation strip.
import { test } from "node:test";
import assert from "node:assert/strict";
import qrcode from "qrcode-generator";
import { readFileSync } from "node:fs";
import type { RouteProfile } from "./api.ts";
import { haversineM, pathLengthM, type LonLat } from "./geo.ts";
import {
  CARD_SIZES,
  CARD_SIZE_DEFAULT,
  HOME_NEAR_M,
  HOME_TRIM_M,
  MIN_QR_PX,
  MIN_SMALL_TEXT_PX,
  QR_HOME_END,
  QR_NEEDS_CONNECTION,
  QR_WAITS_FOR_ROUTE,
  cardAlt,
  cardAttribution,
  cardFileName,
  cardLayout,
  cardName,
  cardRoute,
  cardSize,
  homeEnd,
  profileStrip,
  qrAvailability,
  qrFit,
  qrModules,
  sliceLine,
  statsLine,
} from "./shareCard.ts";

test("the four sizes PLAN.md names, Square first and the default", () => {
  assert.deepEqual(
    CARD_SIZES.map((s) => [s.id, s.width, s.height]),
    [
      ["square", 1080, 1080],
      ["portrait", 1080, 1350],
      ["story", 1080, 1920],
      ["landscape", 1200, 630],
    ],
  );
  assert.equal(CARD_SIZE_DEFAULT, "square");
  for (const s of CARD_SIZES) assert.match(s.label, new RegExp(`${s.width} × ${s.height}$`));
  assert.equal(cardSize("story").height, 1920);
});

test("the layout fills the card: map, band and footer stack to its height; the QR code fits the footer", () => {
  for (const size of CARD_SIZES) {
    for (const profile of ["off", "band", "map"] as const) {
      for (const qr of [false, true]) {
        const l = cardLayout(size, { name: true, qr, profile });
        const band = profile === "band" ? l.profile!.h : 0;
        assert.equal(l.map.h + band + l.footer.h, size.height, `${size.id} ${profile} ${qr}`);
        assert.ok(l.map.h > size.height / 3, `${size.id}: the map keeps most of the card`);
        assert.equal(l.footer.y + l.footer.h, size.height);
        assert.ok(l.font.credit >= MIN_SMALL_TEXT_PX && l.font.profile >= MIN_SMALL_TEXT_PX, "small text stays legible");
        if (qr) {
          assert.ok(l.qr!.w >= MIN_QR_PX && l.qr!.w === l.qr!.h);
          assert.ok(l.qr!.y + l.qr!.h <= size.height - l.pad, "inside the footer");
          assert.ok(l.text.x + l.text.w <= l.qr!.x, "the words stay left of the code");
        } else {
          assert.equal(l.qr, null);
          assert.equal(l.text.w, size.width - l.pad * 2);
        }
        if (profile === "map") {
          assert.ok(l.profile!.y + l.profile!.h <= l.map.h, "the strip is over the map");
          assert.ok(l.profile!.y > l.map.h / 2, "over its lower part");
        }
        if (profile === "off") assert.equal(l.profile, null);
      }
    }
  }
  // Scaled by the shorter side: Story's text is Square's; Landscape's is smaller but not below the floor.
  assert.equal(cardLayout(cardSize("story"), { name: false, qr: false, profile: "off" }).font.stats, 40);
  const wide = cardLayout(cardSize("landscape"), { name: false, qr: true, profile: "off" });
  assert.equal(wide.font.credit, MIN_SMALL_TEXT_PX);
  assert.equal(wide.qr!.w, MIN_QR_PX);
});

test("the footer's numbers: miles first, kilometres in brackets, the climb in feet then metres", () => {
  assert.equal(statsLine(19956, 376), "12.4 mi (20.0 km) · 1,234 ft (376 m) climb");
  assert.equal(statsLine(19956, 0), "12.4 mi (20.0 km)");
  assert.equal(statsLine(19956, null), "12.4 mi (20.0 km)");
  assert.equal(statsLine(100, undefined), "330 ft (100 m)");
});

test("the name: a file's or saved route's own, never one with Home in it", () => {
  const home = { point: [-77.03, 38.9] as LonLat, label: "1600 Elm Street" };
  assert.equal(cardName("Hains Point laps", home), "Hains Point laps");
  assert.equal(cardName("  ", home), null);
  assert.equal(cardName(null, null), null);
  assert.equal(cardName("Home to Hains Point", home), null);
  assert.equal(cardName("ride HOME", null), null);
  assert.equal(cardName("Homestead loop", null), "Homestead loop");
  assert.equal(cardName("From 1600 elm street", home), null);
});

test("the credits drawn into the image: OpenStreetMap first, the base map, and USGS with the profile", () => {
  assert.equal(cardAttribution(false), "Map: © OpenStreetMap contributors (ODbL) · Protomaps");
  assert.equal(cardAttribution(true), "Map: © OpenStreetMap contributors (ODbL) · Protomaps · Elevation: USGS 3DEP");
});

const STRIP = { x: 10, y: 100, w: 200, h: 50 };
const PROFILE: RouteProfile = {
  interval_m: 100,
  m: [0, 100, 200, 300, 400],
  elevation_m: [10, 20, null, 40, 30],
  grade_pct: [null, null, null, null, null],
  climbs: [],
} as unknown as RouteProfile;

test("the preview's text says the route, the marks, the profile and the QR code", () => {
  const strip = profileStrip(PROFILE, STRIP);
  const alt = cardAlt({ name: null, distanceM: 19956, climbM: 376, stops: 2, startShown: true, finishShown: true, profile: strip, qr: true });
  assert.equal(
    alt,
    "Route map, 12.4 mi (20.0 km), 1,234 ft (376 m) climb. Marked: start, 2 stops, finish. Elevation profile from 33 ft (10 m) to 131 ft (40 m). QR code to the shared link. RouteMaker. Map: © OpenStreetMap contributors (ODbL) · Protomaps · Elevation: USGS 3DEP.",
  );
  const bare = cardAlt({ name: "Laps", distanceM: 19956, climbM: 0, stops: 0, startShown: false, finishShown: true, profile: null, qr: false });
  assert.match(bare, /^Route map, "Laps", 12\.4 mi \(20\.0 km\)\. Marked: finish\. RouteMaker\./);
  assert.doesNotMatch(bare, /QR|Elevation profile|Home/);
});

test("the elevation strip: lowest at the bottom, highest at the top, split at a gap, labelled ft (m)", () => {
  const s = profileStrip(PROFILE, STRIP)!;
  assert.equal(s.minM, 10);
  assert.equal(s.maxM, 40);
  assert.equal(s.minLabel, "33 ft (10 m)");
  assert.equal(s.maxLabel, "131 ft (40 m)");
  assert.deepEqual(s.runs, [
    [
      [10, 150],
      [60, 150 - 50 / 3],
    ],
    [
      [160, 100],
      [210, 100 + 50 / 3],
    ],
  ]);
  // Flat: in the middle.
  const flat = profileStrip({ ...PROFILE, elevation_m: [5, 5, 5, 5, 5] }, STRIP)!;
  assert.ok(flat.runs[0].every(([, y]) => y === 125));
  // Cut at both ends: only the drawn part, stretched over the box.
  const cut = profileStrip(PROFILE, STRIP, 0.25, 0.25)!;
  assert.equal(cut.minM, 20);
  assert.equal(cut.maxM, 40);
  assert.deepEqual(cut.runs, []);
  assert.equal(profileStrip({ ...PROFILE, elevation_m: [null, null, 3, null, null] }, STRIP), null);
});

// A straight line north, about 111 m a step, 2.2 km long.
const LINE: LonLat[] = Array.from({ length: 21 }, (_, i) => [-77.0, 38.9 + i * 0.001] as LonLat);
const LENGTH = pathLengthM(LINE);

test("sliceLine cuts the line where the distances fall", () => {
  const part = sliceLine(LINE, 300, LENGTH - 300);
  assert.ok(Math.abs(pathLengthM(part) - (LENGTH - 600)) < 0.5);
  assert.ok(Math.abs(haversineM(LINE[0], part[0]) - 300) < 0.5);
  assert.deepEqual(sliceLine(LINE, 0, LENGTH), LINE);
});

test("Home: an end within 300 m of it has no pin, and the line is cut 0.2 mi short there", () => {
  const points: LonLat[] = [LINE[0], LINE[10], LINE[20]];
  const none = cardRoute(LINE, points, null)!;
  assert.deepEqual(none.line, LINE);
  assert.deepEqual([none.start, none.finish, none.stops], [LINE[0], LINE[20], [LINE[10]]]);
  assert.equal(none.cutStart, 0);

  // Home 250 m from the start (inside HOME_NEAR_M).
  const near = { point: [-77.0, 38.9 - 250 / 111_195] as LonLat, label: "Somewhere" };
  assert.ok(haversineM(near.point, LINE[0]) < HOME_NEAR_M);
  const r = cardRoute(LINE, points, near)!;
  assert.equal(r.start, null);
  assert.deepEqual(r.finish, LINE[20]);
  assert.ok(Math.abs(haversineM(LINE[0], r.line[0]) - HOME_TRIM_M) < 0.5, "cut 0.2 mi from the start");
  assert.ok(Math.abs(HOME_TRIM_M - 321.9) < 0.1);
  assert.ok(Math.abs(r.cutStart - HOME_TRIM_M / LENGTH) < 1e-6);
  assert.equal(r.cutEnd, 0);
  // Nothing drawn is within the cut of Home.
  assert.ok(r.line.every((p) => haversineM(p, LINE[0]) >= HOME_TRIM_M - 0.5));
  assert.equal(homeEnd(LINE, points, near), true);

  // A loop from Home: both ends cut, no start or finish pin, a stop at Home has none either.
  const loopLine = [...LINE, ...LINE.slice(0, -1).reverse()];
  const atHome = { point: LINE[0], label: "Home" };
  const loop = cardRoute(loopLine, [LINE[0], LINE[0], LINE[20], LINE[0]], atHome)!;
  assert.equal(loop.start, null);
  assert.equal(loop.finish, null);
  assert.deepEqual(loop.stops, [LINE[20]]);
  assert.ok(loop.line.every((p) => haversineM(p, LINE[0]) >= HOME_TRIM_M - 0.5));

  // Home 400 m away is not near: nothing cut.
  const far = { point: [-77.0, 38.9 - 400 / 111_195] as LonLat, label: "x" };
  assert.deepEqual(cardRoute(LINE, points, far)!.line, LINE);
  assert.equal(homeEnd(LINE, points, far), false);

  // Too short to draw without showing Home.
  const short = [...LINE.slice(0, 4), ...LINE.slice(0, 3).reverse()];
  assert.equal(cardRoute(short, [short[0], short[0]], { point: short[0], label: "" }), null);
});

test("the QR code: refused at Home, offline, or while the route is planning; otherwise available", () => {
  assert.deepEqual(qrAvailability({ online: true, settled: true, homeEnd: false }), { ok: true });
  assert.deepEqual(qrAvailability({ online: false, settled: true, homeEnd: false }), { ok: false, why: QR_NEEDS_CONNECTION });
  assert.deepEqual(qrAvailability({ online: true, settled: false, homeEnd: false }), { ok: false, why: QR_WAITS_FOR_ROUTE });
  assert.deepEqual(qrAvailability({ online: false, settled: false, homeEnd: true }), { ok: false, why: QR_HOME_END });
});

test("the QR code's modules and their fit, with the quiet zone", () => {
  const qr = qrcode(0, "M");
  const link = "https://example.org/#p=-77.03,38.9;-77.01,38.91&preset=group&route=0123456789abcdef0123456789abcdef";
  qr.addData(link);
  qr.make();
  const modules = qrModules(qr);
  assert.equal(modules.length, qr.getModuleCount());
  assert.ok(modules.length >= 21 && modules.every((row) => row.length === modules.length));
  // The finder pattern's corner is dark.
  assert.equal(modules[0][0], true);
  const fit = qrFit(modules.length, 240);
  assert.ok(fit.cell >= 2);
  assert.ok(fit.offset >= 4 * fit.cell, "4 modules of quiet zone");
  assert.ok(fit.offset * 2 + fit.cell * modules.length <= 240);
});

test("the file's name", () => {
  assert.equal(cardFileName("story"), "routemaker-story.png");
});

// The dialog and App's wiring are read as source, as the other App tests are (no DOM here).
const dialog = readFileSync(new URL("../ShareCardDialog.tsx", import.meta.url), "utf8");
const render = readFileSync(new URL("../app/shareCardRender.ts", import.meta.url), "utf8");

test("the dialog: labelled, the focus in and back, labelled controls, alt text, a polite region of its own", () => {
  assert.match(dialog, /<dialog\s+ref=\{dialogRef\}\s+className="share-card-dialog"\s+aria-labelledby=\{`\$\{id\}-heading`\}/);
  assert.match(dialog, /dialog\.showModal\?\.\(\);\s*headingRef\.current\?\.focus\(\);/);
  assert.match(dialog, /if \(opener\.current instanceof HTMLElement && opener\.current\.isConnected\) opener\.current\.focus\(\);/);
  for (const field of ["size", "profile", "onmap", "qr"]) assert.match(dialog, new RegExp(`<label htmlFor=\\{\`\\$\\{id\\}-${field}\`\\}>`), field);
  assert.match(dialog, /<img src=\{preview\.url\} alt=\{preview\.alt\} \/>/);
  // Inside the modal, always rendered: the page's own region is inert while it is open.
  assert.match(dialog, /<p className="visually-hidden" role="status">\s*\{said\.text\}/);
  assert.match(dialog, /say\(IMAGE_READY\);/);
  assert.match(dialog, /say\(IMAGE_FAILED\);/);
  // Unavailable QR code and profile: disabled, with the reason as their description.
  assert.match(dialog, /disabled=\{qrDisabled\}\s*aria-describedby=\{qrWhy \? `\$\{id\}-qr-why` : undefined\}/);
  assert.match(dialog, /disabled=\{!hasProfile\}\s*aria-describedby=\{hasProfile \? undefined : `\$\{id\}-profile-why`\}/);
  // Defaults: Square, the profile on in its band, the QR code off.
  assert.match(dialog, /useState<CardSizeId>\(CARD_SIZE_DEFAULT\)/);
  assert.match(dialog, /const \[profileOn, setProfileOn\] = useState\(true\);/);
  assert.match(dialog, /const \[onMap, setOnMap\] = useState\(false\);/);
  assert.match(dialog, /const \[qrOn, setQrOn\] = useState\(false\);/);
  // Share only where the browser can share the image file.
  assert.match(dialog, /navigator\.canShare\(\{ files: \[file\] \}\)/);
  assert.match(dialog, /\{shareable && \(/);
});

test("App: Share as image in Plan only, given Home to hide and the QR code's link made as Share's", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /open=\{shareCardOpen && shareCardSource !== null && mode !== "go" && !riding\}/);
  assert.match(app, /home: myGo\.home,/);
  assert.match(app, /name: imported\?\.name \?\? null,/);
  assert.match(app, /makeLink=\{shareCardLink\}/);
  assert.match(app, /shareImage: \(\) => setShareCardOpen\(true\)/);
  // Go has no entry point.
  const go = readFileSync(new URL("../app/Go.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(go, /shareImage|SHARE_IMAGE_LABEL/);
});

test("the drawing: an offscreen map at the card's size with no rider markers; pins carry no names", () => {
  assert.match(render, /pixelRatio: 1,/);
  assert.match(render, /canvasContextAttributes: \{ preserveDrawingBuffer: true/);
  assert.match(render, /interactive: false,/);
  // Only the base map and the card's own line: no stress overlay, no Home, no saved places.
  const code = render.replace(/^\s*\/\/.*$/gm, "");
  assert.doesNotMatch(code, /stressSource|STRESS_SOURCE_ID|myGo|home\b|Home\b/);
  assert.match(render, /pin\(ctx, drawn\.start\.x, drawn\.start\.y, r, START, "S"\)/);
  assert.match(render, /pin\(ctx, drawn\.finish\.x, drawn\.finish\.y, r, FINISH, "F", true\)/);
  assert.match(render, /cardAttribution\(strip !== null\)/);
});
