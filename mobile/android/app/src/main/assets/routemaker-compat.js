/*
 * RouteMaker phone app: the compatibility layer for a site older than v0.8.0 (mobile/README.md).
 *
 * The app loads the live site. From v0.8.0 the site's own bridge (frontend/src/lib/nativeShell.ts) uses
 * the native plugins directly and marks the page with window.__routemakerNativeShell; this layer then
 * does nothing. A site deployed before v0.8.0 knows nothing of the app, so, until v0.8.0 is deployed,
 * this layer gives its Ride mode the same three things from outside, through the browser APIs it
 * already calls:
 *
 * - navigator.geolocation.watchPosition / clearWatch, for Ride mode's navigation watch only: the
 *   background-geolocation plugin (fixes go on with the screen locked; Android's "Riding with
 *   RouteMaker" notification while it runs). A watch goes native only when Ride mode's screen
 *   (`section.ride[aria-labelledby="ride-heading"]`, RideMode.tsx since v0.6) is on the page as it
 *   starts: Ride mode starts its watch from that screen (the Start ride press). Any watch started
 *   without that screen, and getCurrentPosition ("Use my location"), stay the WebView's own.
 *   Group and Mass Ride location sharing (RideGroup.tsx) must never go native: it promises to run
 *   only while the page is in front. The two watches use the same options, so they cannot be told apart
 *   by the call; what keeps sharing out: (1) the sites this layer serves (v0.6 to v0.7) have Ride
 *   mode's watch as their only watchPosition, and sharing arrived with v0.8.0, whose own bridge marks
 *   the page, so this layer stands aside there; (2) the screen test above; (3) the page still hears
 *   visibilitychange (never touched here), and sharing stops its watch when the page is hidden.
 * - speechSynthesis / SpeechSynthesisUtterance: the native text-to-speech plugin, which speaks with the
 *   screen locked.
 * - the old Ride mode's ten-minute pause: while a native ride watch runs and the page is hidden, its
 *   one setTimeout of exactly HIDDEN_STOP_MS (10 minutes, RideMode.tsx) is not scheduled, so "Ride
 *   paused while the page was in the background" never comes. The page still hears that it is hidden
 *   (visibilitychange is never touched), so anything else on it that stops when hidden still does.
 * - navigator.wakeLock, where the WebView has none, answers with a lock that needs nothing, so the old
 *   page does not tell the rider to keep the screen on.
 *
 * Injected by RideCompatPlugin.java at document start, for the site's origin only, before Capacitor's
 * own bridge script: so window.Capacitor is looked up at each call, never at load. Nothing here stores,
 * logs or sends a position: each fix goes to the page's callback and is forgotten.
 */
