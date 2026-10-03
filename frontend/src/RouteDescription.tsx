/**
 * The route summary's "Route description" (OWNER-DECISIONS 220): the route in
 * words, stretch by stretch, for riders who hear it rather than see the map -
 * many blind cyclists ride as tandem stokers. A component of its own so App.tsx
 * only places it.
 *
 * - A heading, so a screen reader can jump to it.
 * - A disclosure button (aria-expanded) over an ordered list: closed unless the
 *   rider has opened it before. Nothing is announced when the route changes;
 *   the list just updates.
 * - One sentence to an item, with the severity and the tier in words, never in
 *   colour alone.
 * - "Copy description" and "Download as text" (a cue sheet, no network).
 */
import { useEffect, useId, useState } from "react";
import type { RouteResponse } from "./lib/api.ts";
import "./routeDescription.css";
import {
  DESCRIPTION_HEADING,
  chevron,
  cueSheetFileName,
  descriptionEntries,
  descriptionText,
  readOpen,
  toggleLabel,
  writeOpen,
} from "./lib/routeDescription.ts";

async function copy(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Fall through to the selection method.
  }
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.append(area);
    area.select();
    const done = document.execCommand("copy");
    area.remove();
    return done;
  } catch {
    return false;
  }
}

export function RouteDescription({ route }: { route: RouteResponse }) {
  const entries = descriptionEntries(route);
  const [open, setOpen] = useState<boolean>(() => readOpen());
  // Said only after the rider presses Copy: a reply to their action, not a
  // announcement about the route.
  const [copied, setCopied] = useState<"" | "done" | "failed">("");
  const listId = useId();
  // A confirmation of one press is not left standing over the next route.
  useEffect(() => setCopied(""), [route.description]);
  if (entries === null) return null;

  const toggle = () => {
    setOpen(!open);
    writeOpen(!open);
  };
  const onCopy = async () => {
    setCopied((await copy(descriptionText(route))) ? "done" : "failed");
  };
  const onDownload = () => {
    const blob = new Blob([descriptionText(route)], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = cueSheetFileName(route);
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  };

  return (
    <section className="route-description" aria-labelledby="route-description-heading">
      <h3 id="route-description-heading">{DESCRIPTION_HEADING}</h3>
      <button type="button" className="description-toggle" aria-expanded={open} aria-controls={listId} onClick={toggle}>
        <span aria-hidden="true">{chevron(open)} </span>
        {toggleLabel(entries)}
      </button>
      <ol id={listId} className="description-list" hidden={!open}>
        {entries.map((entry, i) => (
          <li key={i} className={`description-${entry.kind}`}>
            {entry.text}
          </li>
        ))}
      </ol>
      <div className="actions description-actions">
        <button type="button" onClick={onCopy}>
          Copy description
        </button>
        <button type="button" onClick={onDownload}>
          Download as text
        </button>
        <span role="status" className="hint description-status">
          {copied === "done" ? "Copied." : copied === "failed" ? "Could not copy. Use Download as text." : ""}
        </span>
      </div>
    </section>
  );
}
