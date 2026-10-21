# RouteMaker phone app (v0.8.0)

The owner, 2026-10-16: "It appears that a standalone app that points to the website would be a
nessecity for using it in bikeshare mode as the phone stays in the pocket and navigation cues stop
when the phone is off."

In a browser, Ride mode's GPS watch and its voice (Web Speech) stop when the screen locks, and after
ten minutes in the background the ride pauses. This folder is a thin Android app (Capacitor 8) that
opens the live site in a WebView and gives Ride mode three native things while a ride is going:

- **Location with the screen locked.** `@capacitor-community/background-geolocation` runs an Android
  foreground service of type `location` from Start ride to End ride, with a persistent
  **"Riding with RouteMaker"** notification. End ride (or leaving Ride mode) removes the watcher, which
  stops the service and its notification.
- **Spoken cues with the screen locked.** `@capacitor-community/text-to-speech` (the phone's own
  text-to-speech engine) in place of Web Speech.
- **The latest cue on the notification shade** (v0.8.0 site only). `@capacitor/local-notifications`
  shows a second, silent "Latest cue" notification, replaced as each cue is said, cleared at End ride.

One more native thing, outside a ride: **Send to Garmin** (the site's GPX sheet, v0.9.0 site and app). The
site makes the FIT course and hands it to `FilesPlugin.java` ("RouteMakerFiles"), which writes it to the app's
cache and hands it to Garmin Connect when Connect takes it (the manifest's one `<queries>` entry names it),
otherwise to Android's "Open with" list. A WebView can neither share nor download a file a page makes, so an
older app without the plugin shows no Send to Garmin button.

**Opening a RouteMaker link in the app** (v0.9.0 app): in any app, Share the link and pick RouteMaker.
`SharedLink.java` takes the first https link in the shared text and opens it only when it is on the site kept
on this phone; any other link is refused with a short message. A tapped link still opens the browser:
Android opens a tapped web link in an app only for an address built into the APK (verified App Links, plus
a file on the server naming the app's signing key), and no build carries one. That can come with a
production address. Opening a shared link replaces the page shown, a ride in progress included.

There are no new buttons: Start ride, Go and End work as on the website. Distances are the site's
own (feet and miles).

iOS can be added later from the same shell (`npx cap add ios` on a Mac, plus the location and audio
background modes); the web side is already platform-neutral.

## How a test APK gets working cues before v0.8.0 is deployed

The app loads whatever site the rider typed on first launch, so it has to work with the code that
site runs.
There are two layers, and exactly one of them is active on any page:

1. **The site's own bridge, from v0.8.0** (`frontend/src/lib/nativeShell.ts`). It detects the shell
   (`window.Capacitor.isNativePlatform()`), calls the plugins directly through the injected bridge
   object (no Capacitor package in the web bundle), and marks the page with
   `window.__routemakerNativeShell`. It also adds the cue notification, never pauses a ride when the
   page is hidden, and speaks "My screen reader" cues aloud while the page is hidden (below).
2. **The app's compatibility layer, for a site older than v0.8.0**
   (`android/app/src/main/assets/routemaker-compat.js`, injected at document start for the site's
   origin only by `RideCompatPlugin.java`). The old Ride mode knows nothing of the app, so this layer
   swaps the browser APIs it already calls: Ride mode's `navigator.geolocation.watchPosition`/
   `clearWatch` go to the background-location plugin, `speechSynthesis` goes to the native voice, and
   while a native ride watch runs with the page hidden, the old Ride mode's one ten-minute timer
   (`HIDDEN_STOP_MS`) is not scheduled, so the old pause never comes. Where the WebView has no screen
   wake lock, it answers with a stand-in so the old page does not say "keep your screen on".
   `getCurrentPosition` ("Use my location") is left alone. When the page carries the v0.8.0 mark, the
   layer stands aside entirely.

   **Only Ride mode's watch goes native, never Group or Mass Ride location sharing** (`RideGroup.tsx`,
   which promises to run only while the page is in front). Both use the same `watchRide` options, so
   the call alone cannot tell them apart. A watch goes native only if Ride mode's screen
   (`section.ride[aria-labelledby="ride-heading"]`) is on the page when it starts (Ride mode starts it
   from that screen, at Start ride); any other watch is the WebView's own. Beyond that: the sites this
   layer serves (v0.6 and v0.7) have Ride mode's watch as their only `watchPosition`, sharing arrived
   with v0.8.0, whose own bridge marks the page (so the layer is off there and RideGroup's watch is the
   browser's), and the layer never touches `visibilitychange`, so anything that stops when the page is
   hidden still does. `test/compat.test.mjs` holds all of this.

So a debug APK pointed at the current beta or live site should keep the GPS and the voice going with
the screen locked today, without deploying anything. What the old site cannot have until v0.8.0 is
deployed: the "Latest cue" notification, "My screen reader" spoken while locked, and the wording of
the Ride mode safety note (it still says the screen must stay on).

**The server needs no change.** The WebView loads the site at its own origin, so cookies, CSRF
(`CSRF_TRUSTED_ORIGINS`, `SESSION_COOKIE_SAMESITE = "Lax"`) and same-origin API calls are exactly a
phone browser's; no CORS is involved. The Discord sign-in round trip stays inside the app
(`server.allowNavigation: ["discord.com"]`), so the session cookie lands in the app's WebView (the
native bridge does not reach Discord's pages: see "The native bridge, for the site only"). Two
alternatives were set aside: bundling the built front end in the APK would make every `/api` and
tile request cross-origin (CORS and cookie changes on the server, and MapLibre's tile workers do not
go through Capacitor's native HTTP), and serving the bundle under the site's hostname makes
Capacitor answer `/api` locally.

## The site address: asked once, kept on the phone

No build carries a site address. The repository is public, and so are its Actions artifacts (any
signed-in GitHub user can download them), so an APK built there must not name a server. Instead, the
first time RouteMaker opens it shows one screen, **"Which RouteMaker site?"**:

- Type the site's address, such as `https://routes.example.org` (typing the name alone adds
  `https://`). Only `https://` is accepted, and only the site itself (no `/page`, `?` or user name).
- Continue checks it by fetching the site's public health path, `/healthz` (`200 ok`, or `503
  degraded` while its database is down). A clear sentence says what is wrong otherwise: no answer
  (no signal, no such name, a bad certificate) or "not a RouteMaker site". A site behind a password
  (the beta's HTTP basic auth, which covers `/healthz` too) answers 401 asking for it; that is kept,
  and the site's own sign-in box follows (below).
- The address is kept in the app's private preferences on this phone only (never sent anywhere but
  to that site, never in a backup: `allowBackup` is off).
- For TalkBack: the screen has a heading, the field is labelled "Site address", and the checking
  message and each error are read out as they appear (a polite live region).

To change it: touch and hold the RouteMaker icon and choose **Site address**, or reset the app in
Android's **Settings, Apps, RouteMaker, Storage, Clear storage** ("clear app data"). Clearing storage
also clears the site's data in the app (sign-in, a saved Home), as uninstalling does; the next launch
asks for the address again.

**The beta's password (HTTP basic auth).** A WebView, unlike a browser, shows nothing when a site
asks for a basic-auth password, so the app shows its own "Sign in to the site" box (user name and
password, both labelled for TalkBack) for the kept site only; any other site's request is refused. The
app never stores the password: it hands it to the WebView (`HttpAuthHandler.proceed`), which keeps it
in memory until the app's process ends, and never calls `WebViewDatabase`'s saved-password store. So
it is asked again after the app is closed or the phone restarts, never in the middle of a ride. The
password fields carry autofill hints, so the rider's own password manager may offer to fill or save
it; that is the rider's choice and outside the app.

## Installing a test build on an Android phone

1. **Actions, "Android app", Run workflow**, build `debug`. When it finishes, download the artifact
   `routemaker-android-debug-N` (a zip holding `app-debug.apk`). It names no site.
2. On the phone, open the APK (from Files, Drive or a USB copy) and allow "Install unknown apps" for
   the app you opened it with. Play Protect may warn that the app is unknown; choose to install anyway.
3. Open RouteMaker and type the site's address (above); for the beta, sign in with its password when
   asked.
4. Plan a route, press Go and Start ride. Android asks for location ("While using the app"), then for
   notifications (Android 13+), both at Start ride and never mid-ride. Lock the phone and ride.

With the `ROUTEMAKER_DEBUG_KEYSTORE_BASE64` secret set (Building, below), every debug build carries the
same key and a newer one installs over the last, keeping the app's data. Without it, each run signs
with a fresh debug key and a newer APK will not install over an older one ("App not installed"):
uninstall first (the site's data in the app, such as a Home, goes with it, and the next install asks
for the site address again). The first build after the secret is added also needs one uninstall.

What to check on the first ride (none of this could be tried here: there is no Android SDK or phone
in the build environment):

- the first-launch screen accepts the site's address (and, on the beta, the sign-in box takes its
  password), refuses an `http://` one, and TalkBack reads its label and errors;
- on a fresh install (Android 14+ especially), the very first ride: grant location at Start ride, lock
  the phone, and the cues keep coming (the permission is asked before the service starts, below);
- the "Riding with RouteMaker" notification appears at Start ride and goes at End ride, and no "Latest
  cue" is left on the shade after the app is swiped away and opened again;
- cues keep coming with the phone locked in a pocket for more than ten minutes;
- on a v0.8.0 site, the "Latest cue" notification follows the cues and clears at End ride;
- battery: the service asks for every fix (high accuracy, no distance filter) while the ride runs.
  Some makers' battery savers (Samsung, Xiaomi) still stop foreground services: if cues stop, set
  RouteMaker's battery use to "Unrestricted".

## Screen readers (TalkBack)

The rider's existing choice in the ride settings decides, as on the website
(`lib/rideOutput.ts`): "My screen reader", "RouteMaker's voice", "Both" or "Neither". A page cannot
tell whether TalkBack is on, so the choice is what keeps cues from being said twice.

- With the screen on and the app in front, "My screen reader" goes to TalkBack through the page's
  live regions only; the native voice is silent. "Both" says each cue twice, as on the website.
- With the phone locked (or another app in front), TalkBack reads nothing of the page, so on a v0.8.0
  site the native voice speaks "My screen reader" cues then; back in front, TalkBack alone again.
  "Neither" stays silent.
- The "Latest cue" notification is on a low-importance channel: no sound, no vibration, no heads-up,
  and Android sends TalkBack no announcement for it, so it never repeats the voice.
- On an older site (compatibility layer), "My screen reader" is silent with the phone locked: choose
  "RouteMaker's voice" for pocket riding until v0.8.0 is deployed.

## Permissions at Start ride

Start ride asks for location, then (Android 13+) for notifications, and only then adds the location
watcher; already granted, nothing is shown. The watcher is added with the plugin's own
`requestPermissions: false`: background-geolocation 1.2.26 would otherwise start its foreground
service before the answer, Android 14+ refuses a location foreground service without the permission
(the plugin swallows the error), and nothing promotes the service after the grant, so the first ride
would stop at the screen lock. Refused location: Ride mode says so, as in a browser. Refused
notifications: the ride goes on (the service still runs; its notification is hidden), and the cue
notification is not asked for again mid-ride. Both the site's bridge (`nativeShell.ts`,
`askRidePermissions`) and the compatibility layer do this.

## The native bridge, for the site only

The background-geolocation plugin needs Capacitor's legacy bridge (`android.useLegacyBridge`, its
README: otherwise fixes stop after five minutes in the background), still with Capacitor 8 and
1.2.26. That bridge is a `WebView.addJavascriptInterface` object, which Android hands to every page and
frame the WebView shows, Discord's sign-in pages included. `GuardedBridge.java` replaces it with an
object of the same name that passes a call to the plugins only while the WebView's top-level page is
the kept site (`SiteWebViewClient.topLevelIsSite()`: cleared before a top-level navigation leaves the
site, set as each top-level page starts); any other call is dropped. It reaches Capacitor's handler by
its private field name (pinned Capacitor 8.5.3; `npm test` fails if a Capacitor bump moves it, and if
it cannot be found at run time the bridge is removed rather than left open). What it cannot tell apart:
a frame inside the site's own page (the site embeds none), and the moment between a back or forward
navigation's commit and its `onPageStarted`.

## Privacy

Positions stay on the phone, as on the website: the plugin hands each fix to the page, the page uses
it for the cues and forgets it, and nothing sends the rider's position to the server (a re-plan sends
the route request, as today). No analytics, no crash reporting, no tracking SDK. The manifest asks for
the network, location (fine and coarse, "while using the app"; never `ACCESS_BACKGROUND_LOCATION`),
the location foreground service, and notifications; the local-notifications plugin's boot, exact-alarm
and wake-lock permissions are removed, and `allowBackup` is off and `dataExtractionRules`
(`res/xml/data_extraction_rules.xml`) exclude everything, so the site's data in the app never goes to
a cloud backup or, on Android 12+, to a new phone by device transfer. The plugin's location service is
declared not exported (only the app binds it), and a GPS is not required to install. A "Latest cue"
notification is cleared when the app starts and when the site's screen goes, so none is left stale. The site address is kept in the app's private preferences only; the
basic-auth password is never kept by the app (above). `mobile/test/config.test.mjs` holds the
permission list.

