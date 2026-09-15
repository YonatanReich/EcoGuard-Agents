# detectors/flood/

Flood candidate detection based on cached Water Authority hydrometric data.

Read hydrometric and weather data from `ecoguard/collection/`; do not collect
it here. `detection_agent.py` produces candidate events with evidence and no
risk score — scoring belongs to `analyzers/emergency/flood/`.
