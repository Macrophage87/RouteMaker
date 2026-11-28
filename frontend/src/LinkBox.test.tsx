// The link box under a "could not copy" line, as a screen reader meets it (LinkBox.tsx).
import { test } from "node:test";
import assert from "node:assert/strict";
import { render } from "./testSupport/render.ts";
import { LinkBox } from "./LinkBox.tsx";

test("the link box is described by the line that says why it is there", async () => {
  const screen = await render(
    <>
      <p id="said">Could not copy the link. Select it below and copy it.</p>
      <LinkBox link="https://example.org/#r" describedBy="said" />
    </>,
  );
  const box = screen.get("textbox", "Link");
  const line = document.getElementById(box.getAttribute("aria-describedby") ?? "");
  assert.equal(line?.textContent, "Could not copy the link. Select it below and copy it.");
  assert.equal((box as HTMLInputElement).value, "https://example.org/#r");
});
