"""`/healthz`: the one route on this deployment that is meant to be found.

The container healthcheck needs a path it can curl before any session exists,
and the only other candidate was the admin prefix - which would have put the
prefix into `compose.yaml`, the process table and the orchestrator's logs, the
one place it was deliberately kept out of. So the endpoint is public, and the
whole of its safety is that it is worth nothing to find.

That is what these tests are about. The status codes are the easy half; the
assertions that matter are the ones about what the endpoint does *not* do -
publish anything about the deployment, mint a session, permit caching, or cost
more than a constant to ask.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

db = pytest.mark.django_db(transaction=True)

HEALTH_PATH = "/healthz"


class Boom(RuntimeError):
    """Not a `django.db.Error`, on purpose.

    A connection that has been torn down or misconfigured does not always fail
    inside the DB-API hierarchy, and the orchestrator needs the same answer
    however the driver chose to complain. A handler narrow enough to miss this
    would make the health endpoint the thing that 500s during an outage.
    """


def break_the_connection(monkeypatch) -> None:
    def refuse(*args, **kwargs):
        raise Boom("connection refused")

    monkeypatch.setattr("core.health.connection.cursor", refuse)


def test_the_route_is_wired_at_a_fixed_public_path() -> None:
    """Reversed *and* asserted as a literal. The healthcheck in `compose.yaml`
    is a curl of a hardcoded string, so a rename that only the reverse follows
    would leave the container reporting unhealthy for a route that works."""
    assert reverse("healthz") == HEALTH_PATH


def test_it_is_not_behind_the_admin_prefix() -> None:
    """The point of the endpoint. If it moved under `ADMIN_PATH` the healthcheck
    could not reach it without publishing that path."""
    from django.conf import settings

    assert not HEALTH_PATH.strip("/").startswith(settings.ADMIN_PATH.strip("/"))


@db
class TestWhatItAnswers:
    def test_a_working_database_is_two_hundred(self, client) -> None:
        response = client.get(HEALTH_PATH)
        assert response.status_code == 200
        assert response.content.strip() == b"ok"

    def test_a_broken_connection_is_five_hundred_and_three(self, client, monkeypatch) -> None:
        """503 and not 500: an orchestrator reads the status line, and the
        difference between "not ready" and "crashed while being asked" is the
        difference between a restart and a paged human."""
        break_the_connection(monkeypatch)
        response = client.get(HEALTH_PATH)
        assert response.status_code == 503
        assert response.content.strip() == b"degraded"

    def test_it_needs_no_authentication(self, client) -> None:
        """Asserted rather than assumed, because every other route on this
        deployment refuses an anonymous request and a decorator added here by
        habit would make the healthcheck fail closed forever."""
        assert "Cookie" not in client.defaults
        assert client.get(HEALTH_PATH).status_code == 200


@db
class TestWhatItDoesNotPublish:
    """A health endpoint is the standard place for a deployment to leak. The
    driver's own error for a refused connection carries the database name, the
    user and the host."""

    def test_the_healthy_body_is_one_word(self, client) -> None:
        assert client.get(HEALTH_PATH).content.strip() == b"ok"

    def test_the_failing_body_says_nothing_about_why(self, client, monkeypatch) -> None:
        break_the_connection(monkeypatch)
        body = client.get(HEALTH_PATH).content.decode()

        assert body.strip() == "degraded"
        for leaked in ("Boom", "connection refused", "Traceback", "routemaker"):
            assert leaked not in body

    def test_neither_body_names_the_admin_path(self, client, monkeypatch) -> None:
        from django.conf import settings

        prefix = settings.ADMIN_PATH.strip("/")
        assert prefix not in client.get(HEALTH_PATH).content.decode()
        break_the_connection(monkeypatch)
        assert prefix not in client.get(HEALTH_PATH).content.decode()


@db
class TestWhatItCosts:
    """The only unauthenticated route in the deployment, and therefore the only
    one an anonymous flood can aim at. Its cost has to be a constant that does
    not grow with any table."""

    def test_it_sets_no_session_cookie(self, client) -> None:
        """A cookie per probe would be a session row per probe, from an
        unauthenticated caller, on a timer."""
        response = client.get(HEALTH_PATH)
        assert "sessionid" not in response.cookies
        assert not response.cookies

    def test_it_creates_no_session_row(self, client) -> None:
        from core.models import Session

        before = Session.objects.count()
        client.get(HEALTH_PATH)
        client.get(HEALTH_PATH)
        assert Session.objects.count() == before

    def test_it_issues_exactly_one_query(self, client, django_assert_num_queries) -> None:
        """`SELECT 1` and nothing else - no model query, no migration check, no
        count. Reaching for any of those would turn the probe into an
        amplifier."""
        with django_assert_num_queries(1):
            client.get(HEALTH_PATH)

    def test_it_forbids_caching(self, client) -> None:
        """The answer is a statement about this instant. A proxy holding the
        last 200 for even a few seconds reports a database that has since gone
        as healthy, which is the window the probe exists to close."""
        cache_control = client.get(HEALTH_PATH)["Cache-Control"]
        assert "no-cache" in cache_control
        assert "max-age=0" in cache_control


@db
class TestWhatItRefuses:
    def test_a_post_is_not_a_health_check(self, client) -> None:
        assert client.post(HEALTH_PATH).status_code == 405

    def test_head_works_because_healthcheckers_use_it(self, client) -> None:
        assert client.head(HEALTH_PATH).status_code == 200
