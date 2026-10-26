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
  assert.deepEqual(config.server.allowNavigation, ["discord.com", "sso.garmin.com", "connect.garmin.com", "api.wahooligan.com"], "the Discord sign-in, Connect Garmin and Connect Wahoo round trips only");
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
  assert.throws(() => buildConfig({ CI: "true", ROUTEMAKER_URL: "https://beta.example.net" }), /local builds and the store build only/);
  assert.throws(() => buildConfig({ CI: "true", ROUTEMAKER_STORE_BUILD: "0", ROUTEMAKER_URL: "https://beta.example.net" }), /store build only/);
  assert.equal(buildConfig({ CI: "true" }).server.url, undefined);
  // The by-hand store build only, with the same origin rules.
  assert.equal(buildConfig({ CI: "true", ROUTEMAKER_STORE_BUILD: "1", ROUTEMAKER_URL: "https://site.example.org" }).server.url, "https://site.example.org");
  assert.throws(() => buildConfig({ CI: "true", ROUTEMAKER_STORE_BUILD: "1", ROUTEMAKER_URL: "http://site.example.org" }), /https/);
});

test("Android: the legacy bridge the background-location plugin needs; the inspector only when asked", () => {
  const config = buildConfig({});
  assert.equal(config.android.useLegacyBridge, true);
  // The legacy bridge is a JavaScript interface every page and frame gets: GuardedBridge passes calls on
  // only while the top-level page is the kept site. It reaches Capacitor's handler by its field name.
  const guard = readFileSync(here("../android/app/src/main/java/org/routemaker/phone/GuardedBridge.java"), "utf8");
  assert.match(guard, /getDeclaredField\("msgHandler"\)/);
  assert.match(guard, /if \(!client\.topLevelIsSite\(\)\)/);
  const capBridge = readFileSync(here("../node_modules/@capacitor/android/capacitor/src/main/java/com/getcapacitor/Bridge.java"), "utf8");
  assert.match(capBridge, /private final MessageHandler msgHandler;/, "Capacitor still keeps its handler there");
  const capHandler = readFileSync(here("../node_modules/@capacitor/android/capacitor/src/main/java/com/getcapacitor/MessageHandler.java"), "utf8");
  assert.match(capHandler, /webView\.addJavascriptInterface\(this, "androidBridge"\)/);
  assert.match(capHandler, /public void postMessage\(String jsonStr\)/);
  const main = readFileSync(here("../android/app/src/main/java/org/routemaker/phone/MainActivity.java"), "utf8");
  assert.match(main, /GuardedBridge\.install\(bridge, client\)/);
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

test("the manifest: the location service not exported, GPS not required, nothing backed up or transferred", () => {
  const manifest = readFileSync(here("../android/app/src/main/AndroidManifest.xml"), "utf8");
  assert.match(manifest, /BackgroundGeolocationService"\s*android:exported="false"\s*tools:replace="android:exported"/);
  assert.match(manifest, /android\.hardware\.location\.gps" android:required="false" tools:replace="android:required"/);
  assert.match(manifest, /android:dataExtractionRules="@xml\/data_extraction_rules"/);
  const rules = readFileSync(here("../android/app/src/main/res/xml/data_extraction_rules.xml"), "utf8");
  for (const part of ["cloud-backup", "device-transfer"]) {
    const block = rules.match(new RegExp(`<${part}>([\\s\\S]*?)</${part}>`))[1];
    const excluded = [...block.matchAll(/<exclude domain="(\w+)" path="\." \/>/g)].map((m) => m[1]).sort();
    assert.deepEqual(excluded, ["database", "device_database", "device_file", "device_root", "device_sharedpref", "external", "file", "root", "sharedpref"], part);
    assert.doesNotMatch(block, /<include/);
  }
});

test("the cue notification is cleared at app start and when the site's screen goes", () => {
  const main = readFileSync(here("../android/app/src/main/java/org/routemaker/phone/MainActivity.java"), "utf8");
  const id = Number(main.match(/CUE_NOTICE_ID = (\d+);/)[1]);
  const shell = readFileSync(here("../../frontend/src/lib/nativeShell.ts"), "utf8");
  assert.equal(id, Number(shell.match(/export const CUE_NOTICE_ID = ([\d_]+);/)[1].replace(/_/g, "")));
  const create = main.slice(main.indexOf("public void onCreate"), main.indexOf("registerPlugin"));
  assert.match(create, /cancelCueNotice\(\);/, "before anything else in onCreate");
  assert.match(main, /public void onDestroy\(\) \{\s*\/\/[^\n]*\n\s*cancelCueNotice\(\);/);
});

test("no template tests left from the Capacitor project", () => {
  assert.equal(existsSync(here("../android/app/src/test/java/com/getcapacitor")), false);
  assert.equal(existsSync(here("../android/app/src/androidTest/java/com/getcapacitor")), false);
  assert.ok(existsSync(here("../android/app/src/test/java/org/routemaker/phone/SiteAddressTest.java")));
});

test("release signing and the store id come from the environment; no key in the repository", () => {
  const gradle = readFileSync(here("../android/app/build.gradle"), "utf8");
  for (const name of ["ROUTEMAKER_KEYSTORE_FILE", "ROUTEMAKER_KEYSTORE_PASSWORD", "ROUTEMAKER_KEY_ALIAS", "ROUTEMAKER_KEY_PASSWORD", "ROUTEMAKER_APP_ID"]) {
    assert.match(gradle, new RegExp(`System\\.getenv\\("${name}"\\)|envOr\\("${name}"`), name);
  }
  // The only password written down is Android's public debug one, for the optional steady debug key.
  assert.doesNotMatch(gradle, /(?:store|key)Password\s+["'](?!android["'])/);
  assert.match(gradle, /System\.getenv\("ROUTEMAKER_DEBUG_KEYSTORE_FILE"\)/);
  assert.match(gradle, /if \(debugKeystore\) \{\s*debug \{/, "the fixed passwords sit only in the debug signing config");
  const workflow = readFileSync(here("../../.github/workflows/android.yml"), "utf8");
  // Pull requests touching the app: tests and a debug APK only. Release by hand, or on a release tag
  // (only when mobile/ changed since the tag before); no other push.
  assert.match(workflow, /^on:\s*\n\s+push:\s*\n\s+tags: \["v\*"\]\s*\n\s+pull_request:\s*\n\s+paths:\s*\n\s+- "mobile\/\*\*"\s*\n\s+- "\.github\/workflows\/android\.yml"\s*\n\s+workflow_dispatch:/m);
  assert.doesNotMatch(workflow, /^\s+branches:/m);
  assert.match(workflow, /BUILD: \$\{\{ github\.event_name == 'push' && 'release' \|\| github\.event_name == 'workflow_dispatch' && inputs\.build \|\| 'debug' \}\}/);
  assert.match(workflow, /if: env\.BUILD == 'release' && github\.event_name != 'pull_request'/);
  assert.match(workflow, /git diff --quiet "\$prev" "\$GITHUB_SHA" -- mobile\//);
  assert.match(workflow, /needs\.changes\.outputs\.app == 'true'/);
  // A skipped `changes` (pull requests, by hand) must not skip the build.
  assert.match(workflow, /if: \$\{\{ !cancelled\(\) && /);
  // The bundle is kept before the Play upload, so a refused upload leaves it to upload by hand.
  assert.ok(workflow.indexOf("actions/upload-artifact") < workflow.indexOf("Upload to Play internal testing"));
  // The Play upload runs on a tag only, through the repository's own script.
  assert.match(workflow, /Upload to Play internal testing \(a release tag only\)\s*\n\s+if: github\.event_name == 'push'/);
  assert.match(workflow, /PLAY_SERVICE_ACCOUNT_JSON: \$\{\{ secrets\.ROUTEMAKER_PLAY_SERVICE_ACCOUNT \}\}/);
  assert.match(workflow, /scripts\/play-upload\.sh android\/app\/build\/outputs\/bundle\/release\/\*\.aab/);
  assert.match(workflow, /\.\/gradlew --no-daemon testDebugUnitTest/);
  assert.match(workflow, /- run: npm test/);
  assert.match(workflow, /persist-credentials: false/);
  for (const uses of workflow.matchAll(/uses: (\S+)/g)) assert.match(uses[1], /@[0-9a-f]{40}$/, `${uses[1]} pinned by commit`);
  // No repository variable, no address: the build names no server, and checks that it does not.
  assert.doesNotMatch(workflow, /vars\./);
  assert.doesNotMatch(workflow, /^\s+ROUTEMAKER_URL:/m);
  assert.match(workflow, /No site address in the build/);
  // Only the release (store) build reads the site secret and bakes it in, never a pull request; its
  // artifact is short-lived.
  assert.match(workflow, /STORE_SITE: \$\{\{ env\.BUILD == 'release' && github\.event_name != 'pull_request' && secrets\.ROUTEMAKER_SITE_URL \|\| '' \}\}/);
  assert.equal(workflow.match(/ROUTEMAKER_SITE_URL \|\|/g).length, 1, "the site secret is read in one place");
  assert.match(workflow, /ROUTEMAKER_STORE_BUILD=1 ROUTEMAKER_URL="\$STORE_SITE" npx cap sync android/);
  assert.match(workflow, /retention-days: \$\{\{ env\.BUILD == 'release' && 3 \|\| 30 \}\}/);
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
