# Every ride link carries a key (the owner, 2026-10-29: "All rides should have a key."): a
# Featured routes post of a Group or Mass Ride kept before now has a link without one.
# core.route_posts.freeze_route now gives each such post its own key, kept in its `stats`
# ("ride_key") and written into its route's link as `k=`; this gives the posts kept before theirs,
# as freeze_route would have. Data only; going back leaves the keys in place.
import base64
import re
import secrets

from django.db import migrations

RIDE_LINK_TYPES = ("mass-ride", "group-ride")
KEY_RE = re.compile(r"[A-Za-z0-9_-]{22}|[A-Za-z0-9_-]{43}")


def _with_key(fragment, key):
    lead = "#" if fragment.startswith("#") else ""
    params = [p for p in fragment.lstrip("#").split("&") if p and not p.startswith("k=")]
    params.append(f"k={key}")
    return lead + "&".join(params)


def give_keys(apps, schema_editor):
    RoutePost = apps.get_model("core", "RoutePost")
    for post in RoutePost.objects.select_related("route").exclude(route=None):
        row = post.route
        inputs = dict(row.inputs or {})
        stats = dict(post.stats or {})
        preset = str(inputs.get("preset") or stats.get("preset") or "")
        fragment = inputs.get("hash")
        if preset not in RIDE_LINK_TYPES or not isinstance(fragment, str):
            continue
        key = stats.get("ride_key")
        if not (isinstance(key, str) and KEY_RE.fullmatch(key)):
            key = base64.urlsafe_b64encode(secrets.token_bytes(16)).rstrip(b"=").decode("ascii")
        stats["ride_key"] = key
        inputs["hash"] = _with_key(fragment, key)
        row.inputs = inputs
        row.save(update_fields=["inputs"])
        post.stats = stats
        post.save(update_fields=["stats"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0052_report311_log_days"),
    ]

    operations = [
        migrations.RunPython(give_keys, migrations.RunPython.noop),
    ]
