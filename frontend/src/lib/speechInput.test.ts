// Speak an alert's words (lib/speechInput.ts; Stephen 2026-10-22, "yes. option 2").
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { LISTENING_SAID, SPEECH_FAILED, SPEECH_INPUT_PLUGIN, SPEECH_OTHER_FAILED, listenOnce, speechSupported, type SpeechEnv } from "./speechInput.ts";
import type { CapacitorBridge } from "./nativeShell.ts";

class FakeRecognition {
  static last: FakeRecognition | null = null;
  lang = "";
  interimResults = false;
  continuous = true;
  maxAlternatives = 5;
  started = false;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null = null;
  onerror: ((event: { error?: string }) => void) | null = null;
  onend: (() => void) | null = null;
  constructor() {
    FakeRecognition.last = this;
  }
  start() {
    this.started = true;
  }
  stop() {
    this.onend?.();
  }
  abort() {}
}

const env = { webkitSpeechRecognition: FakeRecognition } as unknown as SpeechEnv;

test("Speak shows only where the browser turns speech into text", () => {
  assert.equal(speechSupported({}, null), false);
  assert.equal(speechSupported(env, null), true);
  assert.equal(listenOnce(() => {}, () => {}, 80, {}, null), null);
});

type Call = { plugin: string; method: string; options?: Record<string, unknown> };
/** A phone app's bridge: `plugins` it has; each listen answered by `answer`. */
function appBridge(plugins: string[], answer: () => Promise<unknown> = () => Promise.resolve({ text: "" })) {
  const calls: Call[] = [];
  const bridge: CapacitorBridge = {
    isNativePlatform: () => true,
    isPluginAvailable: (name) => plugins.includes(name),
    nativePromise: (plugin, method, options) => {
      calls.push({ plugin, method, options });
      return answer();
    },
    nativeCallback: () => "",
  };
  return { bridge, calls };
}
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

test("in the phone app, Speak shows only with the app's speech input (Stephen 2026-10-30), never the WebView's", () => {
  assert.equal(speechSupported(env, appBridge([]).bridge), false, "an app built before the plugin");
  assert.equal(speechSupported(env, appBridge([SPEECH_INPUT_PLUGIN]).bridge), true);
  assert.equal(speechSupported({}, appBridge([SPEECH_INPUT_PLUGIN]).bridge), true, "the WebView has no recognition of its own");
  const { bridge: noProbe } = appBridge([SPEECH_INPUT_PLUGIN]);
  assert.equal(speechSupported(env, { ...noProbe, isPluginAvailable: undefined }), false, "a bridge that cannot say is not assumed");
  assert.equal(speechSupported(env, null), true);
  assert.equal(listenOnce(() => {}, () => {}, 80, env, appBridge([]).bridge), null);
  // Android's speech input has the microphone, not the app.
  const manifest = readFileSync(new URL("../../../mobile/android/app/src/main/AndroidManifest.xml", import.meta.url), "utf8");
  assert.doesNotMatch(manifest, /RECORD_AUDIO/);
  const java = readFileSync(new URL("../../../mobile/android/app/src/main/java/org/routemaker/phone/SpeechPlugin.java", import.meta.url), "utf8");
  assert.match(java, /@CapacitorPlugin\(name = "RouteMakerSpeech"\)/);
  assert.match(java, /public void listen\(PluginCall call\)/);
  assert.match(java, /RecognizerIntent\.ACTION_RECOGNIZE_SPEECH/);
  const main = readFileSync(new URL("../../../mobile/android/app/src/main/java/org/routemaker/phone/MainActivity.java", import.meta.url), "utf8");
  assert.match(main, /registerPlugin\(SpeechPlugin\.class\);/);
});

