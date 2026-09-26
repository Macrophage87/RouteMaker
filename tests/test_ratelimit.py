"""The per-client limiter the anonymous routing API and the stress tiles share.

PLAN, Moderation and abuse limits: limits are "counted in a PostgreSQL
fixed-window table rather than in process memory, since gunicorn runs a worker
per core and in-memory counters would multiply every stated limit by the worker
count". The concurrency test below is the one that holds that claim: many
connections at once, one budget between them.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import timedelta

import pytest
from django.db import connection, connections
from django.http import HttpResponse
from django.test import RequestFactory, override_settings

from core import ratelimit
from core.models import RateLimitWindow

db = pytest.mark.django_db(transaction=True)

LIMIT = ratelimit.Limit(scope="test", requests=5, window_s=60)


def request_from(remote: str = "203.0.113.9", forwarded: str | None = None):
    extra = {"REMOTE_ADDR": remote}
    if forwarded is not None:
        extra["HTTP_X_FORWARDED_FOR"] = forwarded
    return RequestFactory().post("/x", **extra)


class TestClientAddress:
    def test_the_address_caddy_appended_is_the_client(self) -> None:
        """Caddy, trusting no upstream proxy, replaces any X-Forwarded-For the
        client sent with the peer it saw, so the last entry is the one that
        cannot be forged from outside."""
        assert ratelimit.client_address(request_from(forwarded="198.51.100.7")) == "198.51.100.7"

    def test_a_forged_leading_entry_does_not_choose_the_bucket(self) -> None:
        forged = request_from(forwarded="192.0.2.1, 198.51.100.7")
        assert ratelimit.client_address(forged) == "198.51.100.7"

    def test_without_a_proxy_header_the_peer_is_the_client(self) -> None:
        assert ratelimit.client_address(request_from(remote="203.0.113.9")) == "203.0.113.9"

    def test_a_malformed_header_falls_back_to_the_peer(self) -> None:
        request = request_from(remote="203.0.113.9", forwarded="not-an-address")
        assert ratelimit.client_address(request) == "203.0.113.9"

    def test_one_ipv6_subscriber_is_one_client(self) -> None:
        """A single subscriber is routinely handed a whole /64; counting per
        address would give one person 2**64 budgets."""
        a = ratelimit.client_address(request_from(forwarded="2001:db8:1:2::1"))
        b = ratelimit.client_address(request_from(forwarded="2001:db8:1:2:ffff::9"))
        c = ratelimit.client_address(request_from(forwarded="2001:db8:1:3::1"))
        assert a == b
        assert a != c

    def test_an_ipv4_mapped_address_is_the_ipv4_client(self) -> None:
        mapped = ratelimit.client_address(request_from(forwarded="::ffff:198.51.100.7"))
        assert mapped == ratelimit.client_address(request_from(forwarded="198.51.100.7"))


class TestClientKey:
    def test_the_stored_key_is_not_the_address(self) -> None:
        """PLAN, Privacy and retention: client addresses are never shown in any
        UI and are dropped on a schedule. Keeping a keyed hash rather than the
        address means a dump of this table is not a list of who used the site."""
        key = ratelimit.client_key("198.51.100.7")
        assert "198.51.100.7" not in key
        assert key != "198.51.100.7"
        # A keyed digest: the same width whatever the address.
        assert len(key) == len(ratelimit.client_key("2001:db8:1:2::/64"))

    def test_it_is_keyed_by_the_deployments_secret(self) -> None:
        """Unkeyed, the digest of an IPv4 address is reversed by hashing all
        four billion of them; keyed, only the holder of SECRET_KEY can."""
        key = ratelimit.client_key("198.51.100.7")
        with override_settings(SECRET_KEY="another-deployments-secret"):
            assert ratelimit.client_key("198.51.100.7") != key
        assert key != hashlib.sha256(b"198.51.100.7").hexdigest()

    def test_it_is_stable_and_distinguishes_clients(self) -> None:
        assert ratelimit.client_key("198.51.100.7") == ratelimit.client_key("198.51.100.7")
        assert ratelimit.client_key("198.51.100.7") != ratelimit.client_key("198.51.100.8")

    def test_it_fits_the_column(self) -> None:
        width = RateLimitWindow._meta.get_field("client").max_length
        assert len(ratelimit.client_key("2001:db8:1:2::/64")) <= width


@db
class TestFixedWindow:
    def test_the_budget_is_allowed_and_the_next_request_refused(self) -> None:
        decisions = [ratelimit.hit(LIMIT, "client-a") for _ in range(LIMIT.requests + 1)]
        assert all(d.allowed for d in decisions[:-1])
        assert not decisions[-1].allowed

    def test_a_refusal_says_when_to_come_back(self) -> None:
        for _ in range(LIMIT.requests):
            ratelimit.hit(LIMIT, "client-a")
        refused = ratelimit.hit(LIMIT, "client-a")
        assert 1 <= refused.retry_after_s <= LIMIT.window_s

    def test_clients_do_not_share_a_budget(self) -> None:
        for _ in range(LIMIT.requests + 1):
            ratelimit.hit(LIMIT, "client-a")
        assert ratelimit.hit(LIMIT, "client-b").allowed

    def test_scopes_do_not_share_a_budget(self) -> None:
        """The tiles and the router are limited separately: a map pan fetches
        dozens of tiles and must not spend the routing budget."""
        for _ in range(LIMIT.requests + 1):
            ratelimit.hit(LIMIT, "client-a")
        other = ratelimit.Limit(scope="other", requests=LIMIT.requests, window_s=LIMIT.window_s)
        assert ratelimit.hit(other, "client-a").allowed

    def test_the_next_window_starts_a_fresh_budget(self) -> None:
        for _ in range(LIMIT.requests + 1):
            ratelimit.hit(LIMIT, "client-a")
        row = RateLimitWindow.objects.get(scope=LIMIT.scope, client="client-a")
        row.window_start -= timedelta(seconds=LIMIT.window_s)
        row.save(update_fields=["window_start"])
        assert ratelimit.hit(LIMIT, "client-a").allowed

    def test_the_fresh_budget_is_a_budget(self) -> None:
        """The restarted window must bind like the first one, not reset on
        every request after it."""
        for _ in range(LIMIT.requests + 1):
            ratelimit.hit(LIMIT, "client-a")
        RateLimitWindow.objects.filter(client="client-a").update(
            window_start=RateLimitWindow.objects.get(client="client-a").window_start
            - timedelta(seconds=LIMIT.window_s)
        )
        decisions = [ratelimit.hit(LIMIT, "client-a") for _ in range(LIMIT.requests + 1)]
        assert [d.allowed for d in decisions] == [True] * LIMIT.requests + [False]

    def test_one_row_per_client_however_many_windows_pass(self) -> None:
        """The row is reused, so the table grows with clients, not with time."""
        for _ in range(3):
            ratelimit.hit(LIMIT, "client-a")
            RateLimitWindow.objects.filter(client="client-a").update(
                window_start=RateLimitWindow.objects.get(client="client-a").window_start
                - timedelta(seconds=LIMIT.window_s)
            )
        assert RateLimitWindow.objects.filter(scope=LIMIT.scope, client="client-a").count() == 1

    def test_the_budget_holds_across_concurrent_connections(self) -> None:
        """Each thread has its own database connection, which is what a
        gunicorn worker per core amounts to."""
        # Three times the budget: enough to contend, and few enough connections
        # that a suite running beside other suites on the same server does not
        # meet max_connections - the review's suspected flake. A thread that
        # fails says why instead of shortening `allowed` silently.
        attempts = 3 * LIMIT.requests
        allowed = []
        errors = []
        start = threading.Barrier(attempts, timeout=30)

        def one() -> None:
            try:
                start.wait()
                allowed.append(ratelimit.hit(LIMIT, "client-a").allowed)
            except Exception as error:  # noqa: BLE001 - reported below
                errors.append(repr(error))
            finally:
                connections.close_all()

        threads = [threading.Thread(target=one) for _ in range(attempts)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == []
        assert len(allowed) == attempts
        assert sum(allowed) == LIMIT.requests

    def test_retry_after_is_the_time_left_in_the_window(self) -> None:
        """Not only somewhere in range: the seconds from now to the window's
        end, read off the database clock."""
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT to_timestamp(floor(extract(epoch FROM clock_timestamp()) / 60) * 60), "
                "clock_timestamp()"
            )
            window_start, now = cursor.fetchone()
        expected = (window_start + timedelta(seconds=LIMIT.window_s) - now).total_seconds()
        if expected < 3:
            pytest.skip("too close to a window boundary to measure")
        for _ in range(LIMIT.requests):
            ratelimit.hit(LIMIT, "client-a")
        refused = ratelimit.hit(LIMIT, "client-a")
        assert abs(refused.retry_after_s - expected) <= 2

    def test_retry_after_is_never_zero_at_the_end_of_a_window(self, monkeypatch) -> None:
        """At the last instant of a window the time left rounds to nothing,
        and "Retry-After: 0" invites an immediate retry into the same refusal."""
        for _ in range(LIMIT.requests):
            ratelimit.hit(LIMIT, "client-a")

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, *args):
                pass

            def fetchone(self):
                return (LIMIT.requests + 1, 0)

        monkeypatch.setattr(ratelimit.connection, "cursor", lambda: Cursor())
        assert ratelimit.hit(LIMIT, "client-a").retry_after_s == 1


@db
class TestRetention:
    def test_stale_rows_are_purged_and_current_ones_kept(self) -> None:
        ratelimit.hit(LIMIT, "stale")
        ratelimit.hit(LIMIT, "fresh")
        RateLimitWindow.objects.filter(client="stale").update(
            window_start=RateLimitWindow.objects.get(client="stale").window_start
            - ratelimit.RETENTION
            - timedelta(seconds=1)
        )
        ratelimit.hit(ratelimit.Limit(scope="other", requests=5, window_s=60), "stale")
        RateLimitWindow.objects.filter(client="stale").update(
            window_start=RateLimitWindow.objects.filter(client="stale").first().window_start
            - ratelimit.RETENTION
            - timedelta(seconds=1)
        )
        assert ratelimit.purge_expired() == 2
        assert set(RateLimitWindow.objects.values_list("client", flat=True)) == {"fresh"}

    def test_the_retention_is_inside_the_plans_ceiling(self) -> None:
        """PLAN, Privacy and retention: client addresses are kept at most 30
        days in the rate-limit store."""
        assert timedelta(0) < ratelimit.RETENTION <= timedelta(days=30)

    def test_the_worker_sweep_purges_on_its_schedule(self) -> None:
        """A quiet deployment makes no requests, so the purge cannot ride on
        them; it rides on the six-hourly membership sweep, as the session and
        membership purges do."""
        from config.procrastinate import app
        from core.models import ScheduledRun

        ratelimit.hit(LIMIT, "stale")
        ratelimit.hit(LIMIT, "fresh")
        RateLimitWindow.objects.filter(client="stale").update(
            window_start=RateLimitWindow.objects.get(client="stale").window_start
            - ratelimit.RETENTION
            - timedelta(seconds=1)
        )
        app.tasks["membership_sweep"].func(timestamp=0)
        assert set(RateLimitWindow.objects.values_list("client", flat=True)) == {"fresh"}
        detail = ScheduledRun.objects.get(task="membership_sweep").detail
        assert "1 idle rate-limit rows" in detail

    def test_a_request_does_not_purge(self) -> None:
        """The purge is the sweep's; a hit is one upsert."""
        ratelimit.hit(LIMIT, "stale")
        RateLimitWindow.objects.filter(client="stale").update(
            window_start=RateLimitWindow.objects.get(client="stale").window_start
            - ratelimit.RETENTION
            - timedelta(seconds=1)
        )
        for _ in range(50):
            ratelimit.hit(LIMIT, "fresh")
        assert RateLimitWindow.objects.filter(client="stale").exists()

    def test_the_table_stays_out_of_the_nightly_dump(self) -> None:
        """Backups outlive the retention window, so a table of client keys in
        them would outlive the rule too."""
        from config.procrastinate import BACKUP_EXCLUDED_TABLES

        assert RateLimitWindow._meta.db_table in BACKUP_EXCLUDED_TABLES


