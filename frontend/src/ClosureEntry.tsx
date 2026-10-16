/**
 * A reviewer's closure form (v0.7.0 closures; lib/closureReview.ts): the road panel's "Mark closed", and Review's
 * "Confirm closure" for a rider's report. The road piece or its whole named stretch (the panel only, as the stress
 * editor offers it), a required reason, the first and last day (native date fields; the last may be left empty),
 * and an optional source link.
 *
 * Built like SuggestChange.tsx: its heading takes the focus when it opens; every control is labelled; the result is
 * a sentence in a polite status region that is always in the page; an error is an alert that names the field and
 * moves the focus to it; Cancel (and Escape, in the panel) closes it and the caller returns the focus to its button.
 */
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { STRETCH_HELP, STRETCH_WAIT, countText, extentOptions, fetchStretch, mayHaveStretch, stretchSaid, type Extent, type StretchLoad } from "./lib/stressEditor.ts";
import {
  CLOSURE_END_HELP,
  CLOSURE_EXTENT_LEGEND,
  CLOSURE_END_LABEL,
  CLOSURE_HEADING,
  CLOSURE_NOTE,
  CLOSURE_REASON_LABEL,
  CLOSURE_REASON_MAX,
  CLOSURE_SEND,
  CLOSURE_START_LABEL,
  CLOSURE_URL_LABEL,
  CONFIRM_HEADING,
  closureProblem,
  closureStretchPath,
  confirmReport,
  enterClosure,
  regionToday,
  type ClosureField,
} from "./lib/closureReview.ts";

interface Props {
  origin: string;
  /** The road piece (the panel's way), or the report's. */
  wayId: number;
  title: string;
  /** Confirming a rider's report: its id and its fixed reason words (never the rider's own text). */
  report?: { id: number; reason: string };
  onClose: () => void;
  /** Confirmed: the sentence said, for a caller that closes the form (Review). */
  onDone?: (message: string) => void;
}

