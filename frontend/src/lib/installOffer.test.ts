// The install offer (lib/installOffer.ts; WEB-NAV-plan.md section 8 "Install prompt", P4).
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { IOS_INSTALL, INSTALL_LABEL, installOffer, installState, isIos, isStandalone, promptInstall, resetInstall, subscribeInstall, watchInstall } from "./installOffer.ts";

afterEach(() => resetInstall());

const IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.4 Mobile/15E148 Safari/604.1";
const ANDROID = "Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Mobile Safari/537.36";

function fakeWindow({ ua = ANDROID, platform = "Linux", touch = 5, display = "browser", iosStandalone = undefined as boolean | undefined } = {}) {
  const listeners = new Map<string, (event: Event) => void>();
  return {
    listeners,
    addEventListener: (type: string, fn: (event: Event) => void) => listeners.set(type, fn),
    matchMedia: (query: string) => ({ matches: query === `(display-mode: ${display})` }),
    navigator: { userAgent: ua, platform, maxTouchPoints: touch, standalone: iosStandalone },
  };
}

function promptEvent(outcome: "accepted" | "dismissed") {
  const calls: string[] = [];
  return {
    calls,
    preventDefault: () => calls.push("preventDefault"),
    prompt: async () => void calls.push("prompt"),
    userChoice: Promise.resolve({ outcome }),
  };
}

test("the offer: installed first, then the button, then the iOS line, else nothing", () => {
  assert.equal(installOffer({ promptable: true, installed: false, standalone: true, ios: false }), "installed");
  assert.equal(installOffer({ promptable: true, installed: true, standalone: false, ios: false }), "installed");
  assert.equal(installOffer({ promptable: true, installed: false, standalone: false, ios: false }), "button");
  assert.equal(installOffer({ promptable: false, installed: false, standalone: false, ios: true }), "ios");
  assert.equal(installOffer({ promptable: false, installed: false, standalone: false, ios: false }), "none");
});

test("the words are the plan's", () => {
  assert.equal(INSTALL_LABEL, "Install RouteMaker");
  assert.equal(IOS_INSTALL, "In Safari, press Share, then Add to Home Screen.");
});

test("iOS: an iPhone, and an iPad that says it is a Mac; not a Mac, not Android", () => {
  assert.equal(isIos(IPHONE), true);
  assert.equal(isIos("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15", "MacIntel", 5), true);
  assert.equal(isIos("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15", "MacIntel", 0), false);
  assert.equal(isIos(ANDROID, "Linux", 5), false);
});

test("standalone: the installed display modes, or iOS's own flag; a tab is not", () => {
  assert.equal(isStandalone(fakeWindow({ display: "standalone" })), true);
  assert.equal(isStandalone(fakeWindow({ display: "fullscreen" })), true);
  assert.equal(isStandalone(fakeWindow({ ua: IPHONE, iosStandalone: true })), true);
  assert.equal(isStandalone(fakeWindow()), false);
  assert.equal(isStandalone(null), false);
});

test("the browser's prompt is held (its own bar suppressed) and offered as the button; appinstalled hides it", () => {
  const win = fakeWindow();
  watchInstall(win);
  let changes = 0;
  subscribeInstall(() => (changes += 1));
  assert.equal(installOffer(installState()), "none");
  const event = promptEvent("accepted");
  win.listeners.get("beforeinstallprompt")!(event as unknown as Event);
  assert.deepEqual(event.calls, ["preventDefault"]);
  assert.equal(installOffer(installState()), "button");
  win.listeners.get("appinstalled")!({} as Event);
  assert.equal(installOffer(installState()), "installed");
  assert.equal(changes, 2);
});

test("the press shows the browser's dialog once; accepted or dismissed, the held prompt is let go", async () => {
  const win = fakeWindow();
  watchInstall(win);
  const accepted = promptEvent("accepted");
  win.listeners.get("beforeinstallprompt")!(accepted as unknown as Event);
  assert.equal(await promptInstall(), "accepted");
  assert.deepEqual(accepted.calls, ["preventDefault", "prompt"]);
  assert.equal(installState().promptable, false);
  assert.equal(await promptInstall(), "none");
  const dismissed = promptEvent("dismissed");
  win.listeners.get("beforeinstallprompt")!(dismissed as unknown as Event);
  assert.equal(await promptInstall(), "dismissed");
  assert.equal(installOffer(installState()), "none");
});

test("on an iPhone in Safari the offer is the line; installed from the home screen, none", () => {
  watchInstall(fakeWindow({ ua: IPHONE, platform: "iPhone" }));
  assert.equal(installOffer(installState()), "ios");
  resetInstall();
  watchInstall(fakeWindow({ ua: IPHONE, platform: "iPhone", iosStandalone: true }));
  assert.equal(installOffer(installState()), "installed");
});
