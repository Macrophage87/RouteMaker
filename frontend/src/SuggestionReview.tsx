/**
 * The instance admin's review of rider suggestions (OWNER-DECISIONS 460.5, 232; lib/suggestions.ts,
 * lib/junctionSuggest.ts), in the Settings sheet. Nothing shows for anyone else.
 *
 * Roads' and junctions' suggestions wait in one list, oldest first, each with the owner's three actions
 * (2026-10-10): Approve now (a road's applied at once, as the editor's change; a junction's becomes a
 * junction override, or for Avoid an Avoid-rated junction, which the next plan uses), Delete, and Send to
 * Discord, which shows the ready-to-paste plain-English poll in a read-only text box with a Copy post
 * button; the suggestion is marked as sent and stays in the list to approve or delete later. Every action
 * button's name says which road or junction it is for (aria-describedby the suggestion's heading); every
 * result, "Copied" included, is a sentence in the section's polite status region, which is always in the
 * page. Status is said in words, never by colour alone.
 *
 * Delete asks first ("Yes, delete" / "Keep it"). After Approve now or Delete the suggestion leaves the
 * list and the focus goes to the next one's heading (the one before, at the end), or to the "No
 * suggestions are waiting" line when none is left: never to the top of the page.
 */
import { useEffect, useId, useRef, useState } from "react";
import { copyText, selectionCopy } from "./lib/sidebar.ts";
import { csrfFromCookie, fetchMe } from "./lib/stressEditor.ts";
import {
  COPIED,
  COPY_FAILED,
  COPY_POST,
  REVIEW_HEADING,
  fetchSuggestions,
  mapLink,
  reviewSuggestion,
  type DiscordPost,
  type ReviewAction,
} from "./lib/suggestions.ts";
import { entrySaid, fetchJunctionSuggestions, loadProblem, reviewEntries, reviewJunctionSuggestion, type ReviewEntry } from "./lib/junctionSuggest.ts";

interface Props {
  /** A change was approved: the map asks for its stress tiles again. */
  onStressChanged?: (generation: number) => void;
}