export function ClosureEntry({ origin, wayId, title, report, onClose, onDone }: Props) {
  const base = useId();
  const id = (part: string) => `${base}-${part}`;
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [extent, setExtent] = useState<Extent>("piece");
  const [stretch, setStretch] = useState<StretchLoad>({ kind: "none" });
  const [reason, setReason] = useState(report?.reason ?? "");
  const [start, setStart] = useState(regionToday());
  const [end, setEnd] = useState("");
  const [url, setUrl] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [said, setSaid] = useState("");
  const [error, setError] = useState<{ field: ClosureField | "extent" | null; message: string } | null>(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  const fail = (field: ClosureField | "extent" | null, message: string) => {
    setError({ field, message });
    setTimeout(() => {
      if (field) document.getElementById(id(field === "extent" ? "extent-piece" : field))?.focus();
    }, 0);
  };

  const chooseStretch = async () => {
    setExtent("stretch");
    if (stretch.kind === "ready" || stretch.kind === "loading") return;
    setStretch({ kind: "loading" });
    setStretch(await fetchStretch(origin, wayId, undefined, fetch, closureStretchPath).catch((): StretchLoad => ({ kind: "error", message: "The stretch could not be found just now." })));
  };

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (sending || sent) return;
    const problem = closureProblem(reason, start, end, url);
    if (problem) {
      fail(problem.field, problem.message);
      return;
    }
    let ways = [wayId];
    if (!report && extent === "stretch") {
      if (stretch.kind !== "ready") {
        fail("extent", STRETCH_WAIT);
        return;
      }
      ways = stretch.stretch.osm_way_ids;
    }
    setError(null);
    setSending(true);
    const body = { reason: reason.trim(), start: start || null, end: end || null, url: url.trim() };
    const outcome = report ? await confirmReport(origin, report.id, body) : await enterClosure(origin, ways, body);
    setSending(false);
    if (outcome.kind === "refused") {
      const field = (["reason", "start", "end", "url"] as const).find((f) => f === outcome.field) ?? null;
      fail(field, outcome.message);
      return;
    }
    if (onDone) {
      onDone(outcome.message);
      return;
    }
    setSent(true);
    setSaid(outcome.message);
    headingRef.current?.focus();
  };

  const showExtent = !report && mayHaveStretch(title);
  return (
    <section className="stress-editor closure-entry" aria-labelledby={id("title")}>
      <h3 id={id("title")} ref={headingRef} tabIndex={-1}>
        {report ? CONFIRM_HEADING : CLOSURE_HEADING}
      </h3>
      <p className="stress-editor-said" role="status">
        {said}
      </p>
      {error && (
        <p className="stress-editor-error" role="alert" id={id("error")}>
          {error.message}
        </p>
      )}
      {!sent && (
        <form onSubmit={onSubmit} noValidate aria-describedby={error ? id("error") : undefined}>
          {!showExtent && (
            <p className="stress-editor-extent">
              <span className="road-info-label">This road piece:</span> {title}
            </p>
          )}
          {showExtent && (
            <fieldset className="stress-editor-field stress-editor-extent-choice" aria-describedby={id("extent-help")}>
              <legend>{CLOSURE_EXTENT_LEGEND}</legend>
              {extentOptions(title, stretch.kind === "ready" ? stretch.stretch : null).map((option) => (
                <div key={option.value} className="stress-editor-radio">
                  <input
                    id={id(`extent-${option.value}`)}
                    type="radio"
                    name={id("extent")}
                    value={option.value}
                    checked={extent === option.value}
                    onChange={() => (option.value === "stretch" ? void chooseStretch() : setExtent("piece"))}
                  />
                  <label htmlFor={id(`extent-${option.value}`)}>{option.text}</label>
                </div>
              ))}
              <p id={id("extent-help")} className="hint">
                {STRETCH_HELP}
              </p>
              <p className="hint stress-editor-stretch-said" role="status">
                {extent === "stretch" ? stretchSaid(stretch) : ""}
              </p>
            </fieldset>
          )}
          <div className="stress-editor-field">
            <label htmlFor={id("reason")}>{CLOSURE_REASON_LABEL}</label>
            <textarea
              id={id("reason")}
              rows={2}
              value={reason}
              required
              aria-required="true"
              aria-invalid={error?.field === "reason" ? true : undefined}
              aria-describedby={id("reason-count")}
              onChange={(event) => setReason(event.target.value)}
            />
            <p id={id("reason-count")} className="hint">
              {countText(reason.trim(), CLOSURE_REASON_MAX)}.
            </p>
          </div>
          <div className="stress-editor-field">
            <label htmlFor={id("start")}>{CLOSURE_START_LABEL}</label>
            <input id={id("start")} type="date" value={start} aria-invalid={error?.field === "start" ? true : undefined} onChange={(event) => setStart(event.target.value)} />
          </div>
          <div className="stress-editor-field">
            <label htmlFor={id("end")}>{CLOSURE_END_LABEL}</label>
            <input
              id={id("end")}
              type="date"
              value={end}
              min={start || undefined}
              aria-invalid={error?.field === "end" ? true : undefined}
              aria-describedby={id("end-help")}
              onChange={(event) => setEnd(event.target.value)}
            />
            <p id={id("end-help")} className="hint">
              {CLOSURE_END_HELP}
            </p>
          </div>
          <div className="stress-editor-field">
            <label htmlFor={id("url")}>{CLOSURE_URL_LABEL}</label>
            <input id={id("url")} type="url" inputMode="url" value={url} aria-invalid={error?.field === "url" ? true : undefined} onChange={(event) => setUrl(event.target.value)} />
          </div>
          <p className="hint">{CLOSURE_NOTE}</p>
          <div className="stress-editor-buttons">
            <button type="submit" aria-disabled={sending ? true : undefined}>
              {sending ? "Sending…" : CLOSURE_SEND}
            </button>
            <button type="button" className="secondary" onClick={onClose}>
              Cancel
            </button>
          </div>
        </form>
      )}
      {sent && (
        <div className="stress-editor-buttons">
          <button type="button" className="secondary" onClick={onClose}>
            Done
          </button>
        </div>
      )}
    </section>
  );
}
