// The phone app's config (site-config.js) and what the repository must never hold.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { buildConfig, siteUrl } = require("../site-config.js");
const here = (path) => fileURLToPath(new URL(path, import.meta.url));

test("no site address in the build: the app asks for it on first launch", () => {
  const config = buildConfig({});
  assert.equal(config.server.url, undefined, "no server.url: the bundled www/index.html until an address is kept");
  assert.equal(config.server.cleartext, undefined);
  assert.equal(siteUrl({}), null);
  assert.equal(siteUrl({ ROUTEMAKER_URL: "  " }), null);
  assert.equal(config.server.errorPath, "offline.html");
  assert.deepEqual(config.server.allowNavigation, ["discord.com"], "the sign-in round trip only");
  assert.ok(existsSync(here("../www/offline.html")));
  assert.ok(existsSync(here("../www/index.html")));
  // The bundled page is a placeholder: no script, nothing sent.
  assert.doesNotMatch(readFileSync(here("../www/index.html"), "utf8"), /<script|https?:\/\//);
});

test("ROUTEMAKER_URL, a local build's override: an https origin only; http only for a development server, asked for by name", () => {
  assert.equal(buildConfig({ ROUTEMAKER_URL: " https://beta.example.net/ " }).server.url, "https://beta.example.net");
  assert.equal(buildConfig({ ROUTEMAKER_URL: "https://beta.example.net" }).server.cleartext, false);
  assert.throws(() => siteUrl({ ROUTEMAKER_URL: "http://10.0.2.2:5173" }), /https/);
  const dev = buildConfig({ ROUTEMAKER_URL: "http://10.0.2.2:5173", ROUTEMAKER_ALLOW_HTTP: "1" });
  assert.equal(dev.server.url, "http://10.0.2.2:5173");
  assert.equal(dev.server.cleartext, true);
  assert.throws(() => siteUrl({ ROUTEMAKER_URL: "https://beta.example.net/ride" }), /origin alone/);
  assert.throws(() => siteUrl({ ROUTEMAKER_URL: "https://beta.example.net/?x=1" }), /origin alone/);
  assert.throws(() => siteUrl({ ROUTEMAKER_URL: "https://user:pw@beta.example.net" }), /origin alone/);
  assert.throws(() => siteUrl({ ROUTEMAKER_URL: "javascript:alert(1)" }), /https/);
  assert.throws(() => siteUrl({ ROUTEMAKER_URL: "not a url" }), /not a URL/);
});

test("ROUTEMAKER_URL is refused in CI: an Actions artifact of a public repository must name no server", () => {
  assert.throws(() => buildConfig({ CI: "true", ROUTEMAKER_URL: "https://beta.example.net" }), /local builds only/);
  assert.equal(buildConfig({ CI: "true" }).server.url, undefined);
});

test("Android: the legacy bridge the background-location plugin needs; the inspector only when asked", () => {
  const config = buildConfig({});
  assert.equal(config.android.useLegacyBridge, true);
  assert.equal(config.android.allowMixedContent, false);
  assert.equal(config.android.webContentsDebuggingEnabled, false);
  assert.equal(buildConfig({ ROUTEMAKER_DEBUG: "1" }).android.webContentsDebuggingEnabled, true);
  assert.equal(config.plugins.LocalNotifications.smallIcon, "ic_ride");
  assert.equal(config.ios, undefined, "Android only for now");
});

test("the resolved config (with the address) is git-ignored where cap sync writes it", () => {
  const ignore = readFileSync(here("../android/.gitignore"), "utf8");
  assert.match(ignore, /^app\/src\/main\/assets\/capacitor\.config\.json$/m);
  assert.match(ignore, /^app\/src\/main\/assets\/public$/m);
  const mine = readFileSync(here("../.gitignore"), "utf8");
  assert.match(mine, /\*\.jks/);
  assert.match(mine, /\*\.keystore/);
});

test("the manifest asks for the network, the location and notifications, and removes the rest", () => {
  const manifest = readFileSync(here("../android/app/src/main/AndroidManifest.xml"), "utf8");
  const asked = [...manifest.matchAll(/<uses-permission android:name="android\.permission\.([A-Z_]+)" \/>/g)].map((m) => m[1]);
  assert.deepEqual(asked.sort(), [
    "ACCESS_COARSE_LOCATION",
    "ACCESS_FINE_LOCATION",
    "FOREGROUND_SERVICE",
    "FOREGROUND_SERVICE_LOCATION",
    "INTERNET",
    "POST_NOTIFICATIONS",
  ]);
  const removed = [...manifest.matchAll(/<uses-permission android:name="android\.permission\.([A-Z_]+)" tools:node="remove" \/>/g)].map((m) => m[1]);
  assert.deepEqual(removed.sort(), ["RECEIVE_BOOT_COMPLETED", "SCHEDULE_EXACT_ALARM", "WAKE_LOCK"]);
  assert.doesNotMatch(manifest, /ACCESS_BACKGROUND_LOCATION"\s*\/>/, "never 'all the time' location");
  assert.match(manifest, /android:allowBackup="false"/);
  assert.match(manifest, /LocalNotificationRestoreReceiver"\s*tools:node="remove"/);
});

test("release signing and the store id come from the environment; no key in the repository", () => {
  const gradle = readFileSync(here("../android/app/build.gradle"), "utf8");
  for (const name of ["ROUTEMAKER_KEYSTORE_FILE", "ROUTEMAKER_KEYSTORE_PASSWORD", "ROUTEMAKER_KEY_ALIAS", "ROUTEMAKER_KEY_PASSWORD", "ROUTEMAKER_APP_ID"]) {
    assert.match(gradle, new RegExp(`System\\.getenv\\("${name}"\\)|envOr\\("${name}"`), name);
  }
  assert.doesNotMatch(gradle, /storePassword\s+["']/);
  const workflow = readFileSync(here("../../.github/workflows/android.yml"), "utf8");
  assert.match(workflow, /^on:\s*\n\s+workflow_dispatch:/m, "run by hand only");
  assert.doesNotMatch(workflow, /^\s+(pull_request|push):/m);
  // No repository variable, no address: the build names no server, and checks that it does not.
  assert.doesNotMatch(workflow, /vars\./);
  assert.doesNotMatch(workflow, /^\s+ROUTEMAKER_URL:/m);
  assert.match(workflow, /No site address in the build/);
});

test("the first-launch screen: labelled for screen readers, https only, checked against /healthz, kept on the phone", () => {
  const layout = readFileSync(here("../android/app/src/main/res/layout/activity_setup.xml"), "utf8");
  assert.match(layout, /android:labelFor="@\+id\/site_url"/);
  assert.match(layout, /android:id="@\+id\/site_url"[\s\S]*?android:inputType="textUri"/);
  assert.match(layout, /android:accessibilityLiveRegion="polite"/, "status and errors are read out");
  assert.match(layout, /android:accessibilityHeading="true"/);
  const login = readFileSync(here("../android/app/src/main/res/layout/dialog_site_login.xml"), "utf8");
  assert.match(login, /android:labelFor="@\+id\/login_user"/);
  assert.match(login, /android:labelFor="@\+id\/login_password"/);
  assert.match(login, /android:inputType="textPassword"/);
  const java = (name) => readFileSync(here(`../android/app/src/main/java/org/routemaker/phone/${name}.java`), "utf8");
  const address = java("SiteAddress");
  assert.match(address, /PROBE_PATH = "\/healthz"/);
  assert.match(readFileSync(here("../../src/config/urls.py"), "utf8"), /path\("healthz", health\.healthz/);
  assert.match(java("SiteStore"), /getSharedPreferences\(PREFS, Context\.MODE_PRIVATE\)/);
  // The basic-auth password is handed to the WebView for this run only, never kept by the app.
  const auth = java("SiteWebViewClient");
  assert.match(auth, /handler\.proceed\(/);
  assert.doesNotMatch(auth, /setHttpAuthUsernamePassword|SharedPreferences|putString/);
  // The launcher is the first-launch screen; the site's activity is not exported.
  const manifest = readFileSync(here("../android/app/src/main/AndroidManifest.xml"), "utf8");
  assert.match(manifest, /android:name="\.SetupActivity"[\s\S]*?android\.intent\.category\.LAUNCHER/);
  assert.match(manifest, /android:name="\.MainActivity"[\s\S]*?android:exported="false"/);
});