test("the app's speech input: the words fill the box, cut to 80 characters; backing out says nothing", async () => {
  let answer: Promise<unknown> = Promise.resolve({ text: "  flat tire at the bridge " });
  const { bridge, calls } = appBridge([SPEECH_INPUT_PLUGIN], () => answer);
  const texts: string[] = [];
  const ends: (string | null)[] = [];
  assert.ok(listenOnce((t) => texts.push(t), (f) => ends.push(f), 80, {}, bridge));
  await settle();
  assert.equal(calls[0].plugin, "RouteMakerSpeech");
  assert.equal(calls[0].method, "listen");
  assert.equal(typeof calls[0].options?.lang, "string");
  assert.deepEqual(texts, ["flat tire at the bridge"]);
  assert.deepEqual(ends, [null]);
  answer = Promise.resolve({ text: "x".repeat(100) });
  listenOnce((t) => texts.push(t), (f) => ends.push(f), 80, {}, bridge);
  await settle();
  assert.equal(texts.at(-1)?.length, 80);
  answer = Promise.resolve({ text: "" });
  listenOnce((t) => texts.push(t), (f) => ends.push(f), 80, {}, bridge);
  await settle();
  assert.equal(texts.length, 2, "nothing heard: the box keeps what it had");
  assert.deepEqual(ends, [null, null, null]);
});

test("the app's speech input: a failure says what to do instead; a closed box drops late words", async () => {
  const fail = (code: unknown) => Object.assign(new Error("Speech did not work"), { code });
  const ends: (string | null)[] = [];
  for (const code of ["no-speech", "network", "audio-capture", "unavailable", "other", "toString", undefined]) {
    listenOnce(() => {}, (f) => ends.push(f), 80, {}, appBridge([SPEECH_INPUT_PLUGIN], () => Promise.reject(fail(code))).bridge);
  }
  await settle();
  assert.deepEqual(ends, [SPEECH_FAILED["no-speech"], SPEECH_FAILED.network, SPEECH_FAILED["audio-capture"], SPEECH_FAILED.unavailable, SPEECH_OTHER_FAILED, SPEECH_OTHER_FAILED, SPEECH_OTHER_FAILED]);
  const texts: string[] = [];
  const late: (string | null)[] = [];
  const listening = listenOnce((t) => texts.push(t), (f) => late.push(f), 80, {}, appBridge([SPEECH_INPUT_PLUGIN], () => Promise.resolve({ text: "too late" })).bridge)!;
  listening.abort();
  listening.abort();
  await settle();
  assert.deepEqual(texts, []);
  assert.deepEqual(late, [null], "ended once, at the abort, so Speak is not left pressed");
});