@db
class TestDecorator:
    def view(self):
        @ratelimit.rate_limited(LIMIT)
        def ok(request):
            return HttpResponse("ok")

        return ok

    def test_a_refusal_is_429_with_retry_after(self) -> None:
        view = self.view()
        for _ in range(LIMIT.requests):
            assert view(request_from()).status_code == 200
        refused = view(request_from())
        assert refused.status_code == 429
        assert 1 <= int(refused["Retry-After"]) <= LIMIT.window_s
        assert "error" in json.loads(refused.content)

    def test_a_refused_request_does_not_reach_the_view(self) -> None:
        calls = []

        @ratelimit.rate_limited(LIMIT)
        def counting(request):
            calls.append(1)
            return HttpResponse("ok")

        for _ in range(LIMIT.requests + 3):
            counting(request_from())
        assert len(calls) == LIMIT.requests

    def test_the_bucket_is_the_forwarded_client_not_the_proxy(self) -> None:
        """Behind Caddy every request's peer is Caddy. Keyed on the peer, one
        busy client would lock out everyone."""
        view = self.view()
        for _ in range(LIMIT.requests + 1):
            view(request_from(remote="172.18.0.2", forwarded="198.51.100.7"))
        assert view(request_from(remote="172.18.0.2", forwarded="198.51.100.8")).status_code == 200

    def test_nothing_about_the_client_is_stored_in_the_clear(self) -> None:
        self.view()(request_from(forwarded="198.51.100.7"))
        with connection.cursor() as cursor:
            cursor.execute("SELECT scope, client FROM rate_limit_window")
            rows = cursor.fetchall()
        assert rows
        assert not any("198.51.100.7" in client for _scope, client in rows)
