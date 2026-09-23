"""The European fire-danger service.

Publishes a daily rating of how readily fire would spread, as an image covering
the region. Downloaded once a day and sampled per grid cell."""

import io
from datetime import date

import requests
from PIL import Image


class FireDangerAgent:
    """
    Retrieves and classifies the Fire Weather Index danger level for a
    geographic coordinate.

    Attributes:
        base_url (str): GWIS/EFFIS WMS endpoint.
        layer (str): Fire Weather Index raster layer used by the project.
    """

    def __init__(self):
        """Build the client for the European fire-danger service."""
        self.base_url = (
            "https://maps.effis.emergency.copernicus.eu/effis"
        )

        # This layer was discovered through the WMS GetCapabilities request
        # and successfully tested for locations in Israel.
        self.layer = "mf010.fwi"

    def fetch_fwi_image(
        self,
        latitude: float,
        longitude: float,
        delta: float = 0.5
    ) -> Image.Image:
        """
        Fetch the FWI raster around a geographic coordinate.

        A symmetric bounding box is created around the requested point.
        This intentionally places the requested latitude/longitude at the
        center of the returned image, allowing the center pixel to be used
        for classification.

        Args:
            latitude (float): Location latitude in decimal degrees.
            longitude (float): Location longitude in decimal degrees.
            delta (float): Number of degrees to extend the bounding box
                from the requested coordinate in every direction.

        Returns:
            Image.Image: RGB representation of the FWI raster returned
                by GWIS/EFFIS.

        Raises:
            requests.HTTPError: If the WMS request returns a non-success
                HTTP status.
            requests.RequestException: If communication with the service
                fails.
        """
        west = longitude - delta
        south = latitude - delta
        east = longitude + delta
        north = latitude + delta

        params = {
            "SERVICE": "WMS",
            "VERSION": "1.1.1",
            "REQUEST": "GetMap",
            "LAYERS": self.layer,
            "STYLES": "",
            "SRS": "EPSG:4326",
            "BBOX": f"{west},{south},{east},{north}",
            "WIDTH": 500,
            "HEIGHT": 500,
            "FORMAT": "image/png",
            "TRANSPARENT": "false",
            "TIME": date.today().isoformat(),
        }

        response = requests.get(
            self.base_url,
            params=params,
            timeout=30
        )

        response.raise_for_status()

        # The image is opened directly from memory. The production agent
        # therefore does not need to create temporary PNG files on disk.
        return Image.open(
            io.BytesIO(response.content)
        ).convert("RGB")

    def get_center_pixel(
        self,
        image: Image.Image
    ) -> tuple[int, int, int]:
        """
        Read the RGB value representing the requested coordinate.

        fetch_fwi_image creates a bounding box centered on the requested
        location, so the center pixel of the returned raster corresponds
        to that location.

        Args:
            image (Image.Image): RGB FWI raster returned by GWIS/EFFIS.

        Returns:
            tuple[int, int, int]: RGB value of the center pixel.
        """
        center_x = image.width // 2
        center_y = image.height // 2

        return image.getpixel(
            (center_x, center_y)
        )

    def classify_fwi_pixel(
        self,
        pixel: tuple[int, int, int]
    ) -> dict:
        """
        Convert a GWIS/EFFIS raster color into an FWI danger category.

        The RGB values below were extracted from the official legend
        returned by the same WMS service using GetLegendGraphic.

        Because the raster provides a categorized visualization, the
        function returns the category and its FWI range rather than
        claiming an exact FWI value.

        Args:
            pixel (tuple[int, int, int]): RGB value to classify.

        Returns:
            dict: Classification containing:
                - danger_level
                - fwi_min
                - fwi_max
                - pixel_rgb

            If the RGB value does not match a known legend category,
            danger_level is returned as "unknown".
        """
        fwi_classes = {
            (156, 255, 192): {
                "danger_level": "low",
                "fwi_min": None,
                "fwi_max": 11.2,
            },
            (205, 226, 78): {
                "danger_level": "moderate",
                "fwi_min": 11.2,
                "fwi_max": 21.3,
            },
            (230, 172, 0): {
                "danger_level": "high",
                "fwi_min": 21.3,
                "fwi_max": 38.0,
            },
            (217, 112, 16): {
                "danger_level": "very_high",
                "fwi_min": 38.0,
                "fwi_max": 50.0,
            },
            (173, 6, 14): {
                "danger_level": "extreme",
                "fwi_min": 50.0,
                "fwi_max": 70.0,
            },
            (58, 0, 21): {
                "danger_level": "very_extreme",
                "fwi_min": 70.0,
                "fwi_max": None,
            },
        }

        result = fwi_classes.get(pixel)

        # Do not guess a category if GWIS returns an unexpected color.
        # This can happen if the WMS style changes or the requested point
        # contains no classified FWI data.
        if result is None:
            return {
                "danger_level": "unknown",
                "fwi_min": None,
                "fwi_max": None,
                "pixel_rgb": list(pixel),
            }

        return {
            **result,
            "pixel_rgb": list(pixel),
        }

    def get_fire_danger(
        self,
        latitude: float,
        longitude: float
    ) -> dict:
        """
        Retrieve the complete FWI danger classification for a coordinate.

        This is the main public method of FireDangerAgent. Callers do not
        need to work directly with WMS images or RGB values.

        Args:
            latitude (float): Location latitude in decimal degrees.
            longitude (float): Location longitude in decimal degrees.

        Returns:
            dict: Structured fire-danger information containing the data
                source, index type, requested location, danger category,
                FWI category range and the underlying raster RGB value.
        """
        image = self.fetch_fwi_image(
            latitude=latitude,
            longitude=longitude
        )

        pixel = self.get_center_pixel(image)

        classification = self.classify_fwi_pixel(pixel)

        return {
            "source": "GWIS/EFFIS",
            "index": "FWI",
            "latitude": latitude,
            "longitude": longitude,
            **classification,
        }