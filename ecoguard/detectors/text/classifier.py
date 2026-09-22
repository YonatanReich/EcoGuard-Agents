"""One classifier, four hazards, batched over stored text.

The question asked of every message is identical whatever its hazard — is this
a report of something happening, where, and of what — so there is one prompt
and one call, not four. A single message may report several hazards at once: a
factory fire is a fire and an air-quality event, and splitting the prompt per
hazard would make that two half-answers nobody joins back up.

What this does not do
---------------------
It does not fetch. Collection already stored the text; this reads rows.

It does not decide tier. That comes from `text_sources` by source id, and the
model is never shown it — a model told "this is the police" will read the same
sentence more generously, which is precisely the bias the allowlist exists to
keep out of the judgement.

It does not decide whether something is an event. It labels messages; triage
decides events.

It does not geocode. It copies out the location as written. Resolving that to a
cell needs the gazetteer and the service-area grid, and a model asked for
coordinates will supply plausible ones for a town it has never heard of.

It does not rewrite. The stored text stays the source of truth; `claim` is a
short neutral restatement for a human reading a card, never a replacement.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Literal, Sequence

from pydantic import BaseModel, Field

from ecoguard.database.repositories.text_candidates import (
    store_candidates,
    unclassified_text_observations,
)
from ecoguard.database.repositories.collector_runs import (
    last_success_at,
    log_finish,
    log_start,
)
from ecoguard.detectors.text.keywords import HAZARDS, hazards_in, normalise
from ecoguard.shared.llm import ClaudeLLMService

logger = logging.getLogger(__name__)

# Light model, batched: this is a short-text labelling task run over thousands
# of messages a day, not the grounded reasoning the planner does. Configurable
# because the right answer here changes faster than the code does.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# Big enough that per-call overhead is amortised, small enough that one
# malformed message cannot cost fifty others their classification, and small
# enough to stay well inside the output limit at ~8 fields per message.
DEFAULT_BATCH_SIZE = 40

# How far back an unclassified message is still worth a call. A message the
# classifier read and found nothing in leaves no row, so it is indistinguishable
# from one never read and would be offered forever without this bound.
DEFAULT_LOOKBACK = timedelta(hours=24)

# The classifier's bookmark in collector_runs, same as every other lane.
SOURCE = "text_classifier"

Hazard = Literal["fire", "flood", "earthquake", "air_quality"]
UpdateType = Literal["new", "update", "contained", "false_alarm", "none"]


class MessageLabels(BaseModel):
    """What the model returns for one message. Labels and extracts only."""

    index: int = Field(description="The message number as given in the input.")
    relevant: bool = Field(
        description="Does this message report one of the four hazards at all?"
    )
    literal: bool = Field(
        description=(
            "Is it a real event happening now? False for metaphor, for a "
            "forecast or warning about something that has not happened, and "
            "for a report about a past event."
        )
    )
    in_israel: bool = Field(
        description=(
            "Is the event located in Israel or the immediately adjacent "
            "territory? False for events abroad."
        )
    )
    hazards: list[Hazard] = Field(
        default_factory=list,
        description="Every hazard this message reports. Empty when none.",
    )
    update_type: UpdateType = Field(
        default="none",
        description=(
            "new for a first report; update for more detail on one already "
            "reported; contained when it is declared over or under control; "
            "false_alarm when the report is retracted."
        ),
    )
    location_text: str | None = Field(
        default=None,
        description=(
            "The place as the message writes it, copied not resolved. Null "
            "when the message names no place."
        ),
    )
    claim: str | None = Field(
        default=None,
        description="One short neutral sentence restating what is reported.",
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Per-hazard flags, keyed by hazard name, only for hazards listed "
            'above. fire: structures_threatened, evacuation_mentioned. '
            "flood: road_closure_mentioned, people_trapped. earthquake: "
            "felt_report, damage_reported. air_quality: smoke, "
            "chemical_release."
        ),
    )


class BatchLabels(BaseModel):
    """One object per input message, in any order — index carries identity."""

    messages: list[MessageLabels]


# Written as instructions about the text, never about the source. The examples
# are the load-bearing part: Hebrew uses all four of these words figuratively
# in ordinary political and sports writing, and a classifier that has not been
# shown the figurative use will label a column about a "political earthquake"
# as a seismic event.
SYSTEM_PROMPT = """\
You label short Hebrew and English messages from Israeli news feeds and \
Telegram channels. For each message you decide whether it reports a hazard \
happening now, which hazards, and where.

The four hazards:

fire — something is burning: wildfire, structure fire, vehicle fire.
  literal:     "שריפה פרצה ביער בן שמן, צוותי כיבוי בדרך"
  figurative:  "שריפה בליכוד: חברי הכנסת יוצאים נגד היו\"ר"

