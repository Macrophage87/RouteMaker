/**
 * Reads an opened GPX file off the page's thread, so a 20 MB track does not
 * hold the map. The file comes from the rider's own disk and goes nowhere:
 * this worker makes no request.
 */
import { readGpx } from "./gpxImport.ts";

self.onmessage = async (event: MessageEvent<Blob>) => {
  self.postMessage(await readGpx(event.data));
};
