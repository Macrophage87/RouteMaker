import { test } from "node:test";
import assert from "node:assert/strict";
import { GPX_NS_11, MAX_GPX_BYTES } from "./gpx.ts";
import { importGpx, readGpx, type ImportOutcome } from "./gpxImport.ts";

const GOOD = new Blob([
  `<gpx xmlns="${GPX_NS_11}" version="1.1" creator="t"><trk><trkseg>` +
    `<trkpt lat="38.90" lon="-77.03"/><trkpt lat="38.91" lon="-77.02"/><trkpt lat="38.92" lon="-77.03"/>` +
    `</trkseg></trk></gpx>`,
]);

test("a GPX file is read into a plan; anything else is a sentence, not an exception", async () => {
  const good = await readGpx(GOOD);
  assert.ok(good.ok && good.plan.points.length >= 2);
  for (const text of ["<kml/>", "not xml at all", `<gpx xmlns="${GPX_NS_11}" version="1.1"></gpx>`]) {
    const bad = await readGpx(new Blob([text]));
    assert.equal(bad.ok, false, text);
    assert.ok(!bad.ok && bad.message.length > 0 && !/Error:|\bat /.test(bad.message), text);
  }
});

test("a file over 20 MB is refused before it is read", async () => {
  let read = false;
  const huge = {
    size: MAX_GPX_BYTES + 1,
    text: async () => {
      read = true;
      return "";
    },
  } as unknown as Blob;
  const outcome = await readGpx(huge);
  assert.equal(outcome.ok, false);
  assert.equal(read, false);
  let made = 0;
  const viaWorker = await importGpx(huge, () => {
    made += 1;
    throw new Error("no worker should be made");
  });
  assert.equal(viaWorker.ok, false);
  assert.equal(read, false);
  assert.equal(made, 0);
});

function fakeWorker(answer: (file: Blob) => Promise<ImportOutcome> | "error") {
  const made = { posted: 0, terminated: 0 };
  const make = () => {
    const w = {
      onmessage: null as ((e: MessageEvent<ImportOutcome>) => void) | null,
      onerror: null as ((e: unknown) => void) | null,
      postMessage: (file: Blob) => {
        made.posted += 1;
        const result = answer(file);
        if (result === "error") setTimeout(() => w.onerror?.({}), 0);
        else void result.then((data) => w.onmessage?.({ data } as MessageEvent<ImportOutcome>));
      },
      terminate: () => {
        made.terminated += 1;
      },
    };
    return w;
  };
  return { make, made };
}

test("the worker's answer is the answer, and the worker is ended", async () => {
  const { make, made } = fakeWorker(async () => ({ ok: false, message: "from the worker" }));
  const outcome = await importGpx(GOOD, make);
  assert.deepEqual(outcome, { ok: false, message: "from the worker" });
  assert.deepEqual(made, { posted: 1, terminated: 1 });
});

test("a worker that fails, or cannot be made, falls back to reading on the page", async () => {
  const failing = fakeWorker(() => "error");
  const outcome = await importGpx(GOOD, failing.make);
  assert.ok(outcome.ok);
  assert.equal(failing.made.terminated, 1);
  const unmade = await importGpx(GOOD, () => {
    throw new Error("blocked");
  });
  assert.ok(unmade.ok);
  assert.ok((await importGpx(GOOD, null)).ok);
});