## Building

**Workflow** (`.github/workflows/android.yml`): on a pull request that touches `mobile/` or the
workflow, a debug build only; by hand (Run workflow), debug or release; never on a push. Node 22, JDK
21, the runner's Android SDK; `npm ci`, `npm test`, `npx cap sync android`, a check that the synced
config names no site, `./gradlew testDebugUnitTest`, then the APK. The checkout keeps no token
(`persist-credentials: false`); actions are pinned by commit. A pull request's debug APK names no site,
so it is fine as a public artifact. It uses no repository variables. The application id comes from the
`ROUTEMAKER_APP_ID` secret (the owner's reverse domain), for test and store builds alike, so one installs
over the other; without it (a fork's pull request) it is `org.routemaker.phone`. These repository secrets:

| Name | Kind | Used for |
| --- | --- | --- |
| `ROUTEMAKER_KEYSTORE_BASE64` | secret | the release keystore, `base64 -w0 release.jks` |
| `ROUTEMAKER_KEYSTORE_PASSWORD` | secret | its password |
| `ROUTEMAKER_KEY_ALIAS` | secret | the key's alias |
| `ROUTEMAKER_KEY_PASSWORD` | secret | the key's password |
| `ROUTEMAKER_DEBUG_KEYSTORE_BASE64` | secret | optional: a steady key for debug builds only, `base64 -w0 debug.keystore` |
| `ROUTEMAKER_APP_ID` | secret | the application id, such as `com.example.app`; permanent once on Play |
| `ROUTEMAKER_SITE_URL` | secret | the site's https origin, baked into the release (store) build only |

The debug key uses Android's standard debug passwords (`android`) and alias (`androiddebugkey`), so it
is one secret. Make it once with
`keytool -genkeypair -v -keystore debug.keystore -storepass android -keypass android -alias androiddebugkey -dname "CN=Android Debug,O=Android,C=US" -keyalg RSA -keysize 2048 -validity 10000`.
(On macOS, `base64 -i debug.keystore`.) It never signs a release. Pull requests from this
repository's branches and by-hand runs use it too (forks and Dependabot get no secrets and fall back
to a fresh key), so it is only as private as write access here. Anyone holding it could make an APK
that installs over a test build and keeps its data (site address, sign-in, Home), so sideload only
the workflow's own artifacts. A local build still uses your own `~/.android/debug.keystore` unless
`ROUTEMAKER_DEBUG_KEYSTORE_FILE` points at this key.

A `release` run is the store build. It fails at once without the four key secrets or
`ROUTEMAKER_SITE_URL`, bakes the site in (so testers are never asked for it; the owner agreed on
2026-10-21 that the address may be public in this build), writes the key to the runner's temporary
directory only, and uploads a signed APK and an `.aab` for Play, kept 3 days. Debug builds still name no site. Make the keystore once, keep it and
its passwords safe (losing it means a new Play listing):
`keytool -genkeypair -v -keystore release.jks -alias routemaker -keyalg RSA -keysize 4096 -validity 10000`.
Never commit it (`mobile/.gitignore` refuses `*.jks` and `*.keystore`).

**Locally** (Android Studio or the SDK installed, JDK 21):

```sh
cd mobile
npm ci
npm test
npx cap sync android
cd android && ./gradlew test assembleDebug    # app/build/outputs/apk/debug/app-debug.apk
```

Optional, for a local build (in CI only for the release run, which sets `ROUTEMAKER_STORE_BUILD=1`;
`site-config.js` refuses it there otherwise):
`ROUTEMAKER_URL=https://your.site npx cap sync android` builds the address in, and the app then opens
it without asking (the first-launch screen says so if opened). For a development server,
`ROUTEMAKER_URL=http://10.0.2.2:5173 ROUTEMAKER_ALLOW_HTTP=1` (the emulator's address for the host).
The resolved config, with the address, is written to `android/app/src/main/assets/capacitor.config.json`,
which is git-ignored; run `npx cap sync android` again without it before building anything to share.
Such an APK names the server: keep it off public places. `ROUTEMAKER_APP_ID` sets the application id
(a reverse domain you own, for a Play listing) in a local build the same way.
`ROUTEMAKER_DEBUG=1` turns on Chrome's inspector (`chrome://inspect`).

## Files

- `site-config.js`: the Capacitor config (`capacitor.config.js` calls it); no site address unless a
  local build sets `ROUTEMAKER_URL`.
- `www/offline.html`: shown when the site cannot be reached at launch; `www/index.html`: a placeholder
  shown for a moment if the site's screen opens with no address kept.
- `android/`: the generated Android project, plus, in `app/src/main/java/org/routemaker/phone/`:
  `SetupActivity.java` (the launcher: the first-launch "Which RouteMaker site?" screen,
  `res/layout/activity_setup.xml`), `SiteAddress.java` (the address and `/healthz` checks, unit-tested
  in `app/src/test`), `SiteStore.java` (the app's preferences), `MainActivity.java` (puts the kept
  address into Capacitor's config, registers the plugin below), `SiteWebViewClient.java` (the basic-auth
  sign-in box, `res/layout/dialog_site_login.xml`, and which page is on top), `GuardedBridge.java`
  (the native bridge for the site only) and `RideCompatPlugin.java`;
  `assets/routemaker-compat.js`, `res/drawable/ic_ride.xml` (the notifications' icon), the launcher icons
  and launch screens (drawn from the site's favicon by `scripts/make_app_icons.py`), the manifest and
  `app/build.gradle` (store id, version and release signing from the environment).
- `test/`: `npm test` (node's test runner): the config, the manifest, the workflow (its triggers, no
  repository variables, no address), the first-launch screen's labels, the bridge guard, and the
  compatibility layer in a stand-in page. `./gradlew testDebugUnitTest` runs `SiteAddressTest` (needs
  the Android SDK); the workflow runs both on each pull request that touches `mobile/`. The site's bridge is tested in
  `frontend/src/lib/nativeShell.test.ts`.

Plugin versions are pinned in `package.json`. `@capacitor-community/background-geolocation` 1.2.26
says it is built for Capacitor 7 (its peer range allows 8); it is the maintained free plugin, and the
first workflow build is the check that it compiles against Capacitor 8.
