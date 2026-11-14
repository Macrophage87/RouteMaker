/**
 * Anonymous daily usage totals (core.usage on the server; the owner, 2026-11-13: "Yes to anonymous data totals").
 * The server counts most tools from the requests it already answers; a ride, walk or run started is seen only here,
 * so Start tells it the kind, and nothing else: no route, place, account or time. A count that fails is dropped.
 */

export type UsedTool = "ride" | "walk" | "run";

export function countUse(origin: string, tool: UsedTool, send: typeof fetch = fetch): void {
  try {
    void send(`${origin}/api/usage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tool }),
      keepalive: true,
    }).catch(() => undefined);
  } catch {
    // Counting never stops a ride.
  }
}
