// Favorite places (Stephen 2026-10-26: "For signed in users, allow for favorite destinations"; "just have a favorites
// replace home"; "Home and if set work would be the top 2 favorites"; "we'd have a popout"; "At the end ride screen
// offer the opportunity to save that destination as a favorite"): the pure parts, and Go's, App's, the road panel's
// and the ride summary's wiring read as source.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  FAVORITE_PLACES_MAX,
  SAVE_SPOT_TEXT,
  favoriteFromPlace,
  favoritePlacesBody,
  favoriteRemovedSaid,
  favoriteSavedSaid,
  fetchFavoritePlaces,
  othersOf,
  parseFavoritePlaces,
  saveFavoritePlaces,
  withFavorite,
  withWork,
  withoutFavorite,
  workOf,
  favoritesSaver,
  type FavoritePlace,
} from "./favoritePlaces.ts";

const src = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

const market: FavoritePlace = { point: [-77.05, 38.91], label: "Market" };
const office: FavoritePlace = { point: [-77.01, 38.9], label: "Office", work: true };

test("an answer's places are kept in order, each spot once, one Work, cut to the most kept", () => {
  const raw = {
    places: [
      { lon: -77.01, lat: 38.9, label: "Office", work: true },
      { lon: -77.05, lat: 38.91, label: "Market", work: false },
      { lon: -77.050001, lat: 38.910001, label: "Market again" },
      { lon: -77.1, lat: 38.95, label: "Second work", work: true },
      { lon: "x", lat: 38.9, label: "broken" },
      null,
    ],
  };
  assert.deepEqual(parseFavoritePlaces(raw), [office, market, { point: [-77.1, 38.95], label: "Second work" }]);
  assert.deepEqual(parseFavoritePlaces(null), []);
  assert.deepEqual(parseFavoritePlaces({ places: "no" }), []);
  const many = { places: Array.from({ length: 30 }, (_, i) => ({ lon: -77 - i / 100, lat: 38.9, label: `P${i}` })) };
  assert.equal(parseFavoritePlaces(many).length, FAVORITE_PLACES_MAX);
});

test("the body is the whole list, every place named, Work marked", () => {
  assert.deepEqual(favoritePlacesBody([office, { point: [-77.0, 38.9], label: " " }]), {
    places: [
      { lon: -77.01, lat: 38.9, label: "Office", work: true },
      { lon: -77.0, lat: 38.9, label: "38.9000, -77.0000", work: false },
    ],
  });
});

test("Home's list order: Work first after Home, then the rest as added", () => {
  const list = [market, office];
  assert.deepEqual(workOf(list), office);
  assert.deepEqual(othersOf(list), [market]);
  assert.equal(workOf([market]), null);
});

test("a place is added last, once; a full list says so (null)", () => {
  assert.deepEqual(withFavorite([office], market), [office, market]);
  assert.deepEqual(withFavorite([office, market], { ...market, label: "Same spot" }), [office, market]);
  const full = Array.from({ length: FAVORITE_PLACES_MAX }, (_, i): FavoritePlace => ({ point: [-77 - i / 100, 38.9], label: `P${i}` }));
  assert.equal(withFavorite(full, { point: [-76, 39], label: "One more" }), null);
});

test("Work replaces the old Work; a favorite made Work is not listed twice; null clears it", () => {
  const next = withWork([office, market], { ...market, work: true });
  assert.deepEqual(next, [{ ...market, work: true }]);
  assert.deepEqual(withWork([office, market], null), [market]);
  assert.deepEqual(withoutFavorite([office, market], market), [office]);
});

test("each change is said in words", () => {
  assert.equal(favoriteSavedSaid(market), "Market saved to Favorites.");
  assert.equal(favoriteSavedSaid(office), "Work set to Office.");
  assert.equal(favoriteRemovedSaid(market), "Market removed from Favorites.");
  assert.equal(favoriteRemovedSaid(office), "Work cleared.");
  assert.deepEqual(favoriteFromPlace({ lon: -77.05, lat: 38.91, name: "Market" }), market);
  assert.deepEqual(favoriteFromPlace({ lon: -77.01, lat: 38.9, name: "Office" }, true), office);
});

