// Send alert's Speak as a machine (lib/alertDictation.ts; the v0.15.1 end review): behaviour, with a fake recogniser.
import { test } from "node:test";
import assert from "node:assert/strict";
import { alertDictation } from "./alertDictation.ts";
import type { SpeechEnv } from "./speechInput.ts";

/** Chrome's shape: stop() ends after the last result; abort() ends too (an "aborted" error, then onend). */
class FakeRecognition {
  static last: FakeRecognition | null = null;
  lang = "";
  interimResults = false;
  continuous = true;
  maxAlternatives = 5;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null = null;
  onerror: ((event: { error?: string }) => void) | null = null;
  onend: (() => void) | null = null;
  pendingFinal: string | null = null;
  constructor() {
    FakeRecognition.last = this;
  }
  start() {}
  heard(words: string) {
    this.onresult?.({ results: [[{ transcript: words }]] });
  }
  stop() {
    if (this.pendingFinal !== null) this.heard(this.pendingFinal);
    this.onend?.();
  }
  abort() {
    if (this.pendingFinal !== null) this.heard(this.pendingFinal);
    this.onerror?.({ error: "aborted" });
    this.onend?.();
  }
}
const env = { webkitSpeechRecognition: FakeRecognition } as unknown as SpeechEnv;

function harness() {
  const log = { text: [] as string[], listening: [] as boolean[], sent: [] as string[], failed: [] as string[] };
  const d = alertDictation(
    { text: (w) => log.text.push(w), listening: (on) => log.listening.push(on), send: (w) => log.sent.push(w), failed: (f) => log.failed.push(f) },
    80,
    env,
  );
  return { d, log };
}

test("Send while listening sends the finished words, exactly once", () => {
  const { d, log } = harness();
  assert.equal(d.start(""), true);
  const rec = FakeRecognition.last!;
  rec.heard("tree down");
  rec.pendingFinal = "tree down past the bridge";
  d.finishAndSend();
  assert.deepEqual(log.sent, ["tree down past the bridge"]);
  // A second press, or a late end, sends nothing more.
  d.finishAndSend();
  rec.onend?.();
  assert.deepEqual(log.sent, ["tree down past the bridge"]);
  assert.deepEqual(log.listening, [true, false]);
});

test("closing the panel (abort) un-presses Speak at once and nothing heard after it lands or is sent", () => {
  const { d, log } = harness();
  d.start("");
  const rec = FakeRecognition.last!;
  rec.heard("wait");
  rec.pendingFinal = "wait up at the light";
  d.abort();
  assert.deepEqual(log.listening, [true, false]);
  assert.deepEqual(log.text, ["wait"]);
  assert.deepEqual(log.sent, []);
  assert.deepEqual(log.failed, []);
});

test("Send then a quick alert before the words finish: the quick alert's abort wins, the words are not sent", () => {
  const { d, log } = harness();
  d.start("");
  const rec = FakeRecognition.last!;
  const realStop = rec.stop.bind(rec);
  rec.stop = () => {}; // the browser has not finished yet
  d.finishAndSend();
  d.abort();
  realStop();
  assert.deepEqual(log.sent, []);
  assert.deepEqual(log.listening, [true, false]);
});

test("a plain stop keeps the words in the box and sends nothing; spoken words go after typed ones", () => {
  const { d, log } = harness();
  d.start("Flat tire");
  FakeRecognition.last!.heard("at the bridge");
  d.stop();
  assert.equal(log.text.at(-1), "Flat tire at the bridge");
  assert.deepEqual(log.sent, []);
});

test("a failure is said, and Send pressed during it sends what was heard", () => {
  const { d, log } = harness();
  d.start("");
  const rec = FakeRecognition.last!;
  rec.heard("lost");
  rec.stop = () => {
    rec.onerror?.({ error: "network" });
    rec.onend?.();
  };
  d.finishAndSend();
  assert.equal(log.failed.length, 1);
  assert.deepEqual(log.sent, ["lost"]);
});
