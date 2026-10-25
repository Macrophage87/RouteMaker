/**
 * A Featured routes post's script (core/route_posts.py): served at /post.js under that fixed name, so the server's
 * page can name it, and revalidated on every load (Caddyfile @frontend, the beta's nginx). Everything it does is in
 * postPage.tsx, loaded from here so its styles come with it (Vite adds a dynamic import's CSS itself) and the page's
 * words show at once.
 */
void import("./postPage.tsx").then((page) => page.start());
