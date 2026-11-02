/**
 * A Featured routes post's script (core/route_posts.py): served at /post.js under that fixed name, so the server's
 * page can name it, and revalidated on every load (Caddyfile @frontend, the beta's nginx). Everything it does is in
 * postPage.tsx, loaded from here so its styles come with it (Vite adds a dynamic import's CSS itself) and the page's
 * words show at once. The page is in English or Spanish: Spanish's catalog comes first where it is the language
 * (lib/i18n.ts loadLanguage), as in the app's main.tsx, since the page's modules word some labels as they load.
 */
import { language, loadLanguage } from "../lib/i18n.ts";
import { followTheme } from "../lib/themeClock.ts";

// The app's theme and the rider's Colors choice here too: the app's stylesheet, which comes with the charts, takes its
// colours from the class, and so does the page's own CSS once it is set (core/route_posts.py STYLE).
followTheme();

void (language() === "es" ? loadLanguage("es") : Promise.resolve())
  .then(() => import("./postPage.tsx"))
  .then((page) => page.start());
