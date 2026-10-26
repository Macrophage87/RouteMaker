# A Featured routes post's route sent by an assistant as a line to follow was kept with no plan
# link and no file, so Open in RouteMaker opened an empty app (the owner, 2026-10-25: "It just
# opens RouteMaker"). core.route_posts.freeze_route now keeps both; this mends the posts' routes
# kept before, as freeze_route would have kept them.
from html import escape

from django.db import migrations


def _hash(inputs, line, answer):
    points = [p for p in (inputs.get("points") or []) if isinstance(p, list) and len(p) >= 2]
    if len(points) < 2:
        points = [line[0], line[-1]]
    hash_ = "p=" + ";".join(f"{float(p[0]):.5f},{float(p[1]):.5f}" for p in points)
    preset = str(inputs.get("preset") or (answer or {}).get("preset") or "")
    return f"{hash_}&preset={preset}" if preset else hash_


def _gpx(title, line):
    name = escape(title, quote=True)
    points = []
    for p in line:
        ele = p[2] if len(p) > 2 and isinstance(p[2], int | float) else None
        at = f'lat="{float(p[1]):.6f}" lon="{float(p[0]):.6f}"'
        points.append(
            f"      <trkpt {at}><ele>{float(ele):.1f}</ele></trkpt>"
            if ele is not None
            else f"      <trkpt {at}/>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1" creator="RouteMaker">\n'
        "  <metadata>\n"
        f"    <name>{name}</name>\n"
        "    <desc>Route data: © OpenStreetMap contributors, ODbL.</desc>\n"
        '    <copyright author="OpenStreetMap contributors">\n'
        "      <license>https://opendatacommons.org/licenses/odbl/1-0/</license>\n"
        "    </copyright>\n"
        '    <link href="https://www.openstreetmap.org/copyright">\n'
        "      <text>© OpenStreetMap contributors</text>\n"
        "    </link>\n"
        "  </metadata>\n"
        "  <trk>\n"
        f"    <name>{name}</name>\n"
        "    <type>cycling</type>\n"
        "    <trkseg>\n" + "\n".join(points) + "\n    </trkseg>\n"
        "  </trk>\n"
        "</gpx>\n"
    )


def mend(apps, schema_editor):
    RoutePost = apps.get_model("core", "RoutePost")
    for post in RoutePost.objects.select_related("route").exclude(route=None):
        row = post.route
        line = row.line or []
        if len(line) < 2:
            continue
        fields = []
        inputs = dict(row.inputs or {})
        if not isinstance(inputs.get("hash"), str):
            inputs["hash"] = _hash(inputs, line, row.answer)
            row.inputs = inputs
            fields.append("inputs")
        if row.source == "gpx" and not row.gpx:
            row.gpx = _gpx(post.title, line)
            fields.append("gpx")
        if fields:
            row.save(update_fields=fields)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0046_remove_assistant_key"),
    ]

    operations = [
        migrations.RunPython(mend, migrations.RunPython.noop),
    ]
