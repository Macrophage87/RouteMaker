"""The operations page: what has stopped running, and what died trying.

The plan puts two things on an admin page - "failed jobs appear on an admin page
and alert after the final retry", and the alert list whose every entry is "task
X has not succeeded in Y" - and neither had a surface. `stale_tasks` had no
caller at all: the alert the run rows exist for was computed by nothing and
displayed nowhere, so a worker that stopped a week ago produced exactly the
silence the run table was introduced to break.

This is the smallest thing that makes an operator able to see it. It is one
read-only page, gated to instance admins the same way the audit log is, and it
computes nothing of its own: it renders `core.runs.stale_task_details` and
`core.runs.failed_jobs`, which is what `manage.py check_operations` reads too,
so the page and the external monitor cannot disagree about what is broken.

It is registered against `ScheduledRun` rather than added to the admin site's
own URLs because that is what puts it in the admin index, under a heading an
operator can find without being told a path, and what makes the site's
`has_permission` and its `admin_view` wrapper - the 404 for anyone unadmitted -
apply to it without a second implementation of either. The changelist *is* the
page: a filterable list of every run row ever written is not the question being
asked here, which is "is anything broken right now".
"""

from __future__ import annotations

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.template.response import TemplateResponse

from .admin import site
from .models import ScheduledRun
from .runs import STALE_AFTER, failed_jobs, stale_task_details, wedged_jobs

# How many of each list the page shows. Enough to see a pattern, few enough that
# the page stays one screen.
RECENT_RUNS = 25
RECENT_FAILURES = 25


@admin.register(ScheduledRun, site=site)
class ScheduledRunAdmin(admin.ModelAdmin):
    """Read-only, instance-admin only, and rendered as a report.

    Instance-admin only for the same reason the audit log is: it names the
    deployment's internals - which jobs ran, which failed and with what error -
    and a guild admin has no business in it. Read-only to everyone including an
    instance admin, because these rows are the evidence for an alert, and an
    admin that can edit them can silence it by hand.
    """

    def has_view_permission(self, request, obj=None) -> bool:
        return bool(getattr(request.user, "is_instance_admin", False))

    def has_module_permission(self, request) -> bool:
        return self.has_view_permission(request)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    def changelist_view(self, request, extra_context=None):
        """The report. The permission check is repeated rather than inherited:
        Django's own changelist_view is what normally raises PermissionDenied,
        and this replaces it."""
        if not self.has_view_permission(request):
            raise PermissionDenied
        context = {
            **site.each_context(request),
            "title": "Operations",
            "stale": stale_task_details(),
            "windows": sorted(STALE_AFTER.items()),
            # A job still `doing` long past its own budget. It is on this page
            # for the same reason it is in `check_operations`: a worker killed
            # mid-job never writes `failed`, so the failed-jobs list below is
            # empty for exactly the outage that has stopped the queue.
            "wedged_jobs": wedged_jobs(),
            "failed_jobs": failed_jobs(RECENT_FAILURES),
            "recent_runs": ScheduledRun.objects.order_by("-started_at")[:RECENT_RUNS],
            **(extra_context or {}),
        }
        return TemplateResponse(request, "admin/operations.html", context)
