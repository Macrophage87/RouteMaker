/**
 * A Featured routes post's photos, for an instance admin on the post's page (core/route_posts.py photo_upload): each
 * photo is drawn again in the browser, at most PHOTO_EDGE pixels on its longer side, and sent as a JPEG. Drawing it
 * again keeps only the picture: no Exif, date or camera details go with it (the server takes out any left,
 * clean_jpeg). Where it was taken is read from the file first and sent alongside (the owner, 2026-11-07: "people
 * want to know where they are taken"); the server keeps it unless it is at the author's Home. The browser turns a
 * phone's sideways photo the right way up as it draws it.
 */

export const PHOTO_EDGE = 1600;
/** Under the 1 MB the edges let a request carry, with room for the form around it. */
export const PHOTO_MAX_BYTES = 900 * 1024;
export const PHOTO_SENDING = "Making the photo smaller and sending it…";
export const PHOTO_DONE = "Photo added. Showing it in place…";
export const PHOTO_UNREADABLE = "This browser can't open that file. Try a JPEG or PNG.";
export const PHOTO_FAILED = "The photo could not be sent. Try again.";
export const PHOTO_TOO_BIG = "That photo is still too big after making it smaller. Try a smaller or simpler photo.";

/** The size to draw a photo at: at most `edge` on its longer side, never larger than it is. */
export function fitWithin(width: number, height: number, edge: number = PHOTO_EDGE): { width: number; height: number } {
  const scale = Math.min(1, edge / Math.max(width, height));
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}

/** How much of a file is read for its Exif: it sits in the first segments, well inside this. */
export const EXIF_READ_BYTES = 256 * 1024;

/** Where a JPEG says it was taken, [lat, lon], from its Exif GPS; null when it does not say (core/route_posts.py exif_spot). */
export function exifSpot(buffer: ArrayBuffer): [number, number] | null {
  const data = new DataView(buffer);
  const size = data.byteLength;
  if (size < 4 || data.getUint16(0) !== 0xffd8) return null;
  let i = 2;
  while (i + 4 <= size && data.getUint8(i) === 0xff) {
    const marker = data.getUint8(i + 1);
    if (marker === 0xda || marker === 0xd9) return null;
    const end = i + 2 + data.getUint16(i + 2);
    if (marker === 0xe1 && i + 10 <= size && data.getUint32(i + 4) === 0x45786966 && data.getUint16(i + 8) === 0) {
      return tiffSpot(new DataView(buffer, i + 10, Math.max(0, Math.min(end, size) - (i + 10))));
    }
    i = end;
  }
  return null;
}

function tiffSpot(tiff: DataView): [number, number] | null {
  const n = tiff.byteLength;
  if (n < 8) return null;
  const order = tiff.getUint16(0);
  if (order !== 0x4949 && order !== 0x4d4d) return null;
  const little = order === 0x4949;
  const u16 = (at: number) => (at >= 0 && at + 2 <= n ? tiff.getUint16(at, little) : null);
  const u32 = (at: number) => (at >= 0 && at + 4 <= n ? tiff.getUint32(at, little) : null);
  if (u16(2) !== 42) return null;
  const entries = (at: number | null): Map<number, { kind: number; count: number; at: number }> => {
    const out = new Map<number, { kind: number; count: number; at: number }>();
    const count = at === null ? null : u16(at);
    if (at === null || count === null) return out;
    for (let k = 0; k < Math.min(count, 256); k++) {
      const e = at + 2 + 12 * k;
      const tag = u16(e);
      const kind = u16(e + 2);
      const many = u32(e + 4);
      if (tag === null || kind === null || many === null) break;
      const bytes = ({ 1: 1, 2: 1, 3: 2, 4: 4, 5: 8 } as Record<number, number>)[kind] ?? 0;
      const where = bytes * many <= 4 ? e + 8 : u32(e + 8);
      if (where !== null) out.set(tag, { kind, count: many, at: where });
    }
    return out;
  };
  const pointer = entries(u32(4)).get(0x8825);
  if (!pointer) return null;
  const gps = entries(u32(pointer.at));
  const degrees = (tag: number): number | null => {
    const entry = gps.get(tag);
    if (!entry || entry.kind !== 5 || entry.count !== 3) return null;
    let total = 0;
    for (const [k, scale] of [[0, 1], [1, 60], [2, 3600]] as const) {
      const top = u32(entry.at + 8 * k);
      const bottom = u32(entry.at + 8 * k + 4);
      if (top === null || !bottom) return null;
      total += top / bottom / scale;
    }
    return total;
  };
  const ref = (tag: number): string => {
    const entry = gps.get(tag);
    return entry && entry.at < n ? String.fromCharCode(tiff.getUint8(entry.at)) : "";
  };
  const lat = degrees(2);
  const lon = degrees(4);
  if (lat === null || lon === null) return null;
  return [ref(1) === "S" ? -lat : lat, ref(3) === "W" ? -lon : lon];
}

