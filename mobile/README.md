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

There are no new buttons: Start ride, Go and End work as on the website. Distances are the site's
own (feet and miles).

iOS can be added later from the same shell (`npx cap add ios` on a Mac, plus the location and audio
background modes); the web side is already platform-neutral.

## How a test APK gets working cues before v0.8.0 is deployed

The app loads whatever site `ROUTEMAKER_URL` names, so it has to work with the code that site runs.
There are two layers, and exactly one of them is active on any page:

1. **The site's own bridge, from v0.8.0** (`frontend/src/lib/nativeShell.ts`). It detects the shell
   (`window.Capacitor.isNativePlatform()`), calls the plugins directly through the injected bridge
   object (no Capacitor package in the web bundle), and marks the page with
   `window.__routemakerNativeShell`. It also adds the cue notification, never pauses a ride when the
   page is hidden, and speaks "My screen reader" cues aloud while the page is hidden (below).
2. **The app's compatibility layer, for a site older than v0.8.0**
   (`android/app/src/main/assets/routemaker-compat.js`, injected at document start for the site's
   origin only by `RideCompatPlugin.java`). The old Ride mode knows nothing of the app, so this layer
   swaps the browser APIs it already calls: `navigator.geolocation.watchPosition`/`clearWatch` go to
   the background-location plugin, `speechSynthesis` goes to the native voice, and while a native watch
   runs the page is told it is visible (so the old ten-minute pause never comes). Where the WebView has
   no screen wake lock, it answers with a stand-in so the old page does not say "keep your screen on".
   `getCurrentPosition` ("Use my location") is left alone. When the page carries the v0.8.0 mark, the
   layer stands aside entirely.

So a debug APK pointed at the current beta or live site should keep the GPS and the voice going with
the screen locked today, without deploying anything. What the old site cannot have until v0.8.0 is
deployed: the "Latest cue" notification, "My screen reader" spoken while locked, and the wording of
the Ride mode safety note (it still says the screen must stay on).

**The server needs no change.** The WebView loads the site at its own origin, so cookies, CSRF
(`CSRF_TRUSTED_ORIGINS`, `SESSION_COOKIE_SAMESITE = "Lax"`) and same-origin API calls are exactly a
phone browser's; no CORS is involved. The Discord sign-in round trip stays inside the app
(`server.allowNavigation: ["discord.com"]`), so the session cookie lands in the app's WebView. Two
alternatives were set aside: bundling the built front end in the APK would make every `/api` and
tile request cross-origin (CORS and cookie changes on the server, and MapLibre's tile workers do not
go through Capacitor's native HTTP), and serving the bundle under the site's hostname makes
Capacitor answer `/api` locally.

## Installing a test build on an Android phone

1. In the repository's **Settings, Secrets and variables, Actions, Variables**, add
   `ROUTEMAKER_URL` = the site's origin (for example the beta's `https://...`, no path). Optional:
   `ROUTEMAKER_APP_ID` (the Play Store id, a reverse domain you own; default `org.routemaker.phone`).
2. **Actions, "Android app", Run workflow**, build `debug`. When it finishes, download the artifact
   `routemaker-android-debug-N` (a zip holding `app-debug.apk`).
3. On the phone, open the APK (from Files, Drive or a USB copy) and allow "Install unknown apps" for
   the app you opened it with. Play Protect may warn that the app is unknown; choose to install anyway.
4. Open RouteMaker, plan a route, press Go and Start ride. Android asks for location ("While using the
   app"), then, at the first cue, for notifications (Android 13+). Lock the phone and ride.

Each workflow run signs its debug build with a fresh debug key, so a newer debug APK will not install
over an older one: uninstall first (the site's data in the app, such as a Home, goes with it).

What to check on the first ride (none of this could be tried here: there is no Android SDK or phone
in the build environment):

- the "Riding with RouteMaker" notification appears at Start ride and goes at End ride;
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

## Privacy

Positions stay on the phone, as on the website: the plugin hands each fix to the page, the page uses
it for the cues and forgets it, and nothing sends the rider's position to the server (a re-plan sends
the route request, as today). No analytics, no crash reporting, no tracking SDK. The manifest asks for
the network, location (fine and coarse, "while using the app"; never `ACCESS_BACKGROUND_LOCATION`),
the location foreground service, and notifications; the local-notifications plugin's boot, exact-alarm
and wake-lock permissions are removed, and `allowBackup` is off so the site's data in the app never
goes to a cloud backup. `mobile/test/config.test.mjs` holds the permission list.

## Building

**Workflow** (`.github/workflows/android.yml`, run by hand only): Node 22, JDK 21, the runner's Android
SDK; `npm ci`, `npm test`, `npx cap sync android`, then Gradle.

| Name | Kind | Used for |
| --- | --- | --- |
| `ROUTEMAKER_URL` | variable | the site's origin the app opens (required for a useful build) |
| `ROUTEMAKER_APP_ID` | variable | the Android application id (optional) |
| `ROUTEMAKER_KEYSTORE_BASE64` | secret | the release keystore, `base64 -w0 release.jks` |
| `ROUTEMAKER_KEYSTORE_PASSWORD` | secret | its password |
| `ROUTEMAKER_KEY_ALIAS` | secret | the key's alias |
| `ROUTEMAKER_KEY_PASSWORD` | secret | the key's password |

A `release` run fails at once without the four secrets, writes the key to the runner's temporary
directory only, and uploads a signed APK and an `.aab` for Play. Make the keystore once, keep it and
its passwords safe (losing it means a new Play listing):
`keytool -genkeypair -v -keystore release.jks -alias routemaker -keyalg RSA -keysize 4096 -validity 10000`.
Never commit it (`mobile/.gitignore` refuses `*.jks` and `*.keystore`).

**Locally** (Android Studio or the SDK installed, JDK 21):

```sh
cd mobile
npm ci
npm test
ROUTEMAKER_URL=https://your.site npx cap sync android
cd android && ./gradlew assembleDebug    # app/build/outputs/apk/debug/app-debug.apk
```

`ROUTEMAKER_DEBUG=1` turns on Chrome's inspector (`chrome://inspect`). For a development server,
`ROUTEMAKER_URL=http://10.0.2.2:5173 ROUTEMAKER_ALLOW_HTTP=1` (the emulator's address for the host);
the resolved config, with the address, is written to `android/app/src/main/assets/capacitor.config.json`,
which is git-ignored.

## Files

- `site-config.js`: the Capacitor config built from the environment (`capacitor.config.js` calls it).
- `www/offline.html`: shown when the site cannot be reached at launch.
- `android/`: the generated Android project, plus `RideCompatPlugin.java`, `MainActivity.java` (which
  registers it), `assets/routemaker-compat.js`, `res/drawable/ic_ride.xml` (the notifications' icon),
  the manifest and `app/build.gradle` (store id, version and release signing from the environment).
- `test/`: `npm test` (node's test runner): the config, the manifest, the workflow's trigger, and the
  compatibility layer in a stand-in page. The site's bridge is tested in
  `frontend/src/lib/nativeShell.test.ts`.

Plugin versions are pinned in `package.json`. `@capacitor-community/background-geolocation` 1.2.26
says it is built for Capacitor 7 (its peer range allows 8); it is the maintained free plugin, and the
first workflow build is the check that it compiles against Capacitor 8.
