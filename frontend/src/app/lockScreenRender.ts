// The cue sheet lock-screen images drawn on a canvas from their layout (lib/lockScreen.ts): white, dark text (or, dark, the other way round), thin
// rules between rows, in the panel's face (Atkinson Hyperlegible, as the share image). Browser only.
import { ARROW_STROKE, EDGE_STROKE, arrowShape } from "../lib/cueArrow.ts";
import { LOCK_HEIGHT, LOCK_WIDTH, lockColours, lockScreenLayout, type LockPage, type Weight } from "../lib/lockScreen.ts";

const FONT = '"Atkinson Hyperlegible", system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans", sans-serif';

/** The route's lock-screen images as PNG blobs, in order, with their pages (for the status line). */
export async function renderLockScreens(
  route: Parameters<typeof lockScreenLayout>[0],
  vias: readonly number[] = [],
  names: ReadonlyMap<number, string> = new Map(),
  dark = false,
): Promise<{ pages: LockPage[]; blobs: Blob[] }> {
  const { ink: INK, paper: PAPER } = lockColours(dark);
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
  const pages = lockScreenLayout(route, measure, vias, names);
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
    for (const placed of page.arrows) drawArrow(ctx, placed, INK, PAPER);
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

/** A cue's picture (lib/cueArrow.ts), its 100-unit box scaled to its place. */
function drawArrow(ctx: CanvasRenderingContext2D, placed: LockPage["arrows"][number], INK: string, PAPER: string): void {
  const shape = arrowShape(placed.arrow);
  const k = placed.size / 100;
  const at = (p: readonly [number, number]): [number, number] => [placed.x + p[0] * k, placed.y + p[1] * k];
  ctx.save();
  ctx.fillStyle = INK;
  ctx.strokeStyle = INK;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  const line = (points: readonly (readonly [number, number])[], width: number) => {
    ctx.lineWidth = width * k;
    ctx.beginPath();
    points.forEach((p, i) => (i ? ctx.lineTo(...at(p)) : ctx.moveTo(...at(p))));
    ctx.stroke();
  };
  for (const edge of shape.thin) line(edge, EDGE_STROKE);
  for (const stroke of shape.strokes) line(stroke, ARROW_STROKE);
  for (const fill of shape.fills) {
    ctx.beginPath();
    fill.forEach((p, i) => (i ? ctx.lineTo(...at(p)) : ctx.moveTo(...at(p))));
    ctx.closePath();
    ctx.fill();
  }
  for (const d of shape.discs) {
    ctx.beginPath();
    const [x, y] = at([d.x, d.y]);
    if (d.ring) {
      ctx.lineWidth = d.ring * k;
      ctx.arc(x, y, (d.r - d.ring / 2) * k, 0, 2 * Math.PI);
      ctx.stroke();
    } else {
      ctx.arc(x, y, d.r * k, 0, 2 * Math.PI);
      ctx.fill();
    }
  }
  if (shape.label) {
    const [x, y] = at([shape.label.x, shape.label.y]);
    ctx.fillStyle = PAPER;
    ctx.font = `700 ${shape.label.px * k}px ${FONT}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(shape.label.text, x, y);
  }
  ctx.restore();
}