/** The photo drawn again as a JPEG, smaller and at lower quality until it fits PHOTO_MAX_BYTES. */
async function redraw(file: Blob): Promise<Blob> {
  const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  try {
    for (const [edge, quality] of [
      [PHOTO_EDGE, 0.85],
      [PHOTO_EDGE, 0.72],
      [1200, 0.72],
      [900, 0.68],
    ] as const) {
      const size = fitWithin(bitmap.width, bitmap.height, edge);
      const canvas = document.createElement("canvas");
      canvas.width = size.width;
      canvas.height = size.height;
      const g = canvas.getContext("2d");
      if (!g) throw new Error("no canvas");
      // A transparent PNG's see-through parts as white, not a JPEG's black.
      g.fillStyle = "#ffffff";
      g.fillRect(0, 0, size.width, size.height);
      g.drawImage(bitmap, 0, 0, size.width, size.height);
      const blob = await new Promise<Blob>((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("no picture"))), "image/jpeg", quality));
      if (blob.size <= PHOTO_MAX_BYTES) return blob;
    }
    throw new Error("too big");
  } finally {
    bitmap.close();
  }
}

/** Wires each photo form in the admin box: draw the chosen file again, send it, and reload to show it in place. */
export function wirePhotos(doc: Document, slug: string, csrf: string | undefined, reload: () => void = () => window.location.reload()): void {
  const said = doc.getElementById("photo-said");
  const say = (words: string) => {
    if (said) said.textContent = words;
  };
  for (const form of Array.from(doc.querySelectorAll<HTMLFormElement>("form.photo-form"))) {
    const button = form.querySelector<HTMLButtonElement>("button[type=submit]");
    if (button) button.disabled = false;
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const input = form.querySelector<HTMLInputElement>("input[type=file]");
      const file = input?.files?.[0];
      if (!file) return;
      // aria-disabled, not disabled: the button keeps a keyboard user's focus (as sends.ts).
      if (button?.getAttribute("aria-disabled") === "true") return;
      button?.setAttribute("aria-disabled", "true");
      say(PHOTO_SENDING);
      let picture: Blob;
      try {
        picture = await redraw(file);
      } catch (error) {
        say(error instanceof Error && error.message === "too big" ? PHOTO_TOO_BIG : PHOTO_UNREADABLE);
        button?.removeAttribute("aria-disabled");
        return;
      }
      const body = new FormData(form);
      body.set("photo", picture, "photo.jpg");
      try {
        const spot = exifSpot(await file.slice(0, EXIF_READ_BYTES).arrayBuffer());
        if (spot) {
          body.set("lat", String(spot[0]));
          body.set("lon", String(spot[1]));
        }
      } catch {
        // Not a JPEG this can read: the photo goes without where it was taken.
      }
      if (form.dataset.photo) body.set("photo_id", form.dataset.photo);
      try {
        const response = await fetch(`/routes/${encodeURIComponent(slug)}/photos`, {
          method: "POST",
          credentials: "same-origin",
          headers: csrf ? { "X-CSRFToken": csrf } : {},
          body,
        });
        if (response.ok) {
          say(PHOTO_DONE);
          reload();
          return;
        }
        say(response.status === 400 ? (await response.text()) || PHOTO_FAILED : PHOTO_FAILED);
      } catch {
        say(PHOTO_FAILED);
      }
      button?.removeAttribute("aria-disabled");
    });
  }
}
