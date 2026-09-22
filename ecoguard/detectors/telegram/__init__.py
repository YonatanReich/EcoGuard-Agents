"""Telegram-specific helpers shared by the text-event lane.

The Telegram collector stores raw messages like any other text source; the
classifier and triage in `detectors/text` label and coordinate them exactly
like RSS. `flood_candidate_filter.py` here is the one piece that stays
Telegram-specific: a rule-based pre-filter the shared keyword scan reuses.

There used to be a second module, `evidence.py`, that matched Telegram
messages against already-detected Fire/Flood signals as supporting evidence.
It was never wired into the scheduled pipeline in practice and has been
removed; the text-event lane above is the only path from a Telegram message
to an incident now.
"""
