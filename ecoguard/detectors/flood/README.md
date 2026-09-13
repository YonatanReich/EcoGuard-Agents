# detectors/flood/

Empty. Flood candidate detection lands here (EA-278 / EA-287).

Read hydrometric and weather data from `ecoguard/collection/`; do not collect
it here. Produce a candidate event with evidence and no risk score — scoring is
`analyzers/emergency/flood/`.
