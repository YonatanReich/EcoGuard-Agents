"""Fetching the ambulance service region map, once, into the repository."""

import math
from pathlib import Path

import requests


WMS_URL = "https://www.govmap.gov.il/api/geoserver/ows/public/"

# The missing "t" is govmap's own typo — "…districts" is LayerNotDefined.
LAYER = "govmap:layer_mada_districs"

# govmap's WAF answers 403 to any User-Agent not starting with "Mozilla/": the
# requests default and a plain "EcoGuard/1.0" are both refused. This is the
# shortest string that gets through while still saying who is calling.
USER_AGENT = "Mozilla/5.0 (compatible; EcoGuard/1.0)"

# Israel plus a margin, in degrees. Only used to derive the Web Mercator box
# below, which is what both the request and the map layer are positioned by.
WEST, SOUTH, EAST, NORTH = 34.15, 29.40, 35.95, 33.45

# 2048 px across ~200 km is about 98 m/px, at roughly half a megabyte. Doubling
# it to 49 m/px costs 1.4 MB, which is a lot of bundle for boundaries drawn as
# lines a few hundred metres wide anyway.
WIDTH = 2048

OUTPUT = Path(__file__).resolve().parents[1] / "data" / "reference" / "mda_districts.png"


def to_web_mercator(lon: float, lat: float) -> tuple[float, float]:
    """Project a lon/lat degree pair to EPSG:3857 metres."""
    radius = 20037508.342789244
    x = lon * radius / 180.0
    y = math.log(math.tan((90.0 + lat) * math.pi / 360.0)) * radius / math.pi
    return x, y


def fetch() -> bytes:
    """Render the whole country in one GetMap and return the PNG bytes.

    Raises:
        RuntimeError: when govmap answers with anything but an image. It
            reports a bad request as HTTP 200 with an XML ServiceException, so
            the status code alone does not settle it.
    """
    west, south = to_web_mercator(WEST, SOUTH)
    east, north = to_web_mercator(EAST, NORTH)
    height = round(WIDTH * (north - south) / (east - west))

    response = requests.get(
        WMS_URL,
        params={
            "SERVICE": "WMS",
            "VERSION": "1.3.0",
            "REQUEST": "GetMap",
            "LAYERS": LAYER,
            "FORMAT": "image/png",
            "TRANSPARENT": "TRUE",
            "CRS": "EPSG:3857",
            "WIDTH": WIDTH,
            "HEIGHT": height,
            "BBOX": f"{west},{south},{east},{north}",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=120,
    )

    if not response.headers.get("Content-Type", "").startswith("image/"):
        raise RuntimeError(
            f"govmap returned no image ({response.status_code}): "
            f"{response.text[:300]}"
        )

    return response.content


def main() -> None:
    """Fetch the ambulance region map from the command line."""
    png = fetch()
    OUTPUT.write_bytes(png)
    print(f"Wrote {len(png):,} bytes to {OUTPUT}")


if __name__ == "__main__":
    main()
