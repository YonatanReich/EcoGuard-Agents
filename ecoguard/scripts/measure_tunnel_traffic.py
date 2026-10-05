"""How much one open dashboard sends through a tunnel, before a demo goes live.

Replays a browser session against the address the tunnel serves - the page
and its assets once, then each poller at its real interval - with gzip and
ETag revalidation exactly as a browser does them, and counts the bytes as they
cross the wire. A free Pinggy tunnel closed after 7.4 MB in 30 minutes, so the
answer that matters is the projected MB per 30 minutes.

    python -m ecoguard.scripts.measure_tunnel_traffic --minutes 3
    python -m ecoguard.scripts.measure_tunnel_traffic --base http://localhost:4173

Run it while a scenario is on screen; an empty feed measures nothing.
Point it at the production preview (`npm run build && npx vite preview`, port
4173) rather than the dev server: dev serves the app as hundreds of unbundled
modules, which this script does not follow and a tunnel should never carry.
"""

from __future__ import annotations

import argparse
import re
import time

import requests

# What the dashboard polls, and how often (frontend/src/pages/Dashboard.tsx,
# components/ScenarioControl.tsx). The System page (1.5 s) is not part of the
# demo screen; pass --system to include it.
POLLERS = {"/api/events?limit=200": 15.0, "/api/scenario/status": 4.0}
SYSTEM_POLLER = {"/api/system/actors": 1.5}


def _wire_bytes(session: requests.Session, url: str, etags: dict[str, str]) -> tuple[int, int]:
    """(status, bytes on the wire) for one conditional, gzip-accepting GET."""
    headers = {"Accept-Encoding": "gzip"}
    if url in etags:
        headers["If-None-Match"] = etags[url]
    response = session.get(url, headers=headers, stream=True, timeout=30)
    body = response.raw.read(decode_content=False)
    if response.headers.get("etag"):
        etags[url] = response.headers["etag"]
    header_bytes = sum(len(k) + len(v) + 4 for k, v in response.headers.items()) + 20
    return response.status_code, len(body) + header_bytes


def main() -> int:
    """Measure, then print the projection."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="http://localhost:5173")
    parser.add_argument("--minutes", type=float, default=3.0)
    parser.add_argument("--system", action="store_true", help="also poll the System page")
    args = parser.parse_args()

    session = requests.Session()
    etags: dict[str, str] = {}

    _, page = _wire_bytes(session, f"{args.base}/", etags)
    index = session.get(f"{args.base}/", timeout=30).text
    assets = set(re.findall(r'(?:src|href)="(/[^"]+\.(?:js|css))"', index))
    page += sum(_wire_bytes(session, f"{args.base}{path}", etags)[1] for path in assets)
    print(f"page load: {page / 1024:,.0f} KB ({len(assets)} assets)")

    pollers = {**POLLERS, **(SYSTEM_POLLER if args.system else {})}
    due = {path: 0.0 for path in pollers}
    totals = {path: [0, 0, 0] for path in pollers}  # bytes, 200s, 304s
    start = time.monotonic()
    end = start + args.minutes * 60
    while time.monotonic() < end:
        now = time.monotonic() - start
        for path, interval in pollers.items():
            if now >= due[path]:
                status, size = _wire_bytes(session, f"{args.base}{path}", etags)
                totals[path][0] += size
                totals[path][1 if status == 200 else 2] += 1
                due[path] = now + interval
        time.sleep(0.25)

    elapsed_min = (time.monotonic() - start) / 60
    polled = sum(t[0] for t in totals.values())
    for path, (size, full, unchanged) in totals.items():
        print(f"{path:28} {size / 1024:8,.0f} KB  {full} full, {unchanged} unchanged (304)")
    per_30 = polled / elapsed_min * 30 / 1024 / 1024
    print(f"\npolling: {per_30:.2f} MB per 30 minutes, plus {page / 1024 / 1024:.2f} MB per page load")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
