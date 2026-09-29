/**
 * Opening a GPX file: read in this browser, in a Web Worker where there is
 * one, and never uploaded. Signed out there is nowhere to upload it to, and a
 * track is a record of where someone rides.
 */
import { GpxError, MAX_GPX_BYTES, parseGpx } from "./gpx.ts";
import { ImportError, planFromGpx, type ImportedPlan } from "./gpxPlan.ts";

export type ImportOutcome = { ok: true; plan: ImportedPlan } | { ok: false; message: string };

/** Anything unexpected is still a sentence, not a stack trace. */
function failure(error: unknown): ImportOutcome {
  if (error instanceof GpxError || error instanceof ImportError) return { ok: false, message: error.message };
  return { ok: false, message: "The file could not be read as GPX." };
}

/** The whole import, from the file's bytes to a plan; what the worker runs. */
export async function readGpx(file: Blob): Promise<ImportOutcome> {
  if (file.size > MAX_GPX_BYTES) return { ok: false, message: "The file is larger than 20 MB." };
  try {
    return { ok: true, plan: planFromGpx(parseGpx(await file.text())) };
  } catch (error) {
    return failure(error);
  }
}

type WorkerLike = {
  onmessage: ((event: MessageEvent<ImportOutcome>) => void) | null;
  onerror: ((event: unknown) => void) | null;
  postMessage: (message: Blob) => void;
  terminate: () => void;
};

/**
 * Read `file` in a worker made by `makeWorker`, or here on the page when no
 * worker can be made or the worker fails.
 */
export async function importGpx(file: Blob, makeWorker: (() => WorkerLike) | null): Promise<ImportOutcome> {
  if (file.size > MAX_GPX_BYTES) return { ok: false, message: "The file is larger than 20 MB." };
  let worker: WorkerLike | null = null;
  try {
    worker = makeWorker ? makeWorker() : null;
  } catch {
    worker = null;
  }
  if (!worker) return readGpx(file);
  const running = worker;
  const answer = await new Promise<ImportOutcome | null>((resolve) => {
    running.onmessage = (event) => resolve(event.data);
    running.onerror = () => resolve(null);
    running.postMessage(file);
  });
  running.terminate();
  return answer ?? readGpx(file);
}

/** The browser's worker for this module's import, as Vite bundles it. */
export function gpxWorker(): WorkerLike {
  return new Worker(new URL("./gpxWorker.ts", import.meta.url), { type: "module" }) as unknown as WorkerLike;
}
