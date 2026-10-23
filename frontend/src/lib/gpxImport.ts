/**
 * Opening a GPX file: read in this browser, in a Web Worker where there is
 * one, and never uploaded. Signed out there is nowhere to upload it to, and a
 * track is a record of where someone rides.
 */
import { GpxError, MAX_GPX_BYTES, parseGpx } from "./gpx.ts";
import { ImportError, planFromGpx, verbatimTrack, type ImportedPlan } from "./gpxPlan.ts";

export type ImportOutcome = { ok: true; plan: ImportedPlan } | { ok: false; message: string };

/**
 * The file picker's filter. Android's picker (the phone app's and Chrome's) filters by MIME type alone,
 * and a downloaded GPX file there is usually labelled application/octet-stream, so with the filter every
 * GPX file in Downloads is greyed out (the owner, 2026-10-23: "I can't open any GPX files on my phone").
 * On Android any file can be picked; readGpx says in a sentence when it is not GPX.
 */
export const GPX_ACCEPT = ".gpx,application/gpx+xml";

export function gpxAccept(userAgent: string = globalThis.navigator?.userAgent ?? ""): string | undefined {
  return /Android/i.test(userAgent) ? undefined : GPX_ACCEPT;
}

/** Anything unexpected is still a sentence, not a stack trace. */
function failure(error: unknown): ImportOutcome {
  if (error instanceof GpxError || error instanceof ImportError) return { ok: false, message: error.message };
  return { ok: false, message: "The file could not be read as GPX." };
}

/** The whole import, from the file's bytes to a plan; what the worker runs. */
export async function readGpx(file: Blob): Promise<ImportOutcome> {
  if (file.size > MAX_GPX_BYTES) return { ok: false, message: "The file is larger than 20 MB." };
  try {
    const text = await file.text();
    const parsed = parseGpx(text);
    // The file itself is kept beside the plan, for a verbatim export and a saved route.
    return { ok: true, plan: { ...planFromGpx(parsed), verbatim: { text, track: verbatimTrack(parsed) } } };
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
