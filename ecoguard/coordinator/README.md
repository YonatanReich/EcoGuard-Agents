# coordinator/

Empty. The candidate coordinator lands here.

Detectors fire independently and will report the same event more than once: a
satellite hotspot, three Telegram messages and a station reading can all be one
fire. This is where duplicates are merged into a single incident, candidates
from different sources are correlated, and one event gets one identity before
anything downstream analyses it.

It sits between `detectors/` and `analyzers/` because analysing the same fire
four times is both wasteful and misleading — four assessments look like four
fires to whoever is reading.
