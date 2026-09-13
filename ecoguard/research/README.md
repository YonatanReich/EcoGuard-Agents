# research/

Offline work: historical dataset construction, model training and calibration,
evaluation harnesses, and pilot studies.

Not purely offline, though — **production imports five modules from here**
(model calibration, evaluation schemas, historical feature builders, the
land-cover/terrain samplers). That coupling is a feature-contract dependency,
not convenience: the model's feature order is defined here. Treat changes to
those modules as production changes.

`research/tests/` is excluded from the default pytest run and must be invoked
explicitly.
