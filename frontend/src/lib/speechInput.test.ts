// Speak an alert's words (lib/speechInput.ts; Stephen 2026-10-22, "yes. option 2").
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { LISTENING_SAID, SPEECH_FAILED, SPEECH_OTHER_FAILED, listenOnce, speechSupported, type SpeechEnv } from "./speechInput.ts";

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
  assert.equal(speechSupported({}), false);
  assert.equal(speechSupported(env), true);
  assert.equal(listenOnce(() => {}, () => {}, 80, {}), null);
});

test("Speak is hidden in the phone app, which cannot have the microphone (no RECORD_AUDIO)", () => {
  assert.equal(speechSupported(env, true), false);
  assert.equal(speechSupported(env, false), true);
  const manifest = readFileSync(new URL("../../../mobile/android/app/src/main/AndroidManifest.xml", import.meta.url), "utf8");
  // Once the app asks for the microphone, Speak can be tried there and this test changed.
  assert.doesNotMatch(manifest, /RECORD_AUDIO/);
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

test("the Speak button sits in Alert > Other only, keeps its name, and nothing is sent until Send", () => {
  const group = readFileSync(new URL("../RideGroup.tsx", import.meta.url), "utf8");
  const other = group.slice(group.indexOf(") : otherOpen ? ("), group.indexOf('<ul role="list" className="ride-alert-kinds">'));
  assert.match(other, /\{canSpeak && \(\s*<button type="button" className="secondary ride-speak" aria-pressed=\{listening\} onClick=\{speak\}[^>]*>[\s\S]*?\{SPEAK_LABEL\}/);
  // Said words go after typed ones; closing the box aborts (no late words in a closed box).
  assert.match(group, /\(text\) => setOtherText\(typed \? `\$\{typed\} \$\{text\}`\.slice\(0, OTHER_MAX\) : text\)/);
  assert.match(group, /if \(!otherOpen\) abortListening\.current\?\.\(\);/);
  assert.match(group, /say\(LISTENING_SAID\)/);
  assert.equal(LISTENING_SAID, "Listening. Say the issue, then tap Send.");
  const bar = group.slice(group.indexOf('className="ride-group-bar"'), group.indexOf("id={ridersPanel}"));
  assert.doesNotMatch(bar, /ride-speak/);
});
