// The ride left going (ResumeRideDialog): Resume ride shows busy while Ride mode's code arrives (lib/rideCodeWait.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import { click, render } from "./testSupport/render.ts";
import { ResumeRideDialog } from "./ResumeRideDialog.tsx";

test("Resume ride is busy while Ride mode's code arrives, and plain again once in", async () => {
  let resumed = 0;
  const ui = (busy: boolean) => <ResumeRideDialog open destination="Union Station" busy={busy} onResume={() => resumed++} onNotNow={() => {}} onLater={() => {}} />;
  const screen = await render(ui(false));
  const resume = screen.button("Resume ride");
  assert.equal(resume.getAttribute("aria-busy"), null);
  await click(resume);
  assert.equal(resumed, 1);
  await screen.rerender(ui(true));
  assert.equal(screen.button("Resume ride").getAttribute("aria-busy"), "true");
  assert.equal(screen.button("Resume ride").getAttribute("aria-disabled"), "true");
  await screen.rerender(ui(false));
  assert.equal(screen.button("Resume ride").getAttribute("aria-busy"), null);
});
