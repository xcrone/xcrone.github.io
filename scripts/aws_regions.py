#!/usr/bin/env python3
"""Scrape AWS regions into aws-regions/data.json.

Region names, AZ counts, launch years and coordinates come from the AWS
global infrastructure page. Region codes on that page are unreliable
(e.g. "ap-southeast-7x"), so codes come from botocore's endpoints.json,
matched by region name.
"""
import datetime
import json
import os
import re
import sys
import unicodedata
import urllib.request

PAGE_URL = "https://aws.amazon.com/about-aws/global-infrastructure/regions_az/"
BOTOCORE_URL = "https://raw.githubusercontent.com/boto/botocore/develop/botocore/data/endpoints.json"
OUTPUT = os.path.join(os.path.dirname(__file__), "..", "aws-regions", "data.json")
MIN_REGIONS = 30

CONTINENTS_RE = re.compile(r'"continents":"((?:[^"\\]|\\.)*)"')
PAREN_RE = re.compile(r"\(([^)]*)\)")


class ScrapeError(Exception):
    pass


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; xcrone-aws-regions/1.0)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def extract_regions(html):
    """Return the page's regions as flat dicts with a `continent` key."""
    m = CONTINENTS_RE.search(html)
    if not m:
        raise ScrapeError("continents blob not found on page")
    continents = json.loads(json.loads('"' + m.group(1) + '"'))
    regions = []
    for continent in continents:
        for r in continent.get("regions", []):
            regions.append({**r, "id": r["id"].strip(), "name": r["name"].strip(), "continent": continent["name"].strip()})
    return regions


def load_botocore(json_text):
    """Return (code, description, partition) for commercial, China, GovCloud and sovereign partitions."""
    data = json.loads(json_text)
    return [
        (code, info.get("description", ""), p["partition"])
        for p in data["partitions"]
        if not p["partition"].startswith("aws-iso")
        for code, info in p["regions"].items()
    ]


def match_key(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"\bn\.\s*", "northern ", s.lower())
    return " ".join(s.split())


def paren_key(name):
    m = PAREN_RE.search(name)
    return match_key(m.group(1)) if m else None


def merge(page_regions, boto):
    by_name = {match_key(desc): (code, part) for code, desc, part in boto}
    by_paren = {}
    for code, desc, part in boto:
        by_paren.setdefault(paren_key(desc), []).append((code, part))

    out = []
    for r in page_regions:
        hit = by_name.get(match_key(r["name"]))
        if not hit:
            candidates = by_paren.get(paren_key(r["name"])) or []
            hit = candidates[0] if len(candidates) == 1 else None
        if hit:
            code, partition = hit
        elif r.get("available"):
            code, partition = r["id"], None
            print(f"warning: no botocore match for {r['name']!r}, using page id {code!r}", file=sys.stderr)
        else:
            code, partition = None, None
        launched = r.get("launched")
        out.append({
            "code": code,
            "name": r["name"],
            "continent": r["continent"],
            "partition": partition,
            "available": bool(r.get("available")),
            "availability_zones": r.get("availabilityZones"),
            "launched": int(launched) if launched else None,
            "lat": r.get("lat"),
            "lng": r.get("lng"),
        })
    out.sort(key=lambda r: (r["code"] is None, r["code"] or "", r["name"]))
    return out


def validate(regions, min_count=MIN_REGIONS):
    if len(regions) < min_count:
        raise ScrapeError(f"only {len(regions)} regions found, expected at least {min_count}")
    codes = [r["code"] for r in regions if r["code"]]
    dupes = sorted({c for c in codes if codes.count(c) > 1})
    if dupes:
        raise ScrapeError(f"duplicate region codes: {', '.join(dupes)}")


def write_output(path, regions, now=None):
    """Write the file; return False (and leave it untouched) if regions are unchanged."""
    try:
        with open(path, encoding="utf-8") as f:
            if json.load(f).get("regions") == regions:
                return False
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    now = now or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = {"source": PAGE_URL, "generated_at": now, "count": len(regions), "regions": regions}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return True


def main():
    try:
        regions = merge(extract_regions(fetch(PAGE_URL)), load_botocore(fetch(BOTOCORE_URL)))
        validate(regions)
    except ScrapeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    changed = write_output(os.path.normpath(OUTPUT), regions)
    print(f"{len(regions)} regions, {'updated' if changed else 'unchanged'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