export function SuggestionReview({ onStressChanged }: Props) {
  const base = useId();
  const id = (part: string) => `${base}-${part}`;
  const [admin, setAdmin] = useState(false);
  const [items, setItems] = useState<ReviewEntry[] | null>(null);
  const [problem, setProblem] = useState("");
  const [said, setSaid] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [posts, setPosts] = useState<Record<string, DiscordPost>>({});
  // The suggestion whose Delete is asking "Yes, delete / Keep it", and where the focus goes next.
  const [confirming, setConfirming] = useState<string | null>(null);
  // The suggestion whose Approve now is waiting on its warning's confirmation.
  const [warned, setWarned] = useState<string | null>(null);
  const [focusNext, setFocusNext] = useState<string | null>(null);
  // The list as last drawn: an action's answer arrives after a wait, when `items` captured at its
  // start may be out of date (a refresh, another action).
  const itemsNow = useRef<ReviewEntry[] | null>(null);
  itemsNow.current = items;
  const origin = window.location.origin;

  useEffect(() => {
    void fetchMe(origin).then((me) => setAdmin(me.can_change_lts));
  }, [origin]);

  useEffect(() => {
    if (focusNext === null) return;
    document.getElementById(focusNext)?.focus();
    setFocusNext(null);
  }, [focusNext, items, confirming, warned]);

  const load = async () => {
    const [roads, junctions] = await Promise.all([fetchSuggestions(origin), fetchJunctionSuggestions(origin)]);
    // Whichever list came is shown; a list that did not come says so, by name.
    setProblem(loadProblem(roads, junctions));
    if (typeof roads === "string" && typeof junctions === "string") return;
    setItems(reviewEntries(typeof roads === "string" ? [] : roads, typeof junctions === "string" ? [] : junctions));
  };

  if (!admin) return null;

  const review = <T,>(item: ReviewEntry, action: ReviewAction, csrf: string | null) =>
    item.kind === "road" ? reviewSuggestion<T>(origin, item.id, action, csrf) : reviewJunctionSuggestion<T>(origin, item.id, action, csrf);

  const act = async (item: ReviewEntry, action: ReviewAction) => {
    if (busy !== null) return;
    setBusy(item.key);
    const csrf = csrfFromCookie(document.cookie);
    if (action === "discord") {
      const r = await review<DiscordPost>(item, "discord", csrf);
      setBusy(null);
      if (!r.ok) {
        setSaid(r.message);
        return;
      }
      setPosts((old) => ({ ...old, [item.key]: r.body }));
      setItems((old) => old?.map((s) => (s.key === item.key ? { ...s, status: "sent_to_discord" } : s)) ?? old);
      setSaid(entrySaid("discord", item, ""));
      return;
    }
    const r = await review<{ message: string; status: string; generation?: number | null }>(item, action, csrf);
    setBusy(null);
    if (!r.ok) {
      setSaid(r.message);
      return;
    }
    setSaid(entrySaid(action, item, r.body.message));
    if (action === "approve" && item.kind === "road" && typeof r.body.generation === "number") onStressChanged?.(r.body.generation);
    setConfirming(null);
    setWarned(null);
    const list = itemsNow.current ?? [];
    const at = list.findIndex((s) => s.key === item.key);
    const rest = list.filter((s) => s.key !== item.key);
    const next = rest[Math.min(Math.max(at, 0), rest.length - 1)];
    setItems((old) => old?.filter((s) => s.key !== item.key) ?? old);
    setFocusNext(next ? id(`s${next.key}`) : id("none"));
  };

  const copy = async (item: ReviewEntry) => {
    const post = posts[item.key];
    if (!post) return;
    const done = await copyText(post.post, navigator.clipboard, selectionCopy);
    // Said again on a second press: the region is cleared first so the same word is spoken again.
    setSaid("");
    setTimeout(() => setSaid(done ? `${COPIED}. The post for ${item.place} is on the clipboard.` : COPY_FAILED), 50);
  };

  return (
    <section aria-labelledby={id("heading")} className="suggestion-review">
      <h3 id={id("heading")}>{REVIEW_HEADING}</h3>
      <p className="hint">
        Riders' suggested levels for roads and junctions wait here. Approve now changes the road at once, or the
        junction for every route planned from then on; Send to Discord gives you a poll to paste into any bike group
        and keeps the suggestion here to approve or delete later.
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
            const head = id(`s${item.key}`);
            const post = posts[item.key];
            return (
              <li key={item.key} className={`suggestion-item suggestion-item-${item.kind}`}>
                <h4 id={head} tabIndex={-1}>
                  {item.line}
                </h4>
                <p className="suggestion-status">
                  {item.status === "sent_to_discord" ? "Sent to Discord; waiting for your decision." : "Waiting for review."}
                </p>
                {item.detail && <p className="suggestion-detail">{item.detail}</p>}
                <p className="suggestion-reason">
                  <span className="road-info-label">Rider's reason:</span> {item.reason}
                </p>
                <p>
                  <a href={mapLink(origin, item)} aria-describedby={head}>
                    Show on map
                  </a>
                </p>
                <div className="stress-editor-buttons">
                  <button
                    type="button"
                    id={id(`a${item.key}`)}
                    aria-describedby={head}
                    aria-expanded={item.warning ? warned === item.key : undefined}
                    aria-disabled={busy !== null ? true : undefined}
                    onClick={() => {
                      if (!item.warning) {
                        void act(item, "approve");
                        return;
                      }
                      setWarned(item.key);
                      setFocusNext(id(`w${item.key}`));
                    }}
                  >
                    Approve now
                  </button>
                  <button type="button" className="secondary" aria-describedby={head} aria-disabled={busy !== null ? true : undefined} onClick={() => void act(item, "discord")}>
                    Send to Discord
                  </button>
                  <button
                    type="button"
                    id={id(`d${item.key}`)}
                    className="secondary"
                    aria-describedby={head}
                    aria-expanded={confirming === item.key}
                    aria-disabled={busy !== null ? true : undefined}
                    onClick={() => {
                      setConfirming(item.key);
                      setFocusNext(id(`y${item.key}`));
                    }}
                  >
                    Delete
                  </button>
                </div>
                {item.warning && warned === item.key && (
                  <div className="suggestion-confirm" role="group" aria-labelledby={id(`wq${item.key}`)}>
                    <p id={id(`wq${item.key}`)}>{item.warning}</p>
                    <div className="stress-editor-buttons">
                      <button
                        type="button"
                        id={id(`w${item.key}`)}
                        aria-describedby={head}
                        aria-disabled={busy !== null ? true : undefined}
                        onClick={() => void act(item, "approve")}
                      >
                        Yes, approve
                      </button>
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => {
                          setWarned(null);
                          setFocusNext(id(`a${item.key}`));
                        }}
                      >
                        Don't approve
                      </button>
                    </div>
                  </div>
                )}
                {confirming === item.key && (
                  <div className="suggestion-confirm" role="group" aria-labelledby={id(`q${item.key}`)}>
                    <p id={id(`q${item.key}`)}>Delete this suggestion? It cannot be brought back.</p>
                    <div className="stress-editor-buttons">
                      <button
                        type="button"
                        id={id(`y${item.key}`)}
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
                          setFocusNext(id(`d${item.key}`));
                        }}
                      >
                        Keep it
                      </button>
                    </div>
                  </div>
                )}
                {post && (
                  <div className="suggestion-post">
                    <label htmlFor={id(`p${item.key}`)}>Post for Discord ({post.characters} of 2,000 characters)</label>
                    <textarea id={id(`p${item.key}`)} readOnly rows={12} value={post.post} />
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