flood — water where it should not be: flash flood, wadi in spate, flooded \
roads, burst main.
  literal:     "הצפות ברחוב הרצל, הרכבים תקועים במים"
  figurative:  "הצפה של תלונות הגיעה למוקד העירוני"

earthquake — ground shaking felt or measured.
  literal:     "הורגשה רעידת אדמה בצפון הארץ, עוצמה 4.1"
  figurative:  "רעידת אדמה פוליטית: השר התפטר"

air_quality — the air is dangerous to breathe: pollution episode, hazardous \
material release, heavy smoke, dust storm.
  literal:     "דליפת חומרים מסוכנים במפעל, תושבים התבקשו להישאר בבית"
  figurative:  "ענן כבד מרחף מעל הקואליציה"

Rules:

- relevant is false when no hazard is reported at all. Most messages are not \
about hazards; that is expected.
- literal is false for metaphor, for forecasts and warnings about what might \
happen, and for reports about past events, retrospectives and anniversaries. \
A warning that a storm is coming tomorrow is not a flood. A fire that burned \
last year is not a fire.
- in_israel is false for events abroad. Foreign disasters appear constantly in \
these feeds and read exactly like local ones. Judge it from the place named in \
the message; when no place is named and nothing suggests otherwise, assume it \
is local and say so.
- A message can carry more than one hazard. A factory fire producing heavy \
smoke over a town is both fire and air_quality.
- Copy the location exactly as the message writes it. Do not translate it, \
correct it, or convert it to coordinates.
- Never rewrite or summarise the message body. claim is one short neutral \
sentence, and the original text is what is kept.

