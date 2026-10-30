"""The api's access log, with link ids and map tiles taken out of the path.

docker/api-entrypoint.sh hands gunicorn `--logger-class config.access_log.Logger`. The format
already leaves out the query string (`%(U)s`, never `%(r)s`); this takes out what is in the path
itself and would say where someone is or let a reader open their link later:

  /api/rides/<id>, and its alerts' ids       a live ride's link
  /api/shared-routes/<id>, /s/<id>           a shared route (and the owner's revoke of one)
  /mcp/gpx/<token>                           an assistant's GPX download
  /tiles/stress/<z>/<x>/<y>.pbf, and mass    the map the rider is looking at, to a few blocks

each logged as its route's shape (`/api/rides/:id/here`, `/tiles/stress/:zxy`), so the method,
status and timing of every request are still there to read. The beta's nginx logs the same paths
the same way (deploy/beta/nginx-routemaker.conf.template, `$rmbeta_logpath`), and
tests/test_server_logs.py holds the two lists equal. Django's own `django.request` lines (a 404
or a 500 with its path) go through `PathFilter`, and the api's unhandled-error line through
`logged_path`.
"""

from __future__ import annotations

import re

try:
    from gunicorn.glogging import Logger as _GunicornLogger
except ImportError:  # the api image has gunicorn; a checkout's test run may not
    _GunicornLogger = object

# (pattern, replacement), the first that matches wins.
REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"^/api/rides/[^/]+/alerts/[^/]+(?P<rest>.*)$"),
        r"/api/rides/:id/alerts/:id\g<rest>",
    ),
    (re.compile(r"^/api/rides/[^/]+(?P<rest>.*)$"), r"/api/rides/:id\g<rest>"),
    (
        re.compile(r"^/api/(?P<me>me/)?shared-routes/[^/]+(?P<rest>.*)$"),
        r"/api/\g<me>shared-routes/:id\g<rest>",
    ),
    (re.compile(r"^/s/[^/]+(?P<rest>.*)$"), r"/s/:id\g<rest>"),
    (re.compile(r"^/mcp/gpx/.*$"), "/mcp/gpx/:token"),
    (re.compile(r"^/tiles/(?P<kind>[^/]+)/.*$"), r"/tiles/\g<kind>/:zxy"),
)


def logged_path(path: str | None) -> str:
    """The path as the access log writes it: ids and tile coordinates replaced."""
    if not path:
        return "-"
    for pattern, replacement in REDACTIONS:
        if pattern.match(path):
            return pattern.sub(replacement, path, count=1)
    return path


class Logger(_GunicornLogger):
    """gunicorn's logger, with `logged_path` applied to every atom that carries the path."""

    def atoms(self, resp, req, environ, request_time):
        atoms = super().atoms(resp, req, environ, request_time)
        path = logged_path(environ.get("PATH_INFO"))
        atoms["U"] = path
        # Not in the format, and kept out in case it is ever put back: the request line and
        # the query string (RAW_URI holds both), the Referer, the request's headers (`{referer}i`,
        # `{host}i`, ...) and the raw environ.
        atoms["r"] = f"{environ.get('REQUEST_METHOD')} {path} {environ.get('SERVER_PROTOCOL')}"
        atoms["q"] = "-"
        atoms["f"] = "-"
        for key in [k for k in atoms if k.endswith(("}i", "}e"))]:
            del atoms[key]
        return atoms


class PathFilter:
    """A logging filter for `django.request`, which logs every 4xx and 5xx answer as
    "Not Found: <path>" and "Internal Server Error: <path>": each argument that is a path is
    written through `logged_path`, as the access logs write it (settings.LOGGING)."""

    def filter(self, record) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                logged_path(arg) if isinstance(arg, str) and arg.startswith("/") else arg
                for arg in record.args
            )
        return True
