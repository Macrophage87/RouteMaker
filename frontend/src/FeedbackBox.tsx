/**
 * Send feedback (lib/feedback.ts; the owner, 2026-11-12: text only, through the server, nothing kept): one button in
 * Settings' About and in the Beta notice, shown only where the server takes feedback. It opens a short box: the
 * rider's words, one line saying what goes with them (and that where they are never does), Send. No screenshot.
 */
import { useEffect, useId, useRef, useState } from "react";
import { t } from "./lib/i18n.ts";
import { FEEDBACK_MAX, FEEDBACK_MIN, feedbackOn, sendFeedback, type FeedbackDetails } from "./lib/feedback.ts";

export const FEEDBACK_BUTTON = () => t("Send feedback");
export const FEEDBACK_ASK = () => t("What happened?");
export const FEEDBACK_SENT_WITH = () => t("Sent with the app version, browser and ride type. Never where you are.");
export const FEEDBACK_SENT = () => t("Sent. Thank you.");
export const FEEDBACK_FAILED = () => t("Could not send. Try again later.");

/**
 * Whether this server takes feedback (GET /api/feedback). A yes is kept for the page; a no is asked again when the box is
 * next drawn, since it may only mean the api was stopped for an update at the time.
 */
let takes = false;
async function serverTakesFeedback(): Promise<boolean> {
  if (!takes) takes = await feedbackOn(window.location.origin);
  return takes;
}

export function FeedbackBox({ details, onSay }: { details: () => FeedbackDetails; onSay?: (text: string) => void }) {
  const [on, setOn] = useState(false);
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent" | "failed">("idle");
  const id = `feedback-${useId().replace(/:/g, "")}`;
  const box = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    let live = true;
    void serverTakesFeedback().then((yes) => live && setOn(yes));
    return () => {
      live = false;
    };
  }, []);
  if (!on) return null;
  const say = (line: string) => {
    setState(line === FEEDBACK_SENT() ? "sent" : "failed");
    onSay?.(line);
  };
  const send = async () => {
    if (text.trim().length < FEEDBACK_MIN || state === "sending") return;
    setState("sending");
    const result = await sendFeedback(window.location.origin, text, details());
    if (result === "sent") {
      setText("");
      say(FEEDBACK_SENT());
    } else say(FEEDBACK_FAILED());
  };
  return (
    <div className="feedback-box">
      <button
        type="button"
        className="feedback-open"
        aria-expanded={open}
        aria-controls={`${id}-form`}
        onClick={() => {
          setOpen(!open);
          if (!open) window.setTimeout(() => box.current?.focus(), 0);
        }}
      >
        {FEEDBACK_BUTTON()}
      </button>
      <form
        id={`${id}-form`}
        hidden={!open}
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        <label htmlFor={`${id}-text`}>{FEEDBACK_ASK()}</label>
        <textarea
          id={`${id}-text`}
          ref={box}
          rows={4}
          maxLength={FEEDBACK_MAX}
          value={text}
          aria-describedby={`${id}-note`}
          onChange={(event) => {
            setText(event.target.value);
            if (state !== "sending") setState("idle");
          }}
        />
        <p id={`${id}-note`} className="hint">
          {FEEDBACK_SENT_WITH()}
        </p>
        {/* aria-disabled, not disabled: a disabled button drops keyboard focus to the page when a send ends. send()
            itself refuses while sending or with too little text. */}
        <button type="submit" aria-disabled={state === "sending" || text.trim().length < FEEDBACK_MIN ? true : undefined}>
          {t("Send")}
        </button>
        {/* Said once, through the page's own live region (onSay); shown here. */}
        <p className="hint feedback-said">
          {state === "sent" ? FEEDBACK_SENT() : state === "failed" ? FEEDBACK_FAILED() : ""}
        </p>
      </form>
    </div>
  );
}
