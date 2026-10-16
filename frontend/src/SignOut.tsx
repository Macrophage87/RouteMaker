/**
 * Sign out of this session (v0.7.0 end review): a plain form POST to /auth/logout (core.auth_views.logout_view)
 * with the CSRF token, as any form sends it. The server ends the session and sends the page to "/", which loads
 * signed out. The token is the cookie GET /api/me/go set when the page read the account's My Go.
 */
import { csrfFromCookie } from "./lib/stressEditor.ts";

export function SignOutForm() {
  return (
    <form method="post" action="/auth/logout" className="sign-out">
      <input type="hidden" name="csrfmiddlewaretoken" value={csrfFromCookie(document.cookie) ?? ""} />
      <button type="submit" className="secondary">
        Sign out
      </button>
    </form>
  );
}
