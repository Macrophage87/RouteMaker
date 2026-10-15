import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { NO_PHOTO_TEXT, fetchStreetPhoto, photoAlt, readPhoto, streetPhotoUrl, type StreetPhoto } from "./streetPhoto.ts";

const SRC = new URL("../", import.meta.url);
const src = (path: string) => readFileSync(new URL(path, SRC), "utf8");

const ANSWER = {
  found: true,
  image_url: "/api/street-photo/image/123456",
  viewer_url: "https://www.mapillary.com/app/?pKey=123456&focus=photo",
  captured: "2021-06-14",
  date_words: "Photo from June 2021",
  creator: "rider42",
  credit: "Mapillary",
  credit_url: "https://www.mapillary.com/",
  licence: "CC BY-SA",
  licence_url: "https://creativecommons.org/licenses/by-sa/4.0/",
};

test("a photo's date is in its alt text with the road's name", () => {
  const photo = readPhoto(ANSWER) as StreetPhoto;
  assert.equal(photoAlt("Oak Street", photo), "Street photo of Oak Street, from June 2021");
  assert.equal(photo.date_words, "Photo from June 2021");
});

test("no photo is one plain line; an odd or unsafe answer is nothing", () => {
  assert.equal(readPhoto({ found: false, words: NO_PHOTO_TEXT }), "none");
  assert.equal(readPhoto({ ...ANSWER, image_url: "javascript:alert(1)" }), null);
  // The image is this server's copy only: another host's file is refused, the CSP's img-src is same-origin.
  assert.equal(readPhoto({ ...ANSWER, image_url: "https://scontent-iad3-1.xx.fbcdn.net/m1/v/t6/abc.jpg" }), null);
  assert.equal(readPhoto({ ...ANSWER, image_url: "/api/street-photo/image/12/../x" }), null);
  assert.equal(readPhoto({ ...ANSWER, viewer_url: "http://www.mapillary.com/app" }), null);
  assert.equal(readPhoto({ ...ANSWER, date_words: 3 }), null);
  assert.equal(readPhoto("x"), null);
  assert.equal(NO_PHOTO_TEXT, "No street photo here.");
});

test("the server is asked for the point on the road and the way; 204 and failures say nothing", async () => {
  assert.equal(streetPhotoUrl("https://x", [-77.1, 38.9], 42), "https://x/api/street-photo?lon=-77.100000&lat=38.900000&way=42");
  const asked: string[] = [];
  const ok = async (url: string) => {
    asked.push(url);
    return new Response(JSON.stringify(ANSWER), { status: 200 });
  };
  assert.equal(((await fetchStreetPhoto("https://x", [-77.1, 38.9], 42, undefined, ok)) as StreetPhoto).creator, "rider42");
  assert.equal(asked.length, 1);
  const off = async () => new Response(null, { status: 204 });
  assert.equal(await fetchStreetPhoto("https://x", [-77.1, 38.9], 42, undefined, off), null);
  const down = async () => {
    throw new Error("offline");
  };
  assert.equal(await fetchStreetPhoto("https://x", [-77.1, 38.9], null, undefined, down), null);
});

test("the panel shows the photo as a link to Mapillary in a new tab, the date under it, and no new controls", () => {
  const panel = src("RoadInfoDialog.tsx");
  assert.match(panel, /<StreetPhotoView title=\{ready\.title\} point=\{streetViewPoint\(ready, request\.point\)\} wayId=\{ready\.osm_way_id\} \/>/);
  assert.match(panel, /<img src=\{photo\.image_url\} alt=\{photoAlt\(title, photo\)\}/);
  assert.match(panel, /<a href=\{photo\.viewer_url\} target="_blank" rel="noopener noreferrer">/);
  assert.match(panel, /\{photo\.date_words\}/);
  // No token in the front end, and no Mapillary script.
  assert.doesNotMatch(src("lib/streetPhoto.ts"), /MLY\||access_token|mapillary-js/i);
});
