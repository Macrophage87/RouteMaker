/**
 * A survey spot's card (lib/surveySpots.ts; the owner, 2026-11-25): the platform's modal <dialog>, as a route note's
 * (NoteDialog.tsx). "When were you last here?" first, then the spot's own one-tap questions, each with "Not sure".
 * Only "When" must be answered. Send keeps the answers and the spot leaves the rider's map; Cancel keeps nothing.
 * Signed out, the card says to sign in and asks nothing. Escape is Cancel; on close the focus goes back where it was.
 */
import { useEffect, useId, useRef, useState } from "react";
import {
  loadSurveyQuestions,
  sendSurveyAnswers,
  surveyHeading,
  SURVEY_CANCEL,
  SURVEY_DONE,
  SURVEY_FAILED,
  SURVEY_LOADING,
  SURVEY_NEED_WHEN,
  SURVEY_SEND,
  SURVEY_SENT,
  SURVEY_SIGN_IN,
  type Fetch,
  type SurveyMine,
  type SurveyQuestion,
  type SurveySpot,
} from "./lib/surveySpots.ts";
import { language, planLanguageAttributes } from "./lib/i18n.ts";

export function SurveyCard({
  spot,
  origin,
  signedIn,
  onSent,
  onClose,
  fetcher,
}: {
  spot: SurveySpot | null;
  origin: string;
  signedIn: boolean;
  /** After a send the server took: the rider's done list and count. The card says thanks and stays till closed. */
  onSent: (spot: SurveySpot, mine: SurveyMine) => void;
  /** `sent` when it closes on Done after a send (the next spot passed may follow); false on Cancel or Escape. */
  onClose: (sent: boolean) => void;
  fetcher?: Fetch;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const opener = useRef<Element | null>(null);
  const headingId = useId();
  const [questions, setQuestions] = useState<SurveyQuestion[] | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [said, setSaid] = useState("");
  const [sent, setSent] = useState(false);
  const [sending, setSending] = useState(false);
  const open = spot !== null;
  /** The questions come from the server in English. */
  const english = language() === "en";
  const loading = open && signedIn && !sent && questions === null && !said;

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      opener.current = document.activeElement;
      dialog.showModal?.();
    } else if (!open && dialog.open) {
      dialog.close();
      if (opener.current instanceof HTMLElement && opener.current.isConnected) opener.current.focus();
    }
  }, [open]);

  useEffect(() => {
    setAnswers({});
    setSaid("");
    setSent(false);
    setQuestions(null);
    if (!spot || !signedIn) return;
    let live = true;
    void loadSurveyQuestions(origin, spot.id, fetcher).then((q) => {
      if (!live) return;
      if (q) setQuestions(q);
      else setSaid(SURVEY_FAILED);
    });
    return () => {
      live = false;
    };
  }, [spot, signedIn, origin, fetcher]);

  const send = async () => {
    if (!spot || sending) return;
    if (!answers.when) {
      setSaid(SURVEY_NEED_WHEN);
      return;
    }
    setSending(true);
    const result = await sendSurveyAnswers(origin, spot.id, answers, fetcher);
    setSending(false);
    if (result.ok) {
      setSent(true);
      setSaid(SURVEY_SENT);
      onSent(spot, result.mine);
    } else setSaid(result.said);
  };

  return (
    <dialog
      ref={dialogRef}
      className="ask-dialog survey-card"
      aria-labelledby={headingId}
      {...planLanguageAttributes()}
      onCancel={(event) => {
        event.preventDefault();
        onClose(false);
      }}
    >
      {spot && (
        <form
          method="dialog"
          onSubmit={(event) => {
            event.preventDefault();
            if (sent) onClose(true);
            else void send();
          }}
        >
          <h2 id={headingId}>{surveyHeading(spot.road)}</h2>
          {!signedIn && <p>{SURVEY_SIGN_IN}</p>}
          {signedIn &&
            !sent &&
            questions?.map((q) => (
              <fieldset key={q.key} className="survey-question" lang={english ? undefined : "en"}>
                <legend>{q.text}</legend>
                {q.options.map((o) => (
                  <label key={o.value}>
                    <input
                      type="radio"
                      name={`survey-${q.key}`}
                      value={o.value}
                      checked={answers[q.key] === o.value}
                      onChange={() => {
                        setAnswers((a) => ({ ...a, [q.key]: o.value }));
                        setSaid("");
                      }}
                    />
                    {o.label}
                  </label>
                ))}
              </fieldset>
            ))}
          <p className="survey-said" role="status">
            {loading ? SURVEY_LOADING : said}
          </p>
          <div className="closure-choices survey-actions">
            {signedIn && !sent && questions && (
              <button type="submit" className="primary" aria-disabled={sending ? true : undefined}>
                {SURVEY_SEND}
              </button>
            )}
            <button type="button" className="secondary" onClick={() => onClose(sent)}>
              {sent ? SURVEY_DONE : SURVEY_CANCEL}
            </button>
          </div>
        </form>
      )}
    </dialog>
  );
}
