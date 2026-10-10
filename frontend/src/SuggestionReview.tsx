/**
 * The instance admin's review of rider suggestions (OWNER-DECISIONS 460.5; lib/suggestions.ts), in the
 * Settings sheet. Nothing shows for anyone else.
 *
 * Each suggestion has the owner's three actions (2026-10-10): Approve now (applied at once, as the
 * editor's change), Delete, and Send to Discord, which shows the ready-to-paste plain-English poll in a
 * read-only text box with a Copy post button; the suggestion is marked as sent and stays in the list to
 * approve or delete later. Every action button's name says which road it is for (aria-describedby the
 * suggestion's heading); every result, "Copied" included, is a sentence in the section's polite status
 * region, which is always in the page. Status is said in words, never by colour alone.
 *
 * Delete asks first ("Yes, delete" / "Keep it"). After Approve now or Delete the suggestion leaves the
 * list and the focus goes to the next one's heading (the one before, at the end), or to the "No
 * suggestions are waiting" line when none is left: never to the top of the page.
 */
import { useEffect, useId, useState } from "react";
import { copyText, selectionCopy } from "./lib/sidebar.ts";
import { csrfFromCookie, fetchMe } from "./lib/stressEditor.ts";
import {
  COPIED,
  COPY_FAILED,
  COPY_POST,
  REVIEW_HEADING,
  actionSaid,
  fetchSuggestions,
  mapLink,
  reviewSuggestion,
  suggestionLine,
  type DiscordPost,
  type ReviewAction,
  type SuggestionItem,
} from "./lib/suggestions.ts";

interface Props {
  /** A change was approved: the map asks for its stress tiles again. */
  onStressChanged?: (generation: number) => void;
}

