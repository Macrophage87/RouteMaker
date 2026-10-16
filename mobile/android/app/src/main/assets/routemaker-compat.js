/*
 * RouteMaker phone app: the compatibility layer for a site older than v0.8.0 (mobile/README.md).
 *
 * The app loads the live site. From v0.8.0 the site's own bridge (frontend/src/lib/nativeShell.ts) uses
 * the native plugins directly and marks the page with window.__routemakerNativeShell; this layer then
 * does nothing. A site deployed before v0.8.0 knows nothing of the app, so, until v0.8.0 is deployed,
 * this layer gives its Ride mode the same three things from outside, through the browser APIs it
 * already calls:
 *
 * - navigator.geolocation.watchPosition / clearWatch: the background-geolocation plugin (fixes go on
 *   with the screen locked; Android's "Riding with RouteMaker" notification while a watch runs).
 *   getCurrentPosition ("Use my location") is the WebView's own, untouched.
 * - speechSynthesis / SpeechSynthesisUtterance: the native text-to-speech plugin, which speaks with the
 *   screen locked.
 * - while a native watch runs, the page is told it is visible, so the old Ride mode's ten-minute
 *   "paused while the page was in the background" never comes; and navigator.wakeLock, where the
 *   WebView has none, answers with a lock that needs nothing, so the old page does not tell the rider
 *   to keep the screen on.
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
  var nativeWatches = {};
  var liveWatches = 0;
  var nextWatch = 1000000;
  var geo = w.navigator && w.navigator.geolocation;
  if (geo) {
    var browserWatch = geo.watchPosition.bind(geo);
    var browserClear = geo.clearWatch.bind(geo);
    geo.watchPosition = function (ok, fail, options) {
      var cap = active() ? bridge() : null;
      if (!cap) return browserWatch(ok, fail, options);
      nextWatch += 1;
      var id = nextWatch;
      var error = function (code, message) {
        if (typeof fail === "function") fail({ code: code, message: message || "", PERMISSION_DENIED: 1, POSITION_UNAVAILABLE: 2, TIMEOUT: 3 });
      };
      var callbackId;
      try {
        callbackId = cap.nativeCallback(
          "BackgroundGeolocation",
          "addWatcher",
          { backgroundTitle: TITLE, backgroundMessage: MESSAGE, requestPermissions: true, stale: false, distanceFilter: 0 },
          function (data, err) {
            if (nativeWatches[id] === undefined) return;
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
        error(2, "The location service could not start.");
        return id;
      }
      nativeWatches[id] = callbackId;
      liveWatches += 1;
      return id;
    };
    geo.clearWatch = function (id) {
      if (nativeWatches[id] === undefined) return browserClear(id);
      var callbackId = nativeWatches[id];
      delete nativeWatches[id];
      liveWatches -= 1;
      var cap = bridge();
      if (cap) quiet(cap.nativePromise("BackgroundGeolocation", "removeWatcher", { id: callbackId }));
    };
  }

  // ---- Visible while riding ------------------------------------------------------------------------
  function riding() {
    return liveWatches > 0 && active();
  }
  var proto = w.Document && w.Document.prototype;
  var visibility = proto && Object.getOwnPropertyDescriptor(proto, "visibilityState");
  var hiddenProp = proto && Object.getOwnPropertyDescriptor(proto, "hidden");
  if (visibility && visibility.get && hiddenProp && hiddenProp.get) {
    Object.defineProperty(w.document, "visibilityState", {
      configurable: true,
      get: function () {
        return riding() ? "visible" : visibility.get.call(w.document);
      },
    });
    Object.defineProperty(w.document, "hidden", {
      configurable: true,
      get: function () {
        return riding() ? false : hiddenProp.get.call(w.document);
      },
    });
    // The window's capture listener runs before any on the document: the page never hears the change.
    w.addEventListener(
      "visibilitychange",
      function (event) {
        if (riding()) event.stopImmediatePropagation();
      },
      true,
    );
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