(function () {
  "use strict";
  var w = window;
  if (w.__routemakerCompat) return;
  w.__routemakerCompat = true;

  var TITLE = "Riding with RouteMaker";
  var MESSAGE = "Your location is used for Ride mode's cues and stays on this phone. End the ride to stop.";

  function bridge() {
    var c = w.Capacitor;
    try {
      if (c && typeof c.isNativePlatform === "function" && c.isNativePlatform() === true && typeof c.nativeCallback === "function" && typeof c.nativePromise === "function") return c;
    } catch (e) {
      return null;
    }
    return null;
  }
  /** Only for a site without its own bridge, and only inside the native shell. */
  function active() {
    return w.__routemakerNativeShell !== true && bridge() !== null;
  }
  function quiet(promise) {
    if (promise && typeof promise.then === "function") promise.then(null, function () {});
  }

  // ---- The position --------------------------------------------------------------------------------
  /** Ride mode's screen is on the page (its Start ride press starts the watch). */
  function rideScreen() {
    var doc = w.document;
    return !!(doc && typeof doc.querySelector === "function" && doc.querySelector('section.ride[aria-labelledby="ride-heading"]'));
  }
  var nativeWatches = {};
  var liveWatches = 0;
  var nextWatch = 1000000;
  var geo = w.navigator && w.navigator.geolocation;
  if (geo) {
    var browserWatch = geo.watchPosition.bind(geo);
    var browserClear = geo.clearWatch.bind(geo);
    geo.watchPosition = function (ok, fail, options) {
      var cap = active() && rideScreen() ? bridge() : null;
      if (!cap) return browserWatch(ok, fail, options);
      nextWatch += 1;
      var id = nextWatch;
      var error = function (code, message) {
        if (typeof fail === "function") fail({ code: code, message: message || "", PERMISSION_DENIED: 1, POSITION_UNAVAILABLE: 2, TIMEOUT: 3 });
      };
      // "" while the permission questions are open; then the plugin's callback id.
      nativeWatches[id] = "";
      liveWatches += 1;
      var drop = function () {
        if (nativeWatches[id] === undefined) return;
        delete nativeWatches[id];
        liveWatches -= 1;
      };
      var addWatcher = function () {
        if (nativeWatches[id] !== "") return; // End ride while asking
        var callbackId;
        try {
          // Never the plugin's own permission request (1.2.26 starts its foreground service before the
          // answer, which Android 14+ refuses, so the first ride would stop at the screen lock): asked above.
          callbackId = cap.nativeCallback(
            "BackgroundGeolocation",
            "addWatcher",
            { backgroundTitle: TITLE, backgroundMessage: MESSAGE, requestPermissions: false, stale: false, distanceFilter: 0 },
            function (data, err) {
              if (nativeWatches[id] !== callbackId) return;
              if (err || !data) {
                error(err && err.code === "NOT_AUTHORIZED" ? 1 : 2, err && err.message);
                return;
              }
              ok({
                coords: {
                  latitude: data.latitude,
                  longitude: data.longitude,
                  accuracy: data.accuracy,
                  altitude: data.altitude === undefined ? null : data.altitude,
                  altitudeAccuracy: data.altitudeAccuracy === undefined ? null : data.altitudeAccuracy,
                  heading: data.bearing === undefined ? null : data.bearing,
                  speed: data.speed === undefined ? null : data.speed,
                },
                timestamp: typeof data.time === "number" ? data.time : Date.now(),
              });
            },
          );
        } catch (e) {
          drop();
          error(2, "The location service could not start.");
          return;
        }
        nativeWatches[id] = callbackId;
      };
      // At Start ride: location, then notifications (Android 13+, for the "Riding with RouteMaker"
      // notification), then the watcher; nothing is asked mid-ride. Granted already: no dialog.
      var asked;
      try {
        asked = cap.nativePromise("BackgroundGeolocation", "requestPermissions", { permissions: ["location"] });
      } catch (e) {
        asked = null;
      }
      if (!asked || typeof asked.then !== "function") {
        drop();
        error(2, "The location service could not start.");
        return id;
      }
      asked.then(
        function (answer) {
          if (nativeWatches[id] !== "") return;
          if (!answer || answer.location !== "granted") {
            drop();
            error(1, "Location permission refused.");
            return;
          }
          var shown = null;
          try {
            shown = cap.nativePromise("LocalNotifications", "requestPermissions", { permissions: ["display"] });
          } catch (e) {
            shown = null;
          }
          if (shown && typeof shown.then === "function") shown.then(addWatcher, addWatcher);
          else addWatcher();
        },
        function (e) {
          if (nativeWatches[id] !== "") return;
          drop();
          error(2, e && e.message);
        },
      );
      return id;
    };
    geo.clearWatch = function (id) {
      if (nativeWatches[id] === undefined) return browserClear(id);
      var callbackId = nativeWatches[id];
      delete nativeWatches[id];
      liveWatches -= 1;
      var cap = bridge();
      if (cap && callbackId) quiet(cap.nativePromise("BackgroundGeolocation", "removeWatcher", { id: callbackId }));
    };
  }

  // ---- No ten-minute pause while riding -------------------------------------------------------------
  /** RideMode.tsx's HIDDEN_STOP_MS (v0.6 to v0.7): the only 10-minute setTimeout on those pages. */
  var HIDDEN_STOP_MS = 600000;
  function riding() {
    return liveWatches > 0 && active();
  }
  function hidden() {
    var doc = w.document;
    return !!(doc && doc.visibilityState === "hidden");
  }
  var browserTimeout = w.setTimeout;
  if (typeof browserTimeout === "function") {
    var skipped = -1;
    w.setTimeout = function (fn, ms) {
      if (ms === HIDDEN_STOP_MS && riding() && hidden()) {
        // Not scheduled: the pause would stop the native watch the rider pocketed the phone for.
        skipped -= 1;
        return skipped;
      }
      return browserTimeout.apply(w, arguments);
    };
  }

  // ---- The voice -----------------------------------------------------------------------------------
  var BrowserUtterance = w.SpeechSynthesisUtterance;
  var browserSynth = w.speechSynthesis;
  function NativeUtterance(text) {
    if (!active() && typeof BrowserUtterance === "function") return new BrowserUtterance(text);
    this.text = text === undefined ? "" : String(text);
    this.lang = "";
    this.rate = 1;
    this.pitch = 1;
    this.volume = 1;
    this.voice = null;
    this.onstart = null;
    this.onend = null;
    this.onerror = null;
  }
  var speaking = false;
  var turn = 0;
  var synth = {
    get speaking() {
      return speaking || !!(browserSynth && browserSynth.speaking);
    },
    get pending() {
      return !!(browserSynth && browserSynth.pending);
    },
    get paused() {
      return !!(browserSynth && browserSynth.paused);
    },
    speak: function (utterance) {
      var cap = bridge();
      if (!(utterance instanceof NativeUtterance) || !cap) {
        if (browserSynth) browserSynth.speak(utterance);
        return;
      }
      turn += 1;
      var mine = turn;
      speaking = true;
      var done = function () {
        if (mine !== turn) return;
        speaking = false;
        if (typeof utterance.onend === "function") utterance.onend({ type: "end", utterance: utterance });
      };
      if (typeof utterance.onstart === "function") utterance.onstart({ type: "start", utterance: utterance });
      cap
        .nativePromise("TextToSpeech", "speak", {
          text: utterance.text,
          lang: utterance.lang || "en-US",
          rate: typeof utterance.rate === "number" ? utterance.rate : 1,
          pitch: typeof utterance.pitch === "number" ? utterance.pitch : 1,
          volume: typeof utterance.volume === "number" ? utterance.volume : 1,
          queueStrategy: 0,
        })
        .then(done, done);
    },
    cancel: function () {
      if (browserSynth) browserSynth.cancel();
      if (!speaking) return;
      turn += 1;
      speaking = false;
      var cap = bridge();
      if (cap) quiet(cap.nativePromise("TextToSpeech", "stop", {}));
    },
    pause: function () {
      if (browserSynth) browserSynth.pause();
    },
    resume: function () {
      if (browserSynth) browserSynth.resume();
    },
    getVoices: function () {
      return browserSynth ? browserSynth.getVoices() : [];
    },
    addEventListener: function (type, listener, options) {
      if (browserSynth) browserSynth.addEventListener(type, listener, options);
    },
    removeEventListener: function (type, listener, options) {
      if (browserSynth) browserSynth.removeEventListener(type, listener, options);
    },
  };
  try {
    Object.defineProperty(w, "SpeechSynthesisUtterance", { configurable: true, writable: true, value: NativeUtterance });
    Object.defineProperty(w, "speechSynthesis", { configurable: true, get: function () { return synth; } });
  } catch (e) {
    // A WebView that will not let these be replaced: the old page keeps Web Speech.
  }

  // ---- The screen wake lock ------------------------------------------------------------------------
  var nav = w.navigator;
  var browserWake = nav && nav.wakeLock;
  if (nav && !browserWake) {
    try {
      Object.defineProperty(nav, "wakeLock", {
        configurable: true,
        get: function () {
          if (!active()) return undefined;
          return {
            request: function () {
              var released = false;
              return Promise.resolve({
                get released() {
                  return released;
                },
                type: "screen",
                release: function () {
                  released = true;
                  return Promise.resolve();
                },
                addEventListener: function () {},
                removeEventListener: function () {},
              });
            },
          };
        },
      });
    } catch (e) {
      // Left as it is: the old page then says the screen may turn off, which is only a note.
    }
  }
})();
