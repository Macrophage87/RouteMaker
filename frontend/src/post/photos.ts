/**
 * A Featured routes post's photos, for an instance admin on the post's page (core/route_posts.py photo_upload): each
 * photo is drawn again in the browser, at most PHOTO_EDGE pixels on its longer side, and sent as a JPEG. Drawing it
 * again keeps only the picture: no Exif, GPS position, date or camera details go with it (the server takes out any
 * left, clean_jpeg). The browser turns a phone's sideways photo the right way up as it draws it.
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
