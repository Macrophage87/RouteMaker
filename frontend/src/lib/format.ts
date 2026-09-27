/** Numbers as the panel shows them. Metric first, imperial beside it. */

const DASH = "–";

function usable(value: number): boolean {
  return Number.isFinite(value) && value >= 0;
}

export function formatDistance(metres: number): string {
  if (!usable(metres)) return DASH;
  const km = metres / 1000;
  const mi = metres / 1609.344;
  return `${km.toFixed(1)} km (${mi.toFixed(1)} mi)`;
}

export function formatDuration(seconds: number): string {
  if (!usable(seconds)) return DASH;
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `${hours} h ${String(minutes % 60).padStart(2, "0")} min`;
}

export function formatClimb(metres: number): string {
  if (!usable(metres)) return DASH;
  return `${Math.round(metres)} m (${Math.round(metres * 3.28084)} ft)`;
}

/** A whole number of seconds, for "trying again in ...": "1 second", "5 seconds". */
export function formatSeconds(seconds: number): string {
  return seconds === 1 ? "1 second" : `${seconds} seconds`;
}
