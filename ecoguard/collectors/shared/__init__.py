"""Collectors more than one event type depends on.

A source lands here when it is not *about* any single hazard. Weather is the
clear case: fire risk, flood risk and pollution dispersion all read the same
hourly rows, and filing it under any one of them would invite the other two to
collect it again.

The test for this folder is dependency, not subject matter. If only fire ever
reads it, it belongs in fire/ even when it sounds general.
"""
