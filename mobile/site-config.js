// RouteMaker's phone app (v0.8.0): the Capacitor config (capacitor.config.js is the one line that calls
// it; test/config.test.mjs tests it). The shell loads the live site, so Ride mode's cues go on with the
// screen locked (frontend/src/lib/nativeShell.ts is the site's side).
//
// No test build carries a site address: the repository is public, and so are its Actions artifacts. On
// first launch the app asks for the address and keeps it on the phone (SetupActivity.java). For a
// local build, and for the store build CI makes by hand, ROUTEMAKER_URL bakes one in; `npx cap sync
// android` writes it to android/app/src/main/assets/capacitor.config.json, which is git-ignored.

/**
 * The local override from ROUTEMAKER_URL: an https origin, or http only with ROUTEMAKER_ALLOW_HTTP=1
 * (a development server on the LAN or the Android emulator's 10.0.2.2). A path, query or fragment is
 * refused: the shell loads the site's front page, as the installable app does. Null when unset.
 */
function siteUrl(env) {
  const raw = (env.ROUTEMAKER_URL || "").trim();
  if (!raw) return null;
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
  // CI may bake an address in only for the owner's by-hand store build (android.yml's release run,
  // ROUTEMAKER_STORE_BUILD=1, the address from the ROUTEMAKER_SITE_URL secret). Test builds name none.
  if (env.CI && env.ROUTEMAKER_STORE_BUILD !== "1") {
    throw new Error("ROUTEMAKER_URL is for local builds and the store build only: a CI test build is public and must name no server");
  }
  return { url: url.origin, cleartext: url.protocol === "http:" };
}

function buildConfig(env = process.env) {
  const site = siteUrl(env);
  const server = {
    // Sign-in (/auth/login) is a round trip through Discord's authorize page: kept in the app, so the
    // session cookie lands in the app's WebView. Any other site opens in the phone's browser. The
    // compatibility script is injected for the site's own origin only (RideCompatPlugin.java); the
    // native bridge reaches every page the WebView shows, Discord's too, so GuardedBridge.java passes
    // its calls to the plugins only while the top-level page is the kept site.
    allowNavigation: ["discord.com"],
    // Shown when the site cannot be reached at launch (no signal).
    errorPath: "offline.html",
  };
  if (site) {
    server.url = site.url;
    server.cleartext = site.cleartext;
  }
  return {
    // The Android namespace. The store id (applicationId) is ROUTEMAKER_APP_ID in android/app/build.gradle,
    // so the owner's own reverse domain never has to be committed.
    appId: "org.routemaker.phone",
    appName: "RouteMaker",
    // Holds only the error page and a placeholder: the site itself is never bundled.
    webDir: "www",
    server,
    android: {
      // @capacitor-community/background-geolocation: keeps fixes reaching the page after 5 minutes in
      // the background (its README, issue 89). Still needed with Capacitor 8 and plugin 1.2.26. The
      // legacy bridge is a JavaScript interface on every page and frame, whatever its origin (Discord's
      // sign-in pages too): GuardedBridge.java drops each call unless the top-level page is the site.
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

module.exports = { buildConfig, siteUrl };
