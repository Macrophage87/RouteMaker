import { test } from "node:test";
import assert from "node:assert/strict";
import { menuParts, withoutMenuMarks } from "./menuNames.ts";
import { IOS_LOCATION_STEPS } from "./geolocation.ts";

test("menu names marked **like this** come apart for bold, and come off for the voice", () => {
  assert.deepEqual(menuParts("Open the **Settings** app, then **Privacy & Security**."), [
    { text: "Open the ", menu: false },
    { text: "Settings", menu: true },
    { text: " app, then ", menu: false },
    { text: "Privacy & Security", menu: true },
    { text: ".", menu: false },
  ]);
  assert.deepEqual(menuParts("**Ayarlar** uygulamasını açın"), [
    { text: "Ayarlar", menu: true },
    { text: " uygulamasını açın", menu: false },
  ]);
  assert.equal(withoutMenuMarks("On Android: **Settings**, **Display**."), "On Android: Settings, Display.");
  // The iPhone steps name the menus in bold; the last step has none to name.
  for (const step of IOS_LOCATION_STEPS.slice(0, 3)) assert.match(step, /\*\*[^*]+\*\*/);
});
