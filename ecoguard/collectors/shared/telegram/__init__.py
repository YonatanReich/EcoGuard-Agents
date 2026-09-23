"""Raw Telegram messages, read by the shared text-event lane.

Collection deliberately preserves provider material without deciding whether a
message describes an event. Classification (`detectors/text/classifier.py`)
and triage (`detectors/text/run.py`) do that, on their own schedule.
"""
