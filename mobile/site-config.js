// RouteMaker's phone app (v0.8.0): the Capacitor config, built from the environment (capacitor.config.js
// is the one line that calls it; test/config.test.mjs tests it). The shell loads the live site, so Ride
// mode's cues go on with the screen locked (frontend/src/lib/nativeShell.ts is the site's side).
//
// The site's address is never committed. It is read at build time from ROUTEMAKER_URL (the workflow
// takes it from the repository variable of the same name); without it the placeholder below is used,
// which loads nothing, so a build without the variable is plainly not a release.
//
// Run `npx cap sync android` after changing this file or the variables: sync writes the resolved config
// into android/app/src/main/assets/capacitor.config.json, which is git-ignored, so the address stays out
// of git.

const PLACEHOLDER_URL = "https://routes.example.org";

/**
 * The site's address from the environment: an https origin, or http only with ROUTEMAKER_ALLOW_HTTP=1
 * (a development server on the LAN or the Android emulator's 10.0.2.2). A path, query or fragment is
 * refused: the shell loads the site's front page, as the installable app does.
 */
function siteUrl(env) {
  const raw = (env.ROUTEMAKER_URL || "").trim() || PLACEHOLDER_URL;
  let url;
  try {
    url = new URL(raw);
  } catch {
    throw new Error(`ROUTEMAKER_URL is not a URL: ${JSON.stringify(raw)}`);
  }
  const http = env.ROUTEMAKER_ALLOW_HTTP === "1";
  if (url.protocol !== "https:" && !(http && url.protocol === "http:")) {
    throw new Error("ROUTEMAKER_URL must be https:// (set ROUTEMAKER_ALLOW_HTTP=1 for a development server over http)");
  }
  if ((url.pathname !== "/" && url.pathname !== "") || url.search || url.hash || url.username || url.password) {
    throw new Error("ROUTEMAKER_URL must be the site's origin alone, such as https://routes.example.org");
  }
  return { url: url.origin, cleartext: url.protocol === "http:", placeholder: url.origin === PLACEHOLDER_URL };
}

function buildConfig(env = process.env) {
  const site = siteUrl(env);
  return {
    // The Android namespace. The store id (applicationId) is ROUTEMAKER_APP_ID in android/app/build.gradle,
    // so the owner's own reverse domain never has to be committed.
    appId: "org.routemaker.phone",
    appName: "RouteMaker",
    // Unused while server.url is set except for the error page: the site itself is never bundled.
    webDir: "www",
    server: {
      url: site.url,
      cleartext: site.cleartext,
      // Sign-in (/auth/login) is a round trip through Discord's authorize page: kept in the app, so the
      // session cookie lands in the app's WebView. Any other site opens in the phone's browser. The
      // native bridge and the compatibility script are given to the site's own origin only.
      allowNavigation: ["discord.com"],
      // Shown when the site cannot be reached at launch (no signal).
      errorPath: "offline.html",
    },
    android: {
      // @capacitor-community/background-geolocation: keeps fixes reaching the page after 5 minutes in
      // the background (its README, issue 89).
      useLegacyBridge: true,
      allowMixedContent: false,
      // Chrome's remote inspector only for a development build.
      webContentsDebuggingEnabled: env.ROUTEMAKER_DEBUG === "1",
    },
    plugins: {
      // Android 15+ draws edge to edge: the WebView is padded to the safe area (the site does not ask for
      // viewport-fit=cover), and no CSS variables are injected into the site.
      SystemBars: { insetsHandling: "native" },
      // Android's cue notification uses the app's monochrome ride icon (res/drawable/ic_ride.xml).
      LocalNotifications: { smallIcon: "ic_ride" },
    },
  };
}

module.exports = { buildConfig, siteUrl, PLACEHOLDER_URL };
