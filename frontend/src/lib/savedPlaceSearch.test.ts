// Home, Work and favorites named in Go's Where to? (lib/savedPlaceSearch.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import { savedPlacesFor, SAVED_KINDS } from "./savedPlaceSearch.ts";
import { placeType } from "./geocode.ts";
import type { FavoritePlace } from "./favoritePlaces.ts";

const HOME = { point: [-77.03, 38.92] as [number, number], label: "1500 Harvard St NW" };
const FAVORITES: FavoritePlace[] = [
  { point: [-77.11, 39.06], label: "USP Twinbrook", work: true },
  { point: [-77.0, 38.9], label: "Joe's Bikes" },
  { point: [-77.02, 38.95], label: "Rock Creek Park" },
];

test("'home' and 'work', said or typed, name the saved Home and Work exactly", () => {
  for (const said of ["home", "Home.", "take me home", "go home", "my house"]) {
    const hits = savedPlacesFor(said, HOME, FAVORITES, "en");
    assert.equal(hits.exact?.kind, "home", said);
    assert.deepEqual([hits.exact?.lon, hits.exact?.lat], HOME.point);
    assert.equal(hits.places[0], hits.exact);
  }
  for (const said of ["work", "go to work", "the office"]) {
    const hits = savedPlacesFor(said, HOME, FAVORITES, "en");
    assert.equal(hits.exact?.kind, "work", said);
    assert.equal(hits.exact?.label, "USP Twinbrook");
  }
});

test("other languages' words for home and work, English too", () => {
  assert.equal(savedPlacesFor("casa", HOME, FAVORITES, "es").exact?.kind, "home");
  assert.equal(savedPlacesFor("llévame a casa", HOME, FAVORITES, "es").exact?.kind, "home");
  assert.equal(savedPlacesFor("trabajo", HOME, FAVORITES, "es").exact?.kind, "work");
  assert.equal(savedPlacesFor("maison", HOME, FAVORITES, "fr").exact?.kind, "home");
  assert.equal(savedPlacesFor("домой", HOME, FAVORITES, "ru").exact?.kind, "home");
  assert.equal(savedPlacesFor("会社", HOME, FAVORITES, "ja").exact?.kind, "work");
  assert.equal(savedPlacesFor("집", HOME, FAVORITES, "ko").exact?.kind, "home");
  assert.equal(savedPlacesFor("home", HOME, FAVORITES, "vi").exact?.kind, "home");
});

test("a favorite's name said whole is exact; its first letters list it", () => {
  const whole = savedPlacesFor("Joe's Bikes", HOME, FAVORITES, "en");
  assert.equal(whole.exact?.label, "Joe's Bikes");
  const part = savedPlacesFor("joe", HOME, FAVORITES, "en");
  assert.equal(part.exact, null);
  assert.deepEqual(part.places.map((p) => p.label), ["Joe's Bikes"]);
  // Home and Work by their own names too.
  assert.deepEqual(savedPlacesFor("1500 harv", HOME, FAVORITES, "en").places.map((p) => p.kind), ["home"]);
  assert.deepEqual(savedPlacesFor("usp", HOME, FAVORITES, "en").places.map((p) => p.kind), ["work"]);
});

test("nothing saved, or words that name none: nothing listed, so the search goes on as before", () => {
  assert.deepEqual(savedPlacesFor("home", null, null, "en"), { places: [], exact: null });
  assert.deepEqual(savedPlacesFor("work", HOME, [], "en"), { places: [], exact: null });
  assert.deepEqual(savedPlacesFor("Union Market", HOME, FAVORITES, "en"), { places: [], exact: null });
  assert.deepEqual(savedPlacesFor("h", HOME, FAVORITES, "en"), { places: [], exact: null });
});

test("saved places show as Saved and are of the kinds never kept as recent places", () => {
  const home = savedPlacesFor("home", HOME, FAVORITES, "en").exact!;
  assert.equal(placeType(home), "Saved");
  assert.ok(SAVED_KINDS.has(home.kind));
});

test("one character of Chinese or Japanese names Home ('家'); one Latin letter or digit names nothing", () => {
  assert.equal(savedPlacesFor("家", HOME, FAVORITES, "zh").exact?.kind, "home");
  assert.equal(savedPlacesFor("家", HOME, FAVORITES, "ja").exact?.kind, "home");
  assert.deepEqual(savedPlacesFor("1", HOME, FAVORITES, "en").places, []);
});

test("a favorite named like a keyword is that favorite, not Work", () => {
  const favorites: FavoritePlace[] = [...FAVORITES, { point: [-77.05, 38.9], label: "Office" }];
  assert.equal(savedPlacesFor("office", HOME, favorites, "en").exact?.label, "Office");
  assert.equal(savedPlacesFor("work", HOME, favorites, "en").exact?.kind, "work");
});

test("one row per spot: Work at Home, or Home saved as a favorite too, is listed once", () => {
  const favorites: FavoritePlace[] = [{ point: HOME.point, label: "1500 Harvard St NW", work: true }, { point: HOME.point, label: "1500 Harvard St NW" }];
  const hits = savedPlacesFor("1500", HOME, favorites, "en");
  assert.deepEqual(hits.places.map((p) => p.kind), ["home"]);
  assert.equal(savedPlacesFor("home", HOME, favorites, "en").places.length, 1);
});

test("Hindi and Thai keep their vowel signs: काम is work, कम is not", () => {
  assert.equal(savedPlacesFor("काम", HOME, FAVORITES, "hi").exact?.kind, "work");
  assert.equal(savedPlacesFor("कम", HOME, FAVORITES, "hi").exact, null);
  assert.equal(savedPlacesFor("บ้าน", HOME, FAVORITES, "th").exact?.kind, "home");
  assert.equal(savedPlacesFor("บาน", HOME, FAVORITES, "th").exact, null);
});
