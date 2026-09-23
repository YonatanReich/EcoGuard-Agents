"""What a land-cover class means to a fire, as spread-model parameters.

`surface_cells` stores WorldCover classes because that is what the satellite
publishes. No spread model takes a land-cover class: they take fuel load, how
deep the fuel bed is, how finely divided it is, and how wet it can get before
it stops carrying fire. This is the translation, and it is a table of constants
rather than a data source — nothing to collect, but nothing can model spread
without it.

The mapping targets the Anderson 13 standard fuel models, which is what the
Rothermel surface spread equations are parameterised against and what most
published rate-of-spread work reports in. Each WorldCover class maps to the
Anderson model that best describes Mediterranean-basin fuel of that type:

    grassland  -> FM1  short grass, fastest spreading, entirely wind-driven
    cropland   -> FM3  tall grass; stubble and standing cereal after harvest
    shrubland  -> FM5  brush; Israeli garrigue and batha
    tree_cover -> FM9  long-needle litter, which is what Aleppo pine drops and
                       what carried the 2010 Carmel fire through the crowns

**Why the load is split by size class.** Rothermel's equations are not a
function of total fuel load. They are a function of how much fuel there is *in
each size class and moisture state*, because a fire is a race between the heat
the flaming front releases and the heat the next metre of fuel absorbs before
it ignites. FM5 is the case that proves it: brush is 3.5 t/acre, but two thirds
of that is living tissue at 70-100% moisture, which does not burn — it sits in
the fuel bed as a heat sink. Collapsing FM5 into one dead-fuel class at the
total load makes it spread roughly five times faster than the published tables
say it does, and shrubland is the fuel most of wildland Israel actually is.

So each model carries its four Anderson loads separately. The totals are
unchanged from the published tables; only the split is new.

Two honest limits remain. Anderson 13 was derived in North America, so these
are the closest standard analogues rather than Israel-calibrated fuels — a
local calibration would be a research project, and the constants below are the
right place to apply it when it exists. And a cover-grid cell is a *mixture*:
`blend` below combines parameters by area fraction, which is right for load and
depth and only approximately right for the ratios.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

# Surface-area-to-volume ratios that are standard across every Anderson model
# rather than a property of any one of them, in 1/m. The dead 10-hour and
# 100-hour classes are defined by their size, so their SAV is fixed by
# definition; live SAV is the conventional 1500 1/ft used for both live
# herbaceous and live woody fuel.
SAV_DEAD_10H = 357.6
SAV_DEAD_100H = 98.4
SAV_LIVE = 4921.3


@dataclass(frozen=True)
class FuelModel:
    """One Anderson fuel model's surface-fire parameters.

    Attributes:
        code: Anderson 13 identifier.
        name: the published description.
        dead_1h_kg_m2: oven-dry load of fine dead fuel — everything under
            6 mm. This is the class that carries the flaming front; the
            coarser ones mostly absorb heat on the timescale of a spreading
            fire rather than releasing it.
        dead_10h_kg_m2: dead fuel 6-25 mm.
        dead_100h_kg_m2: dead fuel 25-75 mm.
        live_kg_m2: living herbaceous and woody tissue. Burns only once its
            own moisture is driven off, which is why it acts as a sink at the
            60-100% moisture live fuel actually holds.
        bed_depth_m: how deep the fuel bed stands. Depth drives flame length
            as much as load does — the same mass lying flat and standing up
            burn very differently.
        surface_area_to_volume: 1/m, for the dead 1-hour class. How finely
            divided the fuel is, which sets how fast it can take up heat.
            Grass is fine and ignites in seconds; logs are coarse and barely
            participate.
        live_surface_area_to_volume: 1/m, for the live class.
        moisture_of_extinction: fraction. Above this *dead* fuel moisture the
            fuel stops carrying fire at all — the single most useful number
            here, because it is the threshold a forecast can be checked
            against. The live classes get their own extinction moisture,
            which Rothermel derives from the dead-to-live loading ratio rather
            than tabulating.
        spread_adjustment: multiplier on modelled rate of spread, carrying the
            part of the class that the numbers above do not: crown involvement
            in tree cover, and discontinuity in bare ground.
    """

    code: str
    name: str
    dead_1h_kg_m2: float
    dead_10h_kg_m2: float
    dead_100h_kg_m2: float
    live_kg_m2: float
    bed_depth_m: float
    surface_area_to_volume: float
    live_surface_area_to_volume: float
    moisture_of_extinction: float
    spread_adjustment: float

    @property
    def load_kg_m2(self) -> float:
        """Total oven-dry load across every class, as the tables publish it."""
        return (
            self.dead_1h_kg_m2
            + self.dead_10h_kg_m2
            + self.dead_100h_kg_m2
            + self.live_kg_m2
        )


# Non-burnable classes are present on purpose rather than omitted. A cell that
# is 60% water is 60% firebreak, and a model that silently skips those classes
# would renormalise the rest and report the remaining 40% as if it were the
# whole cell — turning a natural barrier into average fuel.
NON_BURNABLE = FuelModel("NB", "non-burnable", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

# Loads are the published Anderson 13 tons/acre converted at 0.2242 kg/m2 per
# ton/acre, class by class. Depths and SAVs are the published values converted
# from feet and 1/ft.
FUEL_MODELS: dict[str, FuelModel] = {
    # 0.74 t/ac, all of it fine dead grass. Nothing else in the bed at all,
    # which is why FM1 is the fastest model in the set.
    "grassland": FuelModel(
        "FM1", "short grass", 0.166, 0.0, 0.0, 0.0, 0.305, 11483, SAV_LIVE, 0.12, 1.0
    ),
    # 3.01 t/ac of standing cured cereal, again entirely fine and dead.
    "cropland": FuelModel(
        "FM3", "tall grass", 0.675, 0.0, 0.0, 0.0, 0.762, 4921, SAV_LIVE, 0.25, 1.0
    ),
    # 1.0 / 0.5 / 0 / 2.0 t/ac. The live 2.0 is the whole character of the
    # model and the reason brush does not run like grass.
    "shrubland": FuelModel(
        "FM5", "brush", 0.224, 0.112, 0.0, 0.448, 0.610, 6562, SAV_LIVE, 0.20, 1.0
    ),
    # 2.92 / 0.41 / 0.15 t/ac of needle litter, no live surface fuel. The
    # adjustment carries the crown fire that makes a pine stand dangerous and
    # that a surface-fuel model does not represent at all.
    "tree_cover": FuelModel(
        "FM9", "long-needle litter", 0.655, 0.092, 0.034, 0.0, 0.061, 8202, SAV_LIVE, 0.25, 1.8
    ),
    # Built-up is not a wildland fuel and must never be averaged in as one. It
    # is exposure, reported separately by the surface repository.
    "built_up": NON_BURNABLE,
    "bare_sparse_vegetation": NON_BURNABLE,
    "permanent_water": NON_BURNABLE,
    "herbaceous_wetland": NON_BURNABLE,
    "unmapped": NON_BURNABLE,
}

# Parameters that blend as an area-weighted mean. spread_adjustment is excluded
# deliberately and handled separately below.
_BLENDED = (
    "dead_1h_kg_m2",
    "dead_10h_kg_m2",
    "dead_100h_kg_m2",
    "live_kg_m2",
    "bed_depth_m",
    "surface_area_to_volume",
    "live_surface_area_to_volume",
    "moisture_of_extinction",
)


def blend(fractions: Mapping[str, float]) -> dict[str, float | str | None]:
    """Area-weighted fuel parameters for one cell's cover mixture.

    Args:
        fractions: cover class name to its share of the cell, as
            `surface_cells` stores it and the surface repository returns it.

    Returns:
        dict: the blended parameters, the dominant *burnable* model, and the
            burnable share the blend is over. `dominant_fuel_model` is None and
            the parameters are zero when nothing in the cell can carry fire.
            `load_kg_m2` is the total across classes, which is what the
            published tables quote and what a reader expects to recognise.

    The weighting runs over the whole cell, not just its burnable part, so a
    cell that is one-fifth grass and four-fifths rock reports one-fifth of
    grass's fuel load. That is the physically meaningful reading: there is
    genuinely that much less to burn per square metre, and it is why a fire
    slows crossing sparse ground instead of racing over it as a pure-grass
    model would claim.
    """
    weights = {
        name: max(0.0, float(share))
        for name, share in fractions.items()
        if name in FUEL_MODELS
    }
    burnable = {
        name: share
        for name, share in weights.items()
        if FUEL_MODELS[name] is not NON_BURNABLE and share > 0
    }

    blended = {
        field: sum(share * getattr(FUEL_MODELS[name], field) for name, share in weights.items())
        for field in _BLENDED
    }
    if not burnable:
        return {
            **{field: 0.0 for field in _BLENDED},
            "load_kg_m2": 0.0,
            "dominant_fuel_model": None,
            "fuel_model_code": None,
            "burnable_fraction": 0.0,
            "spread_adjustment": 0.0,
        }

    dominant = max(burnable, key=burnable.get)
    total = sum(burnable.values())

    # The ratios are blended over the burnable part only. Averaging a SAV or an
    # extinction moisture towards zero across bare rock would describe a fuel
    # that does not exist anywhere in the cell; the dilution belongs in the
    # loads, which already carry it.
    for field in ("surface_area_to_volume", "live_surface_area_to_volume", "moisture_of_extinction"):
        blended[field] = sum(
            share * getattr(FUEL_MODELS[name], field) for name, share in burnable.items()
        ) / total

    loads = ("dead_1h_kg_m2", "dead_10h_kg_m2", "dead_100h_kg_m2", "live_kg_m2")
    return {
        **{field: round(value, 4) for field, value in blended.items()},
        "load_kg_m2": round(sum(blended[field] for field in loads), 4),
        "dominant_fuel_model": dominant,
        "fuel_model_code": FUEL_MODELS[dominant].code,
        "burnable_fraction": round(total, 4),
        # Averaged over the burnable part only, not the whole cell. It is a
        # multiplier on the behaviour of fuel that is present; diluting it by
        # the bare ground would double-count that dilution, which the load has
        # already applied.
        "spread_adjustment": round(
            sum(share * FUEL_MODELS[name].spread_adjustment for name, share in burnable.items())
            / total,
            4,
        ),
    }