test("every failure code the app's speech input sends is one the page has words for", () => {
  const java = readFileSync(new URL("../../../mobile/android/app/src/main/java/org/routemaker/phone/SpeechPlugin.java", import.meta.url), "utf8");
  const codes = [...java.matchAll(/return "([a-z-]+)";/g), ...java.matchAll(/call\.reject\("[^"]*", "([a-z-]+)"/g)].map((m) => m[1]);
  assert.ok(codes.includes("unavailable") && codes.includes("no-speech"));
  for (const code of codes) assert.ok(code === "other" || Object.hasOwn(SPEECH_FAILED, code), code);
});

test("the words fill the box as they come, cut to the alert's 80 characters, and a stop ends it", () => {
  const texts: string[] = [];
  const ends: (string | null)[] = [];
  const { stop } = listenOnce((t) => texts.push(t), (f) => ends.push(f), 80, env)!;
  const rec = FakeRecognition.last!;
  assert.ok(rec.started && rec.interimResults && !rec.continuous);
  rec.onresult?.({ results: [[{ transcript: "flat tire " }], [{ transcript: "at the bridge" }]] });
  assert.equal(texts.at(-1), "flat tire at the bridge");
  rec.onresult?.({ results: [[{ transcript: "x".repeat(100) }]] });
  assert.equal(texts.at(-1)?.length, 80);
  stop();
  assert.deepEqual(ends, [null]);
});

test("a failure says what to do instead", () => {
  const ends: (string | null)[] = [];
  listenOnce(() => {}, (f) => ends.push(f), 80, env);
  const rec = FakeRecognition.last!;
  rec.onerror?.({ error: "not-allowed" });
  rec.onend?.();
  listenOnce(() => {}, (f) => ends.push(f), 80, env);
  FakeRecognition.last!.onerror?.({ error: "audio-capture" });
  FakeRecognition.last!.onend?.();
  listenOnce(() => {}, (f) => ends.push(f), 80, env);
  FakeRecognition.last!.onerror?.({ error: "service-not-allowed" });
  FakeRecognition.last!.onend?.();
  listenOnce(() => {}, (f) => ends.push(f), 80, env);
  FakeRecognition.last!.onerror?.({ error: "bad-grammar" });
  FakeRecognition.last!.onend?.();
  assert.deepEqual(ends, [SPEECH_FAILED["not-allowed"], SPEECH_FAILED["audio-capture"], SPEECH_FAILED["service-not-allowed"], SPEECH_OTHER_FAILED]);
  for (const said of Object.values(SPEECH_FAILED)) assert.match(said, /type the issue/i, "each says what to do instead");
});

test("Speak heads the alert panel: one press opens the box and listens; the quick alerts stay below (2026-10-30)", () => {
  const group = readFileSync(new URL("../RideGroup.tsx", import.meta.url), "utf8");
  const panel = group.slice(group.indexOf('className="ride-alert-panel"'), group.indexOf("{alerts.length > 0 && ("));
  // Speak first, then the box (only once opened), then the quick alerts, all in the one branch past the confirm.
  const speakAt = panel.indexOf('className="ride-speak"');
  const boxAt = panel.indexOf("{otherOpen && (");
  const kindsAt = panel.indexOf('<ul role="list" className="ride-alert-kinds">');
  assert.ok(speakAt > 0 && speakAt < boxAt && boxAt < kindsAt, "Speak, then the box, then the quick alerts");
  assert.match(panel, /\{canSpeak && \(\s*<button type="button" ref=\{speakButton\} className="ride-speak" aria-pressed=\{listening\} onClick=\{speak\}[^>]*>[\s\S]*?\{SPEAK_LABEL\}/);
  // Pressing Speak opens the box; while listening the box is not focused, so no keyboard covers the words.
  assert.match(group, /const speak = \(\) => \{\s*if \(listening\) \{\s*stopListening\.current\?\.\(\);\s*return;\s*\}\s*setOtherOpen\(true\);/);
  assert.match(panel, /autoFocus=\{!listening\}/);
  // With the box open, Other is not listed again; a quick alert picked instead closes the box, which drops the speech.
  assert.match(panel, /\.filter\(\(kind\) => !\(otherOpen && kind\.id === "other"\)\)/);
  assert.match(group, /const pick = \(kind: AlertKind\) => \{[^}]*setOtherOpen\(kind\.id === "other"\);/);
  // Said words go after typed ones; closing the box or the panel aborts (no late words in a closed box).
  assert.match(group, /\(text\) => setOtherText\(typed \? `\$\{typed\} \$\{text\}`\.slice\(0, OTHER_MAX\) : text\)/);
  assert.match(group, /if \(otherOpen && alertOpen\) return;\s*abortListening\.current\?\.\(\);\s*setSendWhenHeard\(false\);/);
  // Send while listening finishes the words first (stop keeps them), then sends them, not a half-heard guess.
  assert.match(panel, /if \(listening\) \{\s*setSendWhenHeard\(true\);\s*stopListening\.current\?\.\(\);\s*\} else if \(otherText\.trim\(\)\) void send\(OTHER_KIND\);/);
  assert.match(group, /if \(!sendWhenHeard \|\| listening\) return;\s*setSendWhenHeard\(false\);\s*if \(otherText\.trim\(\)\) void send\(OTHER_KIND\);[\s\S]*?\}, \[sendWhenHeard, listening\]\);/);
  // Cancel goes with the box, so focus returns to Speak.
  assert.match(panel, /setOtherOpen\(false\);\s*\/\/[^\n]*\n\s*speakButton\.current\?\.focus\(\);/);
  assert.match(group, /say\(LISTENING_SAID\)/);
  assert.equal(LISTENING_SAID, "Listening. Say the issue, then tap Send.");
  // Nothing is sent until Send: the words only fill the box.
  assert.doesNotMatch(group.slice(group.indexOf("const speak = () => {"), group.indexOf("const abortListening")), /send\(/);
  const bar = group.slice(group.indexOf('className="ride-group-bar"'), group.indexOf("id={ridersPanel}"));
  assert.doesNotMatch(bar, /ride-speak/);
});
