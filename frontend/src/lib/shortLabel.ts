/** A choice's name before its colon ("Full: every turn, …" is "Full"), for a picker whose explanation is behind an (i). */
export function shortLabel(label: string): string {
  const colon = label.indexOf(":");
  return colon > 0 ? label.slice(0, colon) : label;
}
