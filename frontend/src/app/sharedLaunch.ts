/**
 * A place shared to RouteMaker (v0.7.0, "Open shared locations in RouteMaker"): Android's Share sheet opens the
 * installed app at "/?share_title=…&share_text=…&share_url=…" (the manifest's share_target), and desktop Chrome
 * and Edge open geo: links at "/?geo=…" (its protocol_handlers). The place is read (lib/sharedLocation.ts; a short
 * link through the server) and opened in Go as the destination, ready to route: one tap, the share itself.
 * The parameters leave the address bar at once, so a reload does not open the place again.
 */
import { useEffect, useRef } from "react";
import type { Place } from "../lib/geocode.ts";
import { launchShare, readShared, withoutShare } from "../lib/sharedLocation.ts";

/** What a share with an address but no point says: where to go on from. */
export const sharedQuerySaid = (query: string): string => `The shared place has no map point. Type “${query}” in Where to? to find it.`;

export function useSharedLaunch(open: (place: Place) => void, say: (text: string) => void): void {
  const latest = useRef({ open, say });
  latest.current = { open, say };
  useEffect(() => {
    const text = launchShare(window.location.search);
    if (!text) return;
    window.history.replaceState(window.history.state, "", withoutShare(window.location.href));
    void readShared(text).then((read) => {
      if ("place" in read) latest.current.open(read.place);
      else if ("query" in read) latest.current.say(sharedQuerySaid(read.query));
      else latest.current.say(read.error);
    });
  }, []);
}
