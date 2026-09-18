"""The deployment's liveness probe, and the one route that is meant to be found.

Every other path on this deployment is either behind a Discord session or behind
the unguessable admin prefix. This one is neither, on purpose: a container
healthcheck runs before anything has a session and cannot be given the admin
path without putting that path into `compose.yaml`, the process table and the
orchestrator's logs, which is the one place the prefix was kept out of.

What that costs is bounded by giving the endpoint nothing worth asking for.

It answers `ok` or `degraded` and nothing else - no version, no hostname, no
migration state, no exception text, no counts. A health endpoint is the standard
place for a stack trace to be published to the internet, and the driver's error
for a refused connection carries the database name, user and host. The two words
are what a healthcheck reads; anyone wanting more has the logs, which are behind
the host.

It issues exactly one query, `SELECT 1`, and never a model query. This is the
only unauthenticated route in the deployment and therefore the only one an
anonymous flood can aim at, so its cost has to be a constant that does not grow
with the size of any table. `SELECT 1` on the existing connection is that: it
proves the process can reach PostgreSQL, which is what "can this container serve"
means here, and it proves nothing else. Reaching for a row count, a migration
check or a table scan would turn the probe into an amplifier.

It reports rather than raises. Any failure at all is 503, not a 500: an
orchestrator reads the status line, and the difference between "this container
is not ready" and "this container crashed while being asked" is the difference
between a restart and a paged human.
"""

from __future__ import annotations

from django.db import connection
from django.http import HttpResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

PLAIN_TEXT = "text/plain; charset=utf-8"


@never_cache
@require_http_methods(["GET", "HEAD"])
def healthz(request) -> HttpResponse:
    """200 `ok` while the database answers, 503 `degraded` when it does not.

    `never_cache` is load-bearing rather than tidiness. The answer is a
    statement about this instant, and a proxy or a browser that held the last
    200 for even a few seconds would report a database that has since gone as
    healthy - which is precisely the window a healthcheck exists to close.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:  # noqa: BLE001 - see the module docstring: any failure is 503
        # Deliberately not `django.db.Error`. The failures this has to survive
        # are wider than the DB-API hierarchy - a connection refused surfaces as
        # OperationalError, but a misconfigured or torn-down connection raises
        # ImproperlyConfigured or InterfaceError, and an exhausted pool can
        # raise whatever the driver chooses. Every one of them means the same
        # thing to the orchestrator, and catching only some of them would make
        # the health endpoint itself the thing that 500s.
        return HttpResponse("degraded\n", status=503, content_type=PLAIN_TEXT)
    return HttpResponse("ok\n", status=200, content_type=PLAIN_TEXT)
