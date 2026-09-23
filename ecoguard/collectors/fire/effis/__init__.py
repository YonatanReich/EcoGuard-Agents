"""GWIS/EFFIS published Fire Weather Index.

`danger` decodes the categorised WMS raster into a danger band; `collector`
samples it for every service-area cell. This is the authority's own number,
kept as an independent cross-check on the FWI system we compute ourselves in
fire/fwi.
"""
