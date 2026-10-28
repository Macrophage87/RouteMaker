import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { ES } from "../i18n/es.ts";
import { firstWordAndRest, deviceLanguage, readLanguageChoice, setLanguageForTest, speechLang, t, writeLanguageChoice } from "./i18n.ts";
import { arrivalSideWords, crossingWords, cueSpoken, endWords, exitWords, ontoWords, stopText, turnWords, type Cue } from "./navigate.ts";
import { spokenDistance } from "./format.ts";
import * as navigate from "./navigate.ts";
import { OUTPUT_LABELS } from "./rideOutput.ts";
import { PRESETS, presetLabel, presetSaid } from "./presets.ts";
import { REPORT_KINDS } from "./report311.ts";
import { kindLabel, kindShown } from "./report311Log.ts";
import { CUISINE_WORDS, foodKindText, type FoodPlace } from "./food.ts";
import { MASS_BANDS } from "../massStyle.js";

const SRC = fileURLToPath(new URL("..", import.meta.url));

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

/** Every phrase the code passes to t() as it is written: t("...") with a plain string. */
function markedPhrases(): Map<string, string> {
  const found = new Map<string, string>();
  for (const path of sources(SRC)) {
    for (const m of readFileSync(path, "utf8").matchAll(/\bt\("((?:[^"\\]|\\.)*)"/g)) found.set(JSON.parse(`"${m[1]}"`), path);
  }
  return found;
}

const places = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

test("every phrase the code marks has its Spanish, with the same {places}", () => {
  const phrases = markedPhrases();
  assert.ok(phrases.size > 250, `${phrases.size} phrases marked`);
  const missing = [...phrases].filter(([english]) => !(english in ES)).map(([english, path]) => `${english} (${path})`);
  assert.deepEqual(missing, []);
  for (const [english, spanish] of Object.entries(ES)) assert.deepEqual(places(spanish), places(english), english);
});

test("t: the language's phrase, its places filled; English, or a phrase not in the list, as written", () => {
  assert.equal(t("Stop {number}, {name}.", { number: 2, name: "Union Market" }, "en"), "Stop 2, Union Market.");
  assert.equal(t("Stop {number}, {name}.", { number: 2, name: "Union Market" }, "es"), "Parada 2, Union Market.");
  assert.equal(t("Not a phrase in the list", undefined, "es"), "Not a phrase in the list");
  // A name holding braces is left as it is: places are filled once.
  assert.equal(t("To {place}", { place: "{odd}" }, "es"), "A {odd}");
});

test("the language: the rider's choice, else the device's first language the app has, else English", () => {
  const kept = new Map<string, string>();
  const store = { getItem: (k: string) => kept.get(k) ?? null, setItem: (k: string, v: string) => void kept.set(k, v) };
  assert.equal(readLanguageChoice(store), "");
  writeLanguageChoice("es", store);
  assert.equal(readLanguageChoice(store), "es");
  writeLanguageChoice("", store);
  assert.equal(readLanguageChoice(store), "");
  assert.equal(deviceLanguage(["es-US", "en-US"]), "es");
  assert.equal(deviceLanguage(["fr-FR", "es-MX"]), "es");
  assert.equal(deviceLanguage(["fr-FR"]), "en");
  assert.equal(deviceLanguage(undefined), "en");
  assert.equal(speechLang("es"), "es-US");
  assert.equal(speechLang("en"), "en-US");
});

test("Spanish turn directions are whole Spanish sentences, the street names as they are", () => {
  setLanguageForTest("es");
  try {
    assert.equal(turnWords("left", "R Street Northwest"), "Gire a la izquierda hacia R Street Northwest.");
    assert.equal(turnWords("bear_right", "Paint Branch Trail", true), "Manténgase a la derecha para seguir en Paint Branch Trail.");
    assert.equal(turnWords("right", "unnamed path"), "Gire a la derecha hacia el sendero.");
    assert.equal(turnWords("right", "path", false, null, "Rock Creek Trail"), "Gire a la derecha hacia el sendero que lleva a Rock Creek Trail.");
    assert.equal(turnWords("right", "service road beside East-West Highway"), "Gire a la derecha hacia la vía de servicio junto a East-West Highway.");
    assert.equal(turnWords("left", null), "Gire a la izquierda.");
    // A bear is a turn, not "keep" (manténgase is only for staying on a way at a fork).
    assert.equal(turnWords("bear_left", "Rhode Island Avenue"), "Gire ligeramente a la izquierda hacia Rhode Island Avenue.");
    // The API's way names are said in Spanish in a crossing too.
    assert.equal(crossingWords("sidewalk beside Georgia Avenue", "none"), "Intersección con mucho tráfico en la acera junto a Georgia Avenue, sin semáforo.");
    assert.equal(turnWords("uturn", "R Street"), "Dé la vuelta en U.");
    assert.equal(exitWords({ number: 3, circle: "Dupont Circle" }, "P Street Northwest"), "Tome la 3.ª salida hacia P Street Northwest en Dupont Circle");
    assert.equal(exitWords({ number: 1, circle: null }, null), "Tome la 1.ª salida en la rotonda");
    assert.equal(ontoWords("Mount Vernon Trail"), "Continúe por Mount Vernon Trail.");
    assert.equal(crossingWords("C Street", "signal"), "Intersección con mucho tráfico en C Street, con semáforo.");
    assert.equal(crossingWords(null, "none"), "Intersección con mucho tráfico, sin semáforo.");
    assert.equal(endWords("right"), "El final de la ruta. El destino está a su derecha.");
    assert.equal(stopText(2, "Union Market"), "Parada 2, Union Market.");
    assert.equal(spokenDistance(150), "500 pies");
    assert.equal(spokenDistance(1609.344 * 2.5), "2.5 millas");
    const cue = { index: 0, kind: "turn", atM: 0, text: turnWords("left", "R Street"), movement: "left", street: "R Street", severity: "red", tier: null, stop: null } as Cue;
    assert.equal(cueSpoken(cue, "now", 0), "Gire a la izquierda ahora hacia R Street.");
    assert.equal(cueSpoken(cue, "advance", 150), "En 500 pies, gire a la izquierda hacia R Street. Intersección con mucho tráfico.");
    const end = { index: 1, kind: "end", atM: 0, text: endWords("left"), movement: null, street: null, severity: null, tier: null, stop: null } as Cue;
    assert.equal(cueSpoken(end, "arrive", 0), `Ha llegado al final de la ruta. ${arrivalSideWords("left")}`);
  } finally {
    setLanguageForTest("en");
  }
});

