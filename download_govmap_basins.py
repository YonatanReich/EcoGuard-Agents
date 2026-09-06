import json
from pathlib import Path

import requests


WFS_URL = "https://open.govmap.gov.il/geoserver/opendata/wfs"
OUTPUT_FILE = Path("data/govmap_drainage_basins.geojson")
PAGE_SIZE = 1000


def download_drainage_basins():
    all_features = []
    start_index = 0
    first_response = None

    while True:
        params = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": "opendata:Nikuz",
            "outputFormat": "application/json",
            "srsName": "EPSG:4326",
            "count": PAGE_SIZE,
            "startIndex": start_index,
            "sortBy": "UNIQ_ID",
        }

        print(f"Downloading features starting from index {start_index}...")

        response = requests.get(
            WFS_URL,
            params=params,
            timeout=120,
        )

        response.raise_for_status()
        page_data = response.json()

        if page_data.get("type") != "FeatureCollection":
            raise ValueError("GovMap did not return a GeoJSON FeatureCollection")

        if first_response is None:
            first_response = page_data

        page_features = page_data.get("features", [])

        if not page_features:
            break

        all_features.extend(page_features)

        print(
            f"Downloaded {len(page_features)} features. "
            f"Total so far: {len(all_features)}"
        )

        start_index += len(page_features)

        number_matched = page_data.get("numberMatched")

        if number_matched not in (None, "unknown"):
            number_matched = int(number_matched)

            if len(all_features) >= number_matched:
                break

        if len(page_features) < PAGE_SIZE:
            break

    output_geojson = {
        "type": "FeatureCollection",
        "numberMatched": len(all_features),
        "numberReturned": len(all_features),
        "features": all_features,
    }

    # אם GovMap החזיר מידע על מערכת הקואורדינטות, נשמור גם אותו.
    if first_response and "crs" in first_response:
        output_geojson["crs"] = first_response["crs"]

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_FILE.open("w", encoding="utf-8") as output_file:
        json.dump(
            output_geojson,
            output_file,
            ensure_ascii=False,
        )

    print()
    print(f"Finished downloading {len(all_features)} drainage basins.")
    print(f"Saved to: {OUTPUT_FILE.resolve()}")


if __name__ == "__main__":
    download_drainage_basins()