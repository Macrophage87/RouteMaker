/**
 * The road panel's "Suggest a change" (OWNER-DECISIONS 441h, 460.4; lib/suggestions.ts): a rider the
 * settings allow suggests a level for the road piece, with a reason. Nothing changes on the map until an
 * instance admin reviews it.
 *
 * Built like the stress editor (StressEditor.tsx): its heading takes the focus when it opens; a native
 * range control read as its words; a required reason, a labelled textarea; the result is a sentence in
 * a polite status region that is always in the page; an error is an alert that names the field and
 * moves the focus to it; Cancel and Escape close it and the caller returns the focus to its button.
 */
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { csrfFromCookie, countText } from "./lib/stressEditor.ts";
import {
  SUGGEST_HEADING,
  SUGGEST_LEVEL_LABEL,
  SUGGEST_PRIVACY,
  SUGGEST_REASON_LABEL,
  SUGGEST_REASON_MAX,
  SUGGEST_SEND,
  sendSuggestion,
  suggestProblem,
  suggestValueText,
} from "./lib/suggestions.ts";

interface Props {
  origin: string;
  wayId: number;
  title: string;
  /** The road's level now (1 to 5 by halves). */
  current: number;
  /** The nearest point on the road ([lon, lat], the panel's `on_way`): never the spot clicked. */
  point: [number, number];
  /** Whether the road data can hold a half step yet: whole steps only until it can. */
  halfSteps: boolean;
  onClose: () => void;
}

export function SuggestChange({ origin, wayId, title, current, point, halfSteps, onClose }: Props) {
  const base = useId();
  const id = (part: string) => `${base}-${part}`;
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [step, setStep] = useState(current);
  const [reason, setReason] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [said, setSaid] = useState("");
  const [error, setError] = useState<{ field: "reason" | "step" | null; message: string } | null>(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  const fail = (field: "reason" | "step" | null, message: string) => {
    setError({ field, message });
    setTimeout(() => {
      if (field) document.getElementById(id(field))?.focus();
    }, 0);
  };

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (sending || sent) return;
    if (step === current) {
      fail("step", "Choose a level other than the road's own.");
      return;
    }
    const problem = suggestProblem(reason);
    if (problem) {
      fail(problem.field, problem.message);
      return;
    }
    setError(null);
    setSending(true);
    const outcome = await sendSuggestion(
      origin,
      { osm_way_id: wayId, lat: point[1], lon: point[0], step, reason: reason.trim() },
      csrfFromCookie(document.cookie),
    );
    setSending(false);
    if (outcome.kind === "refused") {
      fail(outcome.field === "step" || outcome.field === "reason" ? outcome.field : null, outcome.message);
      return;
    }
    setSent(true);
    setSaid(outcome.message);
    headingRef.current?.focus();
  };

  const words = suggestValueText(step);
  return (
    <section className="stress-editor suggest-change" aria-labelledby={id("title")}>
      <h3 id={id("title")} ref={headingRef} tabIndex={-1}>
        {SUGGEST_HEADING}
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
          <p className="stress-editor-now">Now: {suggestValueText(current)}.</p>
          <p className="stress-editor-extent">
            <span className="road-info-label">This road piece:</span> {title}
          </p>
          <div className="stress-editor-field">
            <label htmlFor={id("step")}>{SUGGEST_LEVEL_LABEL}</label>
            <div className="stress-editor-slider">
              <input
                id={id("step")}
                type="range"
                min={1}
                max={5}
                step={halfSteps ? 0.5 : 1}
                value={step}
                aria-valuetext={words}
                aria-describedby={id("ticks")}
                aria-invalid={error?.field === "step" ? true : undefined}
                onChange={(event) => setStep(Number(event.target.value))}
              />
              <output htmlFor={id("step")} className="stress-editor-output" aria-hidden="true">
                {words}
              </output>
            </div>
            <p id={id("ticks")} className="hint stress-editor-ticks">
              1 is the calmest, 5 is Avoid. The arrow keys move {halfSteps ? "half a step" : "a whole step"}; Home goes to 1
              and End to 5.
            </p>
          </div>
          <div className="stress-editor-field">
            <label htmlFor={id("reason")}>{SUGGEST_REASON_LABEL}</label>
            <textarea
              id={id("reason")}
              rows={3}
              value={reason}
              required
              aria-required="true"
              aria-invalid={error?.field === "reason" ? true : undefined}
              aria-describedby={`${id("reason-help")}${error?.field === "reason" ? ` ${id("error")}` : ""}`}
              onChange={(event) => setReason(event.target.value)}
            />
            <p id={id("reason-help")} className="hint">
              {SUGGEST_PRIVACY} {countText(reason.trim(), SUGGEST_REASON_MAX)}.
            </p>
          </div>
          <div className="stress-editor-buttons">
            <button type="submit" aria-disabled={sending ? true : undefined}>
              {sending ? "Sending…" : SUGGEST_SEND}
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
