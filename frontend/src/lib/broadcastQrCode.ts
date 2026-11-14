// The broadcast's QR code (lib/broadcastQr.ts has its words): loaded with BroadcastQrDialog on first use, so the QR
// encoder and the share card's qrModules stay out of the first load (the v0.27.0 size budget).
import qrcode from "qrcode-generator";
import { qrModules } from "./shareCard.ts";

/** The quiet zone round the code, in modules (the standard asks for 4). */
export const QR_MARGIN = 4;

/** The code as one SVG path on a square `size` modules wide, quiet zone included: crisp at any size. */
export function qrPath(link: string): { size: number; d: string } {
  // Level M: still read off a phone's screen in sunlight, and short enough for a link with its plan.
  const qr = qrcode(0, "M");
  qr.addData(link);
  qr.make();
  const modules = qrModules(qr);
  const parts: string[] = [];
  modules.forEach((row, r) => row.forEach((dark, c) => dark && parts.push(`M${c + QR_MARGIN} ${r + QR_MARGIN}h1v1h-1z`)));
  return { size: modules.length + QR_MARGIN * 2, d: parts.join("") };
}
