#!/usr/bin/env python3
# ruff: noqa: E501 - the README template rows run long
"""Download one ArcGIS layer, once, and record where it came from.

The owner approves each agency layer download individually (OWNER-DECISIONS
151-159), so this refuses to run when its output file already exists: a second
download of an approved layer needs a second approval and a new directory. It
pages a layer at its `maxRecordCount` (`resultOffset`/`resultRecordCount`,
ordered by an id field so the pages do not overlap), writes the features
unedited as one GeoJSON FeatureCollection in WGS 84, and writes a README beside
it recording the source URL, the item id, the item's licence text verbatim, the
retrieval time (UTC), the feature count the service reported and the sha256 of
the file. The item *metadata* is read once for the licence; it is not data.

    python scripts/fetch_agency_layer.py \
        --slug dc-roadway-block --item 6fcba8618ae744949630da3ea12d90eb \
        --layer https://maps2.dcgis.dc.gov/.../MapServer/163 \
        --out-dir ~/rmdata/datasets --credit "DDOT / DC GIS"

Standard library only, so it runs on the host without the virtualenv.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ITEM_BASE = "https://www.arcgis.com/sharing/rest/content/items"
USER_AGENT = "RouteMaker-data-fetch/1.0 (bike route planner)"
RETRIES = 3


def _get(url: str, params: dict[str, str] | None = None) -> dict:
    query = urllib.parse.urlencode(params or {})
    full = f"{url}?{query}" if query else url
    last: Exception | None = None
    for attempt in range(RETRIES):
        try:
            request = urllib.request.Request(full, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=180) as response:
                body = json.loads(response.read())
            if isinstance(body, dict) and "error" in body:
                raise RuntimeError(f"{url}: {body['error']}")
            return body
        except Exception as error:  # noqa: BLE001 - retried, then raised
            last = error
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"giving up on {url}: {last}")


def strip_html(text: str | None) -> str:
    """An item's licence text as plain text. The HTML is kept in the README too."""
    if not text:
        return ""
    plain = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", html.unescape(plain)).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--slug", required=True)
    parser.add_argument("--item", required=True, help="the ArcGIS item id")
    parser.add_argument("--layer", required=True, help="the layer URL, ending in its id")
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--credit", required=True)
    parser.add_argument("--order-by", default="OBJECTID")
    parser.add_argument("--where", default="1=1")
    parser.add_argument("--note", default="")
    # Where an item's metadata is read from; a test points it at a local server.
    parser.add_argument("--item-base", default=ITEM_BASE, help=argparse.SUPPRESS)
    args = parser.parse_args()

    directory = args.out_dir / args.slug
    target = directory / f"{args.slug}.geojson"
    if target.exists():
        print(f"{target} exists: this layer was already downloaded once", file=sys.stderr)
        return 2
    directory.mkdir(parents=True, exist_ok=True)

    item = _get(f"{args.item_base}/{args.item}", {"f": "json"})
    meta = _get(args.layer, {"f": "json"})
    expected = _get(
        f"{args.layer}/query", {"where": args.where, "returnCountOnly": "true", "f": "json"}
    )["count"]
    page = int(meta.get("maxRecordCount") or 1000)
    retrieved = datetime.now(UTC)

    temp = target.with_suffix(".part")
    written = 0
    pages = 0
    with temp.open("w", encoding="utf-8") as out:
        out.write('{"type":"FeatureCollection","features":[')
        offset = 0
        while True:
            body = _get(
                f"{args.layer}/query",
                {
                    "where": args.where,
                    "outFields": "*",
                    "outSR": "4326",
                    "orderByFields": args.order_by,
                    "resultOffset": str(offset),
                    "resultRecordCount": str(page),
                    "f": "geojson",
                },
            )
            features = body.get("features", [])
            for feature in features:
                out.write(("," if written else "") + json.dumps(feature, separators=(",", ":")))
                written += 1
            pages += 1
            print(f"page {pages}: offset {offset}, {len(features)} features", flush=True)
            if not features or written >= expected:
                break
            offset += len(features)
        out.write("]}")
    temp.replace(target)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()

    licence_html = item.get("licenseInfo") or ""
    modified = datetime.fromtimestamp(item.get("modified", 0) / 1000, UTC)
    readme = f"""# {item.get("title")}

| | |
| --- | --- |
| Stored file | `{target.name}` ({target.stat().st_size:,} bytes) |
| sha256 | `{digest}` |
| Retrieved (UTC) | {retrieved:%Y-%m-%d %H:%M:%S} |
| Source layer | <{args.layer}> |
| ArcGIS item | `{args.item}`, <https://www.arcgis.com/home/item.html?id={args.item}> (modified {modified:%Y-%m-%d}) |
| Query | `where={args.where}`, `outFields=*`, `outSR=4326`, `f=geojson`, ordered by `{args.order_by}`, pages of {page} |
| Features | {written:,} stored; the service reported {expected:,} ({pages} pages) |
| Credit (item `accessInformation`) | {item.get("accessInformation") or "(none)"} |
| Required credit line | {args.credit} |

Licence, verbatim from the item's `licenseInfo` as plain text:

> {strip_html(licence_html) or "(the item carries no licence text)"}

The raw `licenseInfo` HTML, for the record:

```html
{licence_html}
```

{args.note}

The file is exactly what the service returned, one download, not edited.
"""
    (directory / "README.md").write_text(readme, encoding="utf-8")
    print(f"{target}: {written} features, sha256 {digest}")
    return 0 if written == expected else 3


if __name__ == "__main__":
    sys.exit(main())
