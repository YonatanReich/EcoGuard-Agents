# analyzers/

Takes a candidate and works out what it means: the current situation, the risk
now, and how it will develop.

Split by whether a human has to be dispatched:

- `emergency/` — needs an emergency-services response. Fire, flood, earthquake.
- `non_emergency/` — advisory. Air pollution, low Kinneret level, extreme-heat
  days. Nobody is dispatched; people are informed.

That split is about the response, not the severity. A heat advisory can matter
enormously and still belong in `non_emergency/`.
