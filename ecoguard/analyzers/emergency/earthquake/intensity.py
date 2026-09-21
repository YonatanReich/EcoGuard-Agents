"""Shaking intensity from magnitude, depth and distance.

Replaces the four invented radius bands the impact model used to draw. Those
returned 5, 10, 25 or 50 km from magnitude alone -- no source, and depth was
collected, stored and never used, so an M5.0 at 5 km and an M5.0 at 100 km
produced the same circle.

The equation here is Allen, Wald and Worden (2012), "Intensity attenuation
for active crustal regions", Journal of Seismology 16: 409-433, in its
hypocentral-distance form. The Dead Sea Transform is an active crustal region,
which is the class the equation is derived for, and the hypocentral form needs
exactly what GSI already sends: magnitude, epicentre and depth.

Coefficients are the published ones, cross-checked against OpenQuake's
`allen_2012_ipe` implementation of the same paper.

WHAT THIS IS NOT
Output is Modified Mercalli Intensity -- how hard the ground shook. It is not
damage and not casualties. Turning intensity into either needs building
fragility and occupancy data the system does not hold, and inventing that
conversion is the failure this module exists to stop repeating.

Site amplification is also absent. Soft sediment amplifies shaking by roughly
2 to 3 over rock, and Israel's coastal plain and Jordan Valley are soft while
the hills are rock, so a rock-site estimate understates the worst places. The
equation takes no site term in this form; adding one needs a Vs30 grid, and
until that exists every value here is a rock-site approximation and says so.
"""

from __future__ import annotations

import math

# Allen, Wald & Worden (2012), Table 5, hypocentral-distance model.
C0 = 2.085
C1 = 1.428
C2 = -1.402
C4 = 0.078
M1 = -0.209
M2 = 2.042

# The anelastic term switches on beyond this range.
ANELASTIC_ONSET_KM = 50.0

# Total standard deviation, itself a function of distance: sigma is widest
# near the source and narrows with range.
S1 = 0.82
S2 = 0.37
S3 = 22.9

# The bands an operator can act on. Below VI almost nothing breaks; at VIII
# and above a response is a rescue operation rather than an assessment.
#
# Names are the standard USGS descriptors, kept so a reader can line the
# output up against any ShakeMap without a conversion table.
INTENSITY_BANDS: tuple[tuple[int, str], ...] = (
    (4, "light"),
    (5, "moderate"),
    (6, "strong"),
    (7, "very_strong"),
    (8, "severe"),
    (9, "violent"),
)

# Below this the shaking is not worth drawing: it is felt, not damaging, and
# a ring around everyone who felt an earthquake is the same uninformative
# circle this module replaced.
MIN_REPORTED_MMI = 4

# The weakest intensity still worth drawing an outline around. Nothing at
# this level breaks, so it is never an actionable band -- but a magnitude
# 3.8 at 15 km produces no band at IV anywhere, and an operator still needs
# to see where it was felt. Used only as the fallback extent.
FELT_MMI = 3


def mmi_at(magnitude: float, hypocentral_distance_km: float) -> float:
    """Modified Mercalli Intensity at one hypocentral distance.

    Args:
        magnitude: as reported by GSI.
        hypocentral_distance_km: slant distance to the hypocentre, not the
            epicentral distance -- the difference is the whole point of using
            the depth.
    """
    if hypocentral_distance_km < 0:
        raise ValueError("hypocentral distance cannot be negative")

    r_m = M1 + M2 * math.exp(magnitude - 5.0)
    distance_term = C2 * math.log(
        math.sqrt(hypocentral_distance_km**2 + r_m**2)
    )
    mmi = C0 + C1 * magnitude + distance_term
    if hypocentral_distance_km > ANELASTIC_ONSET_KM:
        mmi += C4 * math.log(hypocentral_distance_km / ANELASTIC_ONSET_KM)
    return mmi


def sigma_at(hypocentral_distance_km: float) -> float:
    """The equation's own total standard deviation at this distance.

    Carried so a caller can state the uncertainty rather than present a point
    estimate as exact. At the source it is about 0.8 intensity units, which is
    most of a whole band.
    """
    return S1 + S2 / (1.0 + (hypocentral_distance_km / S3) ** 2)


def epicentral_radius_for_mmi(
    magnitude: float, depth_km: float, target_mmi: float
) -> float | None:
    """Ground distance from the epicentre out to where shaking falls to `target_mmi`.

    Returns None when the earthquake never reaches that intensity anywhere,
    which is the common case for the upper bands: a magnitude 4 produces no
    MMI VIII at any distance, and the honest answer is that the band is absent
    rather than a radius of zero.

    The conversion from hypocentral to ground distance is where depth earns
    its place: a contour at 30 km hypocentral distance from a 25 km deep
    earthquake reaches only 16.6 km from the epicentre, and from a 40 km deep
    one it never reaches the surface at all.
    """
    if depth_km < 0:
        raise ValueError("depth cannot be negative")

    # Intensity is highest directly above the hypocentre. If it does not reach
    # the target there, it reaches it nowhere.
    if mmi_at(magnitude, depth_km) < target_mmi:
        return None

    # MMI falls monotonically with distance, so bisect on hypocentral range.
    near, far = depth_km, 1000.0
    if mmi_at(magnitude, far) > target_mmi:
        far = 2000.0  # a very large event; keep the bracket valid
    for _ in range(60):
        middle = (near + far) / 2
        if mmi_at(magnitude, middle) >= target_mmi:
            near = middle
        else:
            far = middle

    hypocentral = near
    if hypocentral <= depth_km:
        return 0.0
    return math.sqrt(hypocentral**2 - depth_km**2)


def intensity_rings(
    magnitude: float, depth_km: float, *, min_mmi: int = MIN_REPORTED_MMI
) -> list[dict[str, float | int | str]]:
    """Every band this earthquake actually produces, strongest first.

    Each entry is the epicentral radius out to which shaking is at least that
    intensity, so the rings nest. A caller counting population per band takes
    the difference between consecutive radii rather than the radii themselves.
    """
    rings: list[dict[str, float | int | str]] = []
    for level, name in sorted(INTENSITY_BANDS, reverse=True):
        if level < min_mmi:
            continue
        radius = epicentral_radius_for_mmi(magnitude, depth_km, level)
        if radius is None or radius <= 0:
            continue
        rings.append({
            "mmi": level,
            "name": name,
            "radius_km": round(radius, 2),
            "sigma": round(sigma_at(radius), 2),
        })
    return rings


__all__ = [
    "FELT_MMI",
    "INTENSITY_BANDS",
    "MIN_REPORTED_MMI",
    "epicentral_radius_for_mmi",
    "intensity_rings",
    "mmi_at",
    "sigma_at",
]
