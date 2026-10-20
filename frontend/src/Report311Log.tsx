/**
 * The 311 checklist (lib/report311Log.ts; Stephen, 2026-10-20: "put a checklist of what needs to be logged
 * to 311 and which website, by location. Checking archives it."), in Suggest, in Go's Menu and Plan alike.
 *
 * Each website is a heading with its one "Open" link; under it, its open entries as checkboxes, each with
 * where it is and "Copy report" (the words to paste into the site). Checking one archives it; Archived is a
 * fold below, where unchecking puts one back. Entries logged with no signal wait under "Website not looked
 * up yet", and are looked up as the checklist opens.
 *
 * Built like the rest of the sheets: real headings, native checkboxes whose label is the entry's own words,
 * the place tied to its checkbox by aria-describedby, and the copy's or the check's result in a polite status
 * region that is always in the page. A checked entry moves, so the focus goes to the next one in the list it
 * left (focusAfter).
 */
import { useEffect, useId, useRef, useState } from "react";
import { copyText, selectionCopy } from "./lib/sidebar.ts";
import { gpsWords } from "./lib/report311.ts";
import {
  archived,
  entryPoint,
  entryText,
  kindLabel,
  openGroups,
  report311Log,
  useReport311Log,
  whenWords,
  type LogEntry,
} from "./lib/report311Log.ts";

export const LOG_HEADING = "Your 311 checklist";
export const LOG_HINT =
  "Log a problem with a ride's 311 button, or right-click a road (press and hold on a phone) and choose Log for 311. Copy the report into the site, then check it off.";
export const LOG_EMPTY = "Nothing to report yet.";

/** What the checkbox says: "Pothole, Oct 20, 10:29 AM". */
export function entryLabel(entry: LogEntry): string {
  return `${kindLabel(entry.kind)}, ${whenWords(entry.at)}`;
}

/** The line under it: the place words, then the GPS position. */
export function entryPlace(entry: LogEntry): string {
  const words = entry.place ? `${entry.place[0].toUpperCase()}${entry.place.slice(1)}. ` : "";
  return `${words}${gpsWords(entryPoint(entry))}.${entry.note ? ` ${entry.note}` : ""}`;
}

function Entry({ entry, onCopy, onCheck }: { entry: LogEntry; onCopy: (entry: LogEntry) => void; onCheck: (entry: LogEntry, checked: boolean) => void }) {
  const id = useId();
  const done = entry.reported !== null;
  return (
    <li className="log311-entry">
      <label className="log311-check">
        <input type="checkbox" checked={done} data-entry={entry.id} aria-describedby={`${id}-place`} onChange={(event) => onCheck(entry, event.target.checked)} />
        <span>{entryLabel(entry)}</span>
      </label>
      <p id={`${id}-place`} className="hint log311-place">
        {entryPlace(entry)}
      </p>
      {!done && (
        <button type="button" className="secondary log311-copy" aria-describedby={`${id}-place`} onClick={() => onCopy(entry)}>
          Copy report
        </button>
      )}
    </li>
  );
}

/**
 * Where the focus goes once a checkbox is checked or unchecked, since its entry moves (to Archived, or back
 * under its website) and the checkbox the focus was on is gone: the next entry's in the list it left, else the
 * one before, else that list's heading (the checklist's, or Archived's summary).
 */
export function focusAfter(list: LogEntry[], id: string): string | null {
  const at = list.findIndex((e) => e.id === id);
  return (list[at + 1] ?? list[at - 1])?.id ?? null;
}

export function Report311Log() {
  const entries = useReport311Log();
  const [copied, setCopied] = useState("");
  const section = useRef<HTMLElement>(null);
  // The checkbox (or heading) to focus after the next render, and the words the status region says.
  const nextFocus = useRef<{ id: string | null; to: "heading" | "archived" } | null>(null);
  useEffect(() => {
    const next = nextFocus.current;
    if (!next || !section.current) return;
    nextFocus.current = null;
    const box = next.id ? section.current.querySelector<HTMLInputElement>(`input[data-entry="${CSS.escape(next.id)}"]`) : null;
    const fallback = next.to === "archived" ? section.current.querySelector<HTMLElement>(".log311-archived summary") : section.current.querySelector<HTMLElement>("h3");
    (box ?? fallback ?? section.current.querySelector<HTMLElement>("h3"))?.focus();
  });
  // Entries logged with no signal (or before their website was known) are looked up as the list opens.
  useEffect(() => {
    void report311Log().lookUp();
  }, []);
  const copy = async (entry: LogEntry) => {
    const done = await copyText(entryText(entry), navigator.clipboard, selectionCopy);
    setCopied("");
    window.setTimeout(() => setCopied(done ? `${kindLabel(entry.kind)} report copied.` : "Could not copy; select the report's text instead."), 150);
  };
  const groups = openGroups(entries);
  const old = archived(entries);
  const check = (entry: LogEntry, checked: boolean) => {
    // The list the entry leaves: open ones in the order shown, or Archived.
    const from = checked ? groups.flatMap((g) => g.entries) : old;
    nextFocus.current = { id: focusAfter(from, entry.id), to: checked ? "heading" : "archived" };
    report311Log().setReported(entry.id, checked);
    setCopied("");
    window.setTimeout(() => setCopied(checked ? `${kindLabel(entry.kind)} archived.` : `${kindLabel(entry.kind)} back on the checklist.`), 150);
  };
  return (
    <section ref={section} aria-labelledby="suggest-311-heading" className="settings-group log311">
      <h3 id="suggest-311-heading" tabIndex={-1}>
        {LOG_HEADING}
      </h3>
      <p className="hint">{LOG_HINT}</p>
      {groups.length === 0 && <p>{LOG_EMPTY}</p>}
      {groups.map((group) => (
        <div key={group.where ?? "pending"} className="log311-group">
          <h4>{group.heading}</h4>
          {group.site?.note && <p className="hint">{group.site.note}</p>}
          {group.site && (
            <a className="action-link secondary" href={group.site.url} target="_blank" rel="noopener noreferrer">
              {`Open ${group.site.site} (new tab)`}
            </a>
          )}
          <ul className="log311-entries" role="list">
            {group.entries.map((entry) => (
              <Entry key={entry.id} entry={entry} onCopy={(e) => void copy(e)} onCheck={check} />
            ))}
          </ul>
        </div>
      ))}
      <p className="hint" role="status">
        {copied}
      </p>
      {old.length > 0 && (
        <details className="fold log311-archived">
          <summary>{`Archived (${old.length})`}</summary>
          <div className="fold-body">
            <ul className="log311-entries" role="list">
              {old.map((entry) => (
                <Entry key={entry.id} entry={entry} onCopy={(e) => void copy(e)} onCheck={check} />
              ))}
            </ul>
          </div>
        </details>
      )}
    </section>
  );
}
