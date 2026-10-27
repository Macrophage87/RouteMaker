import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { ES } from "../i18n/es.ts";
import { deviceLanguage, readLanguageChoice, setLanguageForTest, speechLang, t, writeLanguageChoice } from "./i18n.ts";
import { arrivalSideWords, crossingWords, cueSpoken, endWords, exitWords, ontoWords, stopText, turnWords, type Cue } from "./navigate.ts";
import { spokenDistance } from "./format.ts";

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
    assert.equal(turnWords("right", "service road beside East-West Highway"), "Gire a la derecha hacia la vía de servicio junto a East-West Highway.");
    assert.equal(turnWords("left", null), "Gire a la izquierda.");
    assert.equal(turnWords("uturn", "R Street"), "Dé la vuelta en U.");
    assert.equal(exitWords({ number: 3, circle: "Dupont Circle" }, "P Street Northwest"), "Tome la 3.ª salida hacia P Street Northwest en Dupont Circle");
    assert.equal(exitWords({ number: 1, circle: null }, null), "Tome la 1.ª salida en la rotonda");
    assert.equal(ontoWords("Mount Vernon Trail"), "Continúe por Mount Vernon Trail.");
    assert.equal(crossingWords("C Street", "signal"), "Cruce con mucho tráfico en C Street, con semáforo.");
    assert.equal(crossingWords(null, "none"), "Cruce con mucho tráfico, sin semáforo.");
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
});