export function SuggestionReview({ onStressChanged }: Props) {
  const base = useId();
  const id = (part: string) => `${base}-${part}`;
  const [admin, setAdmin] = useState(false);
  const [items, setItems] = useState<SuggestionItem[] | null>(null);
  const [problem, setProblem] = useState("");
  const [said, setSaid] = useState("");
  const [busy, setBusy] = useState<number | null>(null);
  const [posts, setPosts] = useState<Record<number, DiscordPost>>({});
  // The suggestion whose Delete is asking "Yes, delete / Keep it", and where the focus goes next.
  const [confirming, setConfirming] = useState<number | null>(null);
  const [focusNext, setFocusNext] = useState<string | null>(null);
  const origin = window.location.origin;

  useEffect(() => {
    void fetchMe(origin).then((me) => setAdmin(me.can_change_lts));
  }, [origin]);

  useEffect(() => {
    if (focusNext === null) return;
    document.getElementById(focusNext)?.focus();
    setFocusNext(null);
  }, [focusNext, items, confirming]);

  const load = async () => {
    const next = await fetchSuggestions(origin);
    if (typeof next === "string") setProblem(next);
    else {
      setProblem("");
      setItems(next);
    }
  };

  if (!admin) return null;

  const act = async (item: SuggestionItem, action: ReviewAction) => {
    if (busy !== null) return;
    setBusy(item.id);
    const csrf = csrfFromCookie(document.cookie);
    if (action === "discord") {
      const r = await reviewSuggestion<DiscordPost>(origin, item.id, "discord", csrf);
      setBusy(null);
      if (!r.ok) {
        setSaid(r.message);
        return;
      }
      setPosts((old) => ({ ...old, [item.id]: r.body }));
      setItems((old) => old?.map((s) => (s.id === item.id ? { ...s, status: "sent_to_discord" } : s)) ?? old);
      setSaid(actionSaid("discord", item, ""));
      return;
    }
    const r = await reviewSuggestion(origin, item.id, action, csrf);
    setBusy(null);
    if (!r.ok) {
      setSaid(r.message);
      return;
    }
    setSaid(actionSaid(action, item, r.body.message));
    if (action === "approve" && typeof r.body.generation === "number") onStressChanged?.(r.body.generation);
    setConfirming(null);
    const list = items ?? [];
    const at = list.findIndex((s) => s.id === item.id);
    const rest = list.filter((s) => s.id !== item.id);
    const next = rest[Math.min(Math.max(at, 0), rest.length - 1)];
    setItems(rest);
    setFocusNext(next ? id(`s${next.id}`) : id("none"));
  };

  const copy = async (item: SuggestionItem) => {
    const post = posts[item.id];
    if (!post) return;
    const done = await copyText(post.post, navigator.clipboard, selectionCopy);
    // Said again on a second press: the region is cleared first so the same word is spoken again.
    setSaid("");
    setTimeout(() => setSaid(done ? `${COPIED}. The post for ${item.road} is on the clipboard.` : COPY_FAILED), 50);
  };

  return (
    <section aria-labelledby={id("heading")} className="suggestion-review">
      <h3 id={id("heading")}>{REVIEW_HEADING}</h3>
      <p className="hint">
        Riders' suggested levels wait here. Approve now changes the road at once; Send to Discord gives you a poll to
        paste into any bike group and keeps the suggestion here to approve or delete later.
      </p>
      <p role="status" className="suggestion-review-said">
        {said}
      </p>
      <button type="button" className="secondary" onClick={() => void load()}>
        {items === null ? "Show suggestions" : "Refresh suggestions"}
      </button>
      {problem && <p role="alert">{problem}</p>}
      {items !== null && items.length === 0 && (
        <p id={id("none")} tabIndex={-1}>
          No suggestions are waiting.
        </p>
      )}
      {items !== null && items.length > 0 && (
        <ul className="suggestion-list" aria-label="Suggestions waiting">
          {items.map((item) => {
            const head = id(`s${item.id}`);
            const post = posts[item.id];
            return (
              <li key={item.id} className="suggestion-item">
                <h4 id={head} tabIndex={-1}>
                  {suggestionLine(item)}
                </h4>
                <p className="suggestion-status">
                  {item.status === "sent_to_discord" ? "Sent to Discord; waiting for your decision." : "Waiting for review."}
                </p>
                <p className="suggestion-reason">
                  <span className="road-info-label">Rider's reason:</span> {item.reason}
                </p>
                <p>
                  <a href={mapLink(origin, item)} aria-describedby={head}>
                    Show on map
                  </a>
                </p>
                <div className="stress-editor-buttons">
                  <button type="button" aria-describedby={head} aria-disabled={busy !== null ? true : undefined} onClick={() => void act(item, "approve")}>
                    Approve now
                  </button>
                  <button type="button" className="secondary" aria-describedby={head} aria-disabled={busy !== null ? true : undefined} onClick={() => void act(item, "discord")}>
                    Send to Discord
                  </button>
                  <button
                    type="button"
                    id={id(`d${item.id}`)}
                    className="secondary"
                    aria-describedby={head}
                    aria-expanded={confirming === item.id}
                    aria-disabled={busy !== null ? true : undefined}
                    onClick={() => {
                      setConfirming(item.id);
                      setFocusNext(id(`y${item.id}`));
                    }}
                  >
                    Delete
                  </button>
                </div>
                {confirming === item.id && (
                  <div className="suggestion-confirm" role="group" aria-labelledby={id(`q${item.id}`)}>
                    <p id={id(`q${item.id}`)}>Delete this suggestion? It cannot be brought back.</p>
                    <div className="stress-editor-buttons">
                      <button
                        type="button"
                        id={id(`y${item.id}`)}
                        aria-describedby={head}
                        aria-disabled={busy !== null ? true : undefined}
                        onClick={() => void act(item, "delete")}
                      >
                        Yes, delete
                      </button>
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => {
                          setConfirming(null);
                          setFocusNext(id(`d${item.id}`));
                        }}
                      >
                        Keep it
                      </button>
                    </div>
                  </div>
                )}
                {post && (
                  <div className="suggestion-post">
                    <label htmlFor={id(`p${item.id}`)}>Post for Discord ({post.characters} of 2,000 characters)</label>
                    <textarea id={id(`p${item.id}`)} readOnly rows={12} value={post.post} />
                    <button type="button" aria-describedby={head} onClick={() => void copy(item)}>
                      {COPY_POST}
                    </button>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