test("GET and POST /api/me/places: signed out or failed is null; a save sends the CSRF token", async () => {
  const answer = (status: number, body: unknown) => (async () => new Response(JSON.stringify(body), { status })) as unknown as typeof fetch;
  assert.equal(await fetchFavoritePlaces("https://x", answer(401, { error: "Sign in" })), null);
  assert.deepEqual(await fetchFavoritePlaces("https://x", answer(200, { places: [{ lon: -77.05, lat: 38.91, label: "Market", work: false }] })), [market]);
  let sent: RequestInit | undefined;
  const post = (async (_url: string, init: RequestInit) => {
    sent = init;
    return new Response(JSON.stringify({ places: [] }), { status: 200 });
  }) as unknown as typeof fetch;
  assert.deepEqual(await saveFavoritePlaces("https://x", [], post, "csrftoken=abc"), []);
  assert.equal((sent?.headers as Record<string, string>)["X-CSRFToken"], "abc");
  assert.equal(await saveFavoritePlaces("https://x", [], answer(400, {})), null);
});

test("Go: signed in, Favorites takes Home's place and pops out Home, Work, then the rest; signed out, Home stays", () => {
  const go = src("../app/Go.tsx");
  assert.match(go, /\{places\.signedIn \? \([\s\S]*?\{FAVORITES_TEXT\}[\s\S]*?\) : \([\s\S]*?\{t\("Home"\)\}\s*<\/button>\s*\)\}/);
  const popout = go.slice(go.indexOf("export function FavoritesPopout"), go.indexOf("export function HomeSetter"));
  const order = ["SET_HOME_TEXT", "SET_WORK_TEXT", "others.map", "ADD_FAVORITE_TEXT", "EDIT_FAVORITES_TEXT"].map((key) => popout.indexOf(key));
  assert.ok(order.every((at, i) => at > 0 && (i === 0 || at > order[i - 1])), "Home, Work, the rest, then Add a place and Edit");
  // Remove and Change say what they act on, for screen readers.
  assert.match(popout, /\{t\("Remove"\)\}<span className="visually-hidden"> \{favoriteName\(place\)\}<\/span>/);
  // Food stays on the main row; Change Home leaves More signed in (Edit has it).
  assert.match(go, /places\.homeReady && !places\.signedIn &&/);
});

test("App, the road panel and the ride summary: Save to Favorites, signed in only", () => {
  const app = src("../App.tsx");
  assert.match(app, /onSaveFavorite=\{me\.signed_in \? \(point\) => void addFavoriteAt\(point\) : undefined\}/);
  // Not before the account's list is read (it would replace the list), nor outside the map, nor at Home.
  assert.match(app, /if \(!me\.signed_in \|\| favoritePlaces === null \|\| !destination \|\| !insideCoverage\(destination\) \|\| \(myGo\.home && samePoint\(myGo\.home\.point, destination\)\)\) return null;/);
  // No save before the list is read: the rider is told, and it is read again.
  assert.match(app, /if \(now === null\) \{\s*announce\(FAVORITES_NOT_LOADED\);\s*loadFavorites\(\);\s*return;/);
  assert.match(app, /start && !start\.loop && start\.points\.length >= 2/);
  assert.match(src("../RoadInfoDialog.tsx"), /\{SAVE_SPOT_TEXT\}/);
  assert.match(src("../RideSummaryCard.tsx"), /\{SAVE_SPOT_TEXT\}/);
  assert.equal(SAVE_SPOT_TEXT, "Save to Favorites");
  // Never kept on the device: no storage key.
  assert.doesNotMatch(src("./favoritePlaces.ts"), /localStorage/);
});

test("saves go one at a time, each with the list as it is then; a refusal puts back what the account confirmed", async () => {
  let shown: FavoritePlace[] | null = [market];
  const sent: FavoritePlace[][] = [];
  const answers: ((v: FavoritePlace[] | null) => void)[] = [];
  let refusals = 0;
  const saver = favoritesSaver(
    (places) => {
      sent.push([...places]);
      return new Promise((resolve) => answers.push(resolve));
    },
    () => shown,
    (places) => {
      shown = places;
    },
    () => (refusals += 1),
  );
  saver.loaded([market]);
  // Two quick changes: the second waits for the first's answer, then sends the list as it is then.
  shown = [market, office];
  const first = saver.changed();
  await Promise.resolve();
  shown = [office];
  const second = saver.changed();
  await Promise.resolve();
  assert.deepEqual(sent, [[market, office]], "one in flight");
  answers[0]([market, office]);
  await first;
  assert.deepEqual(shown, [office], "a change since keeps what the rider sees");
  await Promise.resolve();
  assert.deepEqual(sent[1], [office]);
  answers[1](null);
  await second;
  assert.deepEqual(shown, [market, office], "refused: the list the account last confirmed");
  assert.equal(refusals, 1);
});
