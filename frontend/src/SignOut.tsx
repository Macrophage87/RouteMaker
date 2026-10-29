/**
 * Sign out of this session (v0.7.0 end review): a plain form POST to /auth/logout (core.auth_views.logout_view)
 * with the CSRF token, as any form sends it. The server ends the session and sends the page to "/", which loads
 * signed out. The token is the cookie GET /api/me/go set when the page read the account's My Go.
 *
 * Sign out everywhere, beside it (Stephen approved the one control, 2026-10-29): the same kind of form to
 * /auth/logout-everywhere (logout_everywhere_view), which ends every session of the account, this one too, and its
 * assistant apps' grants. One button, asked once, in the danger style.
 */
import { t } from "./lib/i18n.ts";
import { csrfFromCookie } from "./lib/stressEditor.ts";

export const SIGN_OUT_EVERYWHERE = t("Sign out everywhere");
export const SIGN_OUT_EVERYWHERE_ASK = t("Sign out on every device, this one too, and disconnect your AI assistant apps?");

export function SignOutForm() {
  return (
    <form method="post" action="/auth/logout" className="sign-out">
      <input type="hidden" name="csrfmiddlewaretoken" value={csrfFromCookie(document.cookie) ?? ""} />
      <button type="submit" className="secondary">
        {t("Sign out")}
      </button>
    </form>
  );
}

export function SignOutEverywhereForm() {
  return (
    <form
      method="post"
      action="/auth/logout-everywhere"
      className="sign-out-everywhere"
      onSubmit={(event) => {
        if (!window.confirm(SIGN_OUT_EVERYWHERE_ASK)) event.preventDefault();
      }}
    >
      <input type="hidden" name="csrfmiddlewaretoken" value={csrfFromCookie(document.cookie) ?? ""} />
      <button type="submit" className="secondary danger">
        {SIGN_OUT_EVERYWHERE}
      </button>
    </form>
  );
}
