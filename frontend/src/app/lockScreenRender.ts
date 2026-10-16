// The cue sheet lock-screen images drawn on a canvas from their layout (lib/lockScreen.ts): white, dark text, thin
// rules between rows, in the panel's face (Atkinson Hyperlegible, as the share image). Browser only.
import { INK, LOCK_HEIGHT, LOCK_WIDTH, PAPER, lockScreenLayout, type LockPage, type Weight } from "../lib/lockScreen.ts";

const FONT = '"Atkinson Hyperlegible", system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans", sans-serif';

/** The route's lock-screen images as PNG blobs, in order, with their pages (for the status line). */
export async function renderLockScreens(route: Parameters<typeof lockScreenLayout>[0], vias: readonly number[] = []): Promise<{ pages: LockPage[]; blobs: Blob[] }> {
  await Promise.all([document.fonts?.load(`700 64px "Atkinson Hyperlegible"`), document.fonts?.load(`400 32px "Atkinson Hyperlegible"`)]).catch(() => undefined);
  const canvas = document.createElement("canvas");
  canvas.width = LOCK_WIDTH;
  canvas.height = LOCK_HEIGHT;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("no canvas");
  const measure = (text: string, px: number, weight: Weight) => {
    ctx.font = `${weight} ${px}px ${FONT}`;
    return ctx.measureText(text).width;
  };
  const pages = lockScreenLayout(route, measure, vias);
  const blobs: Blob[] = [];
  for (const page of pages) {
    ctx.fillStyle = PAPER;
    ctx.fillRect(0, 0, LOCK_WIDTH, LOCK_HEIGHT);
    ctx.fillStyle = INK;
    ctx.strokeStyle = INK;
    ctx.lineWidth = 2;
    for (const y of page.rules) {
      ctx.beginPath();
      ctx.moveTo(64, y);
      ctx.lineTo(LOCK_WIDTH - 64, y);
      ctx.stroke();
    }
    for (const line of page.lines) {
      ctx.font = `${line.weight} ${line.px}px ${FONT}`;
      ctx.fillText(line.text, line.x, line.y);
    }
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
    if (!blob) throw new Error("no image");
    blobs.push(blob);
  }
  return { pages, blobs };
}
