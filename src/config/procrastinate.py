"""The worker app and its periodic tasks.

Procrastinate runs jobs in PostgreSQL rather than in a broker, which is why
there is no Redis in the stack: one durable store, one backup, one restore.

Every periodic task here writes a success row that an alert reads, rather than
relying on the absence of an error. A job that never ran produces no error at
all, and the failure modes that matter most here - a rebuild that stopped
running, a backup that stopped being taken - are exactly that shape.
"""

from __future__ import annotations

import os

from procrastinate import App, PsycopgConnector

app = App(
    connector=PsycopgConnector(
        kwargs={
            "host": os.environ.get("PGHOST", "127.0.0.1"),
            "dbname": os.environ.get("PGDATABASE", "routemaker"),
            "user": os.environ.get("PGUSER", "routemaker"),
            "password": os.environ.get("PGPASSWORD", "routemaker"),
        }
    )
)

# Cron schedules. The rebuild runs in a low-traffic window because it takes half
# the host's cores and widens the latency alerts while it does.
WEEKLY_REBUILD_CRON = "0 8 * * 2"  # Tuesday 08:00 UTC, early morning local
NIGHTLY_BACKUP_CRON = "0 7 * * *"
MEMBERSHIP_SWEEP_CRON = "0 */6 * * *"

# How long each may run before it is considered stuck. The rebuild's ceiling is
# longer than its expected duration but shorter than the eight days after which
# the "no rebuild completed" alert fires, so a hung rebuild is caught by its own
# timeout rather than by the weekly alarm.
REBUILD_TIMEOUT_S = 6 * 60 * 60
SWEEP_TIMEOUT_S = 30 * 60
