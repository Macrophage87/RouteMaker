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
 * the place tied to its checkbox by aria-describedby, and the copy's result in a polite status region that
 * is always in the page.
 */
import { useEffect, useId, useState } from "react";
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

function Entry({ entry, onCopy }: { entry: LogEntry; onCopy: (entry: LogEntry) => void }) {
  const id = useId();
  const done = entry.reported !== null;
  return (
    <li className="log311-entry">
      <label className="log311-check">
        <input type="checkbox" checked={done} aria-describedby={`${id}-place`} onChange={(event) => report311Log().setReported(entry.id, event.target.checked)} />
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

export function Report311Log() {
  const entries = useReport311Log();
  const [copied, setCopied] = useState("");
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
  return (
    <section aria-labelledby="suggest-311-heading" className="settings-group log311">
      <h3 id="suggest-311-heading">{LOG_HEADING}</h3>
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
              <Entry key={entry.id} entry={entry} onCopy={(e) => void copy(e)} />
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
                <Entry key={entry.id} entry={entry} onCopy={(e) => void copy(e)} />
              ))}
            </ul>
          </div>
        </details>
      )}
    </section>
  );
}