Return one object per input message, each carrying the index it was given."""


def build_batch_text(messages: Sequence[dict[str, Any]]) -> str:
    """The user turn: indexed messages, with the source name but not its tier."""
    lines = []
    for index, message in enumerate(messages):
        source = message.get("display_name") or message.get("handle") or "unknown"
        lines.append(f"[{index}] ({source}) {message['text']}")
    return "\n\n".join(lines)


def is_classifiable(text: str | None) -> bool:
    """Whether a message is worth a model call at all.

    Pure-emoji reactions, bare links and empty posts carry nothing to label,
    and every one of them in a batch is tokens spent to be told `relevant:
    false`.
    """
    if not text or not text.strip():
        return False
    stripped = normalise(text)
    # A message that is nothing but a URL.
    without_links = " ".join(
        word for word in stripped.split() if not word.startswith(("http://", "https://"))
    ).strip()
    if not without_links:
        return False
    # At least one letter in any alphabet; emoji and punctuation are not.
    return any(character.isalpha() for character in without_links)


def batched(items: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


class TextClassifier:
    """Label stored messages, with the keyword net as a floor under the model."""

    def __init__(
        self,
        *,
        llm: ClaudeLLMService | None = None,
        model: str = DEFAULT_MODEL,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._llm = llm if llm is not None else ClaudeLLMService(model=model)
        self._model = model
        self._batch_size = batch_size

    def classify(self, messages: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        """Label each message. One result per input, whatever happened.

        Each message needs `observation_id`, `source_id`, `text` and
        `observed_at`; `handle` and `display_name` are used in the prompt when
        present.
        """
        results: list[dict[str, Any]] = []
        for batch in batched(list(messages), self._batch_size):
            results.extend(self._classify_batch(batch))
        return results

    def _classify_batch(self, batch: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        # The net runs whether or not the model does — as the fallback when it
        # fails, and as the standing recall check when it succeeds.
        keyword_hits = [hazards_in(message.get("text")) for message in batch]

        worth_asking = [
            (position, message) for position, message in enumerate(batch)
            if is_classifiable(message.get("text"))
        ]
        labels: dict[int, MessageLabels] = {}
        failure: str | None = None

        if worth_asking:
            payload = [
                {**message, "text": normalise(message["text"])}
                for _, message in worth_asking
            ]
            try:
                parsed = self._llm.parse_structured(
                    system_blocks=[{"type": "text", "text": SYSTEM_PROMPT}],
                    user_text=build_batch_text(payload),
                    output_format=BatchLabels,
                )
                for item in parsed.messages:
                    if 0 <= item.index < len(worth_asking):
                        labels[worth_asking[item.index][0]] = item
            except Exception as error:
                # Never raises onward. A classification outage must degrade to
                # the keyword net, not stop the detector — and a batch lost to
                # a transient error is re-read on the next tick because the
                # cursor only advances over messages that produced a row.
                failure = type(error).__name__
                logger.exception("text classifier: batch failed; falling back to keywords")

        return [
            self._result(message, labels.get(position), keyword_hits[position], failure)
            for position, message in enumerate(batch)
        ]

    def _result(
        self,
        message: dict[str, Any],
        label: MessageLabels | None,
        keyword_hazards: dict[str, list[str]],
        failure: str | None,
    ) -> dict[str, Any]:
        if label is not None:
            hazards = [hazard for hazard in label.hazards if hazard in HAZARDS]
            return {
                "observation_id": message["observation_id"],
                "source_id": message["source_id"],
                "observed_at": message["observed_at"],
                "hazards": hazards,
                "relevant": label.relevant,
                "literal": label.literal,
                "in_israel": label.in_israel,
                "update_type": label.update_type,
                "location_text": label.location_text,
                "claim": label.claim,
                "details": label.details,
                "classified_by": "model",
                "model_version": self._model,
                "keyword_hazards": sorted(keyword_hazards),
                "keyword_terms": keyword_hazards,
            }

        # No label: either the call failed, or the message was not worth one.
        # Keyword hits still become candidates, flagged so they are never
        # mistaken for a judgement — a stem match says a word appeared, not
        # that anything is happening or where.
        #
        # `in_israel` is the one field with no honest default, and guessing
        # True cost a real classification: the first fallback run labelled a
        # Ukrainian strike on a Moscow oil refinery as a local fire. The
        # channels on the Telegram allowlist are Israeli and post about Israel;
        # the news feeds carry the whole world. So the source kind answers it,
        # which is a weak signal honestly applied rather than a guess.
        from_telegram = str(message.get("source_id") or "").startswith("telegram:")
        return {
            "observation_id": message["observation_id"],
            "source_id": message["source_id"],
            "observed_at": message["observed_at"],
            "hazards": sorted(keyword_hazards),
            "relevant": bool(keyword_hazards),
            "literal": bool(keyword_hazards),
            "in_israel": from_telegram,
            "update_type": "none",
            "location_text": None,
            "claim": None,
            "details": {},
            "classified_by": "keywords",
            "model_version": None,
            "keyword_hazards": sorted(keyword_hazards),
            "keyword_terms": keyword_hazards,
            "failure_reason": failure,
        }


def classify_new_text(
    *,
    since: datetime | None = None,
    limit: int = 500,
    classifier: "TextClassifier | None" = None,
) -> dict[str, Any]:
    """Label every stored message nothing has labelled yet, and store the rows.

    Runs on every detection tick, ahead of triage, which is the only reader of
    `text_candidates`. A tick with no new messages returns before the model is
    called, so the cost follows how much the feeds actually published.
    """
    # A message the model read and found nothing in writes no candidate row, so
    # the row-existence check alone calls it unclassified forever and re-sends
    # it every tick for a day. The bookmark is what bounds that: read what
    # arrived since the last successful run, like every other detector.
    # DEFAULT_LOOKBACK stays as the cold-start floor.
    bookmark = last_success_at(SOURCE)
    lookback = since or max(
        datetime.now(timezone.utc) - DEFAULT_LOOKBACK,
        bookmark or datetime.min.replace(tzinfo=timezone.utc),
    )

    run_id = log_start(SOURCE)
    try:
        messages = unclassified_text_observations(since=lookback, limit=limit)
        if not messages:
            log_finish(run_id, status="ok", rows_written=0)
            return {"messages": 0, "candidates": 0, "disagreements": {}}

        results = (classifier or TextClassifier()).classify(messages)
        stored = store_candidates(results)
    except Exception as error:
        log_finish(run_id, status="failed", error=f"{type(error).__name__}: {error}")
        raise

    report = disagreements(results)
    log_finish(run_id, status="ok", rows_written=stored)
    logger.info(
        "text classifier: %s messages, %s candidate rows, disagreements %s",
        len(messages), stored, report,
    )
    return {
        "messages": len(messages),
        "candidates": stored,
        "disagreements": report,
        "fell_back": sum(1 for r in results if r["classified_by"] == "keywords"),
    }


def disagreements(results: Sequence[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Per hazard, where the model and the keyword net differ.

    The Phase 2 recall check. `model_only` is what the stem list is missing;
    `keywords_only` is where the prompt has grown too strict — or, just as
    often, where the net matched a metaphor and the model correctly refused it,
    which is why the raw counts are reported rather than a score.

    Rows the net produced on its own are excluded: comparing the fallback with
    itself would report perfect agreement during an outage.
    """
    counts = {
        hazard: {"both": 0, "model_only": 0, "keywords_only": 0}
        for hazard in HAZARDS
    }
    for result in results:
        if result["classified_by"] != "model":
            continue
        model_hazards = set(result["hazards"])
        keyword_set = set(result["keyword_hazards"])
        for hazard in HAZARDS:
            in_model, in_keywords = hazard in model_hazards, hazard in keyword_set
            if in_model and in_keywords:
                counts[hazard]["both"] += 1
            elif in_model:
                counts[hazard]["model_only"] += 1
            elif in_keywords:
                counts[hazard]["keywords_only"] += 1
    return counts
