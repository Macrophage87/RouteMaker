// The rider-facing page on how traffic-stress ratings work (OWNER-DECISIONS 461): a static page in
// public/, served by both edges at STRESS_PAGE. Its structure is held here; the browser a11y suite
// (scripts/a11y/check.mjs) checks it at 320 px.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { STRESS_PAGE } from "./stressLegend.ts";

// The road panel's words for each level (src/core/segment_info.py, TIER_WORDS; OWNER-DECISIONS 441l).
const PANEL_WORDS = [
  "Comfortable for everyone",
  "Fine for adults",
  "For experienced cyclists",
  "High stress: busy, fast traffic",
  "Avoid",
];

const page = readFileSync(new URL(`../../public${STRESS_PAGE}`, import.meta.url), "utf8");
const text = page.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");

test("the page is a whole document in English, with a title and a viewport", () => {
  assert.match(page, /^<!doctype html>\n<html lang="en">/);
  assert.match(page, /<title>[^<]+<\/title>/);
  assert.match(page, /<meta name="viewport" content="width=device-width, initial-scale=1">/);
});

test("it runs no script and loads nothing from another host (the app's content security policy)", () => {
  assert.doesNotMatch(page, /<script/i);
  assert.doesNotMatch(page, /\b(src|href)="(https?:)?\/\//i);
  assert.doesNotMatch(page, /@import|url\(/i);
});

test("one h1, and no heading skips a level", () => {
  const levels = [...page.matchAll(/<h([1-6])[\s>]/g)].map((m) => Number(m[1]));
  assert.equal(levels.filter((l) => l === 1).length, 1);
  assert.equal(levels[0], 1);
  for (let i = 1; i < levels.length; i++) assert.ok(levels[i] <= levels[i - 1] + 1, `h${levels[i - 1]} then h${levels[i]}`);
});

test("it has the landmarks a screen reader moves by, and a skip link to the content", () => {
  for (const tag of ["header", "nav", "main", "footer"]) assert.match(page, new RegExp(`<${tag}[\\s>]`), tag);
  assert.match(page, /<a class="skip" href="#main">/);
  assert.match(page, /<main id="main">/);
  for (const [, id] of page.matchAll(/href="#([^"]+)"/g)) assert.match(page, new RegExp(`id="${id}"`), `#${id}`);
});

test("every swatch is hidden from a screen reader, and each level is named in the road panel's words beside it", () => {
  const swatches = [...page.matchAll(/<svg[^>]*>/g)].map((m) => m[0]);
  assert.equal(swatches.length, 5);
  for (const svg of swatches) assert.match(svg, /aria-hidden="true"/);
  for (const words of PANEL_WORDS) assert.ok(text.includes(words), words);
});

test("US units first, metric in brackets", () => {
  assert.match(text, /0\.1 mile \[160 m\]/);
  assert.match(text, /1,200 feet \[370 m\]/);
  assert.doesNotMatch(text, /\b\d+ (m|km)\b(?![^[]*\])/, "a metric figure outside brackets");
});

test("the sources are credited in text", () => {
  for (const credit of ["OpenStreetMap contributors", "DC Open Data", "VDOT", "Montgomery County Planning Department", "Open Baltimore", "U.S. Census Bureau", "Furth"]) {
    assert.ok(text.includes(credit), credit);
  }
});

test("what is not built is marked planned", () => {
  assert.match(text, /Half steps and the stress chart \(planned\)/);
  assert.match(text, /Planned, not built yet\./);
});