test("English is unchanged by the lookup", () => {
  assert.equal(turnWords("left", "R Street Northwest"), "Left onto R Street Northwest.");
  assert.equal(turnWords("right", "unnamed path"), "Right onto the path.");
  assert.equal(crossingWords("C Street", "signal"), "Busy crossing at C Street, signal.");
  assert.equal(crossingWords(null, undefined), "Busy crossing.");
  assert.equal(exitWords({ number: 3, circle: "Dupont Circle" }, "P Street Northwest"), "Take the 3rd exit onto P Street Northwest at Dupont Circle");
  assert.equal(spokenDistance(150), "500 feet");
  assert.equal(crossingWords("sidewalk beside Georgia Avenue", "none"), "Busy crossing at sidewalk beside Georgia Avenue, no signal.");
});

test("every off-route, re-plan, weak-GPS and back-on-route sentence Ride says has its Spanish (routing audit D4)", () => {
  // Module constants are made once at load (in English here), so each one's English is looked up in the catalog.
  const said = Object.entries(navigate).filter(([name, value]) => /_SAID$|^REPLAN_/.test(name) && typeof value === "string") as [string, string][];
  for (const name of ["OFF_ROUTE_SAID", "OFF_ROUTE_KEPT_SAID", "BACK_ON_ROUTE_SAID", "GPS_WEAK_SAID", "CUE_SHEET_SAID", "REPLAN_NO_AHEAD", "REPLAN_FINDING"])
    assert.ok(said.some(([n]) => n === name), name);
  assert.deepEqual(said.filter(([, english]) => !(english in ES)).map(([name]) => name), []);
  const labels = [...Object.values(navigate.VERBOSITY_LABELS), ...Object.values(OUTPUT_LABELS)];
  assert.deepEqual(labels.filter((english) => !(english in ES)), []);
  // A level's short label is its name before the colon (lib/shortLabel.ts), in Spanish too.
  for (const english of Object.values(navigate.VERBOSITY_LABELS)) assert.match(ES[english], /^[^:]+: /, english);
  assert.equal(t("In {distance}", { distance: "0.4 mi (0.6 km)" }, "es"), "En 0.4 mi (0.6 km)");
  assert.equal(t("Then in {distance}", { distance: "0.4 mi (0.6 km)" }, "es"), "Luego en 0.4 mi (0.6 km)");
});

test("a narrow button's first word and the rest, in either language", () => {
  assert.deepEqual(firstWordAndRest("Save route"), ["Save", " route"]);
  assert.deepEqual(firstWordAndRest(t("Start ride", undefined, "es")), ["Iniciar", " recorrido"]);
  assert.deepEqual(firstWordAndRest("Loop"), ["Loop", ""]);
});

test("the words shown from lists (ride types, 311 problems, cuisines, capacity bands) have their Spanish (the 2026-10-28 audit, P9)", () => {
  const listed = [
    ...PRESETS.flatMap((p) => [p.label, p.summary, p.description, ...(p.spoken ? [p.spoken] : [])]),
    ...REPORT_KINDS.map((k) => k.label),
    ...CUISINE_WORDS,
    ...MASS_BANDS.flatMap((b: { name: string; short: string }) => [b.name, b.short]),
  ];
  assert.deepEqual(listed.filter((english) => !(english in ES)), []);
});

test("Spanish shows the Spanish, and what is sent or kept stays English (P9)", () => {
  const place = { id: "n1", lon: -77, lat: 38.9, kind: "r", name: "Alta Strada", cuisine: ["italian", "kosher"] } as FoodPlace;
  setLanguageForTest("es");
  try {
    assert.equal(presetLabel("group-ride"), "Paseo en grupo");
    assert.equal(presetSaid("bike-transit"), "Bicicleta propia más tren o autobús");
    // A 311 report's words are DC's, in English; the button the rider presses is in Spanish.
    assert.equal(kindLabel("pothole"), "Pothole");
    assert.equal(kindShown("pothole"), "Bache");
    // OSM's cuisine values in words; one with no Spanish word is left out, not shown raw. (The kind's label is made
    // at load, in English here.)
    assert.equal(foodKindText(place), "Restaurant: italiano");
  } finally {
    setLanguageForTest("en");
  }
  assert.equal(presetLabel("group-ride"), "Group Ride");
  assert.equal(foodKindText(place), "Restaurant: italian, kosher");
});
