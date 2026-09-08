"""Actual reviewed pollution corpus + mocked Claude; no network/model billing."""

import hashlib
from copy import deepcopy

import pytest

from agents.air_pollution_response_planner import AirPollutionResponsePlanner
from agents.air_pollution_response_schemas import AirPollutionPlanProposal
from services.protocol_retrieval_service import ProtocolRetriever, normalize_for_match
from tests.test_air_pollution_response_planner import FakeLLM, anomaly


ACTION_DOCUMENTS = {
    "PM2.5": "israel-particulate-advisory",
    "PM10": "israel-particulate-advisory",
    "O3": "us-airnow-ozone",
    "NO2": "us-airnow-no2",
    "SO2": "us-airnow-so2",
    "CO": "us-airnow-ambient-co",
}


def pollution_event(pollutant):
    payload = anomaly().model_dump()
    payload["pollutant_observations"][0]["pollutant"] = pollutant
    payload["pollutant_observations"][0]["unit"] = "ppm" if pollutant == "CO" else (
        "ppb" if pollutant in {"O3", "NO2", "SO2"} else "µg/m³"
    )
    return type(anomaly()).model_validate(payload)


def scoped_chunks(retriever, pollutant):
    chunks = retriever.retrieve(
        f"air pollution {pollutant} response public health advisory monitoring",
        # Match the planner's small-corpus retrieval path. One document can
        # produce multiple chunks, and the reviewed action is not necessarily
        # in the document's highest-ranked chunk.
        top_k=max(len(retriever.chunks), len(retriever.documents)),
    )
    return [
        chunk for chunk in chunks
        if {pollutant}.issubset(set(retriever.documents[chunk["document_id"]]["supported_pollutants"]))
    ]


def grounded_proposal(retriever, pollutant="PM2.5"):
    actions, citations = [], []
    for chunk in scoped_chunks(retriever, pollutant):
        for reviewed in retriever.documents[chunk["document_id"]]["reviewed_actions"]:
            if normalize_for_match(reviewed["recommendation"]) not in normalize_for_match(chunk["text"]):
                continue
            actions.append({**reviewed, "supporting_chunk_ids": [chunk["chunk_id"]]})
            citations.append({
                "chunk_id": chunk["chunk_id"],
                "document_title": chunk["document_title"],
                "quoted_text": reviewed["recommendation"],
                "supports": "Conditional decision support",
            })
    assert actions
    return AirPollutionPlanProposal(
        summary="Reviewed conditional public-health decision support.",
        recommended_authority_types=sorted({a["responsible_authority_type"] for a in actions}),
        recommended_resource_types=sorted({a["resource_type"] for a in actions}),
        actions=actions,
        protocol_citations=citations,
    )


def test_corpus_loads_with_attribution_scope_and_reproducible_hashes():
    retriever = ProtocolRetriever(hazard="air_pollution")
    assert retriever.available and len(retriever.documents) == 10
    assert {doc["jurisdiction"] for doc in retriever.documents.values()} >= {
        "Israel", "United States", "Global health guidance",
    }
    for doc in retriever.documents.values():
        text = (retriever.corpus_path / doc["filename"]).read_text(encoding="utf-8")
        assert hashlib.sha256(text.encode("utf-8")).hexdigest() == doc["sha256"]
        assert doc["source_url"].startswith("https://")
        assert doc["jurisdiction"] and doc["guidance_kind"]
        assert doc["scope"] and doc["license"] and doc["retrieved_at"]
        assert set(doc["supported_pollutants"]).issubset(set(ACTION_DOCUMENTS))
        for action in doc["reviewed_actions"]:
            assert action["recommendation"] in text
            assert action["timeframe"] == action["priority"] == "not_specified"


@pytest.mark.parametrize("pollutant", list(ACTION_DOCUMENTS))
def test_pollutant_query_retrieves_its_scoped_action_document(pollutant):
    chunks = scoped_chunks(ProtocolRetriever(hazard="air_pollution"), pollutant)
    assert any(c["document_id"] == ACTION_DOCUMENTS[pollutant] for c in chunks)


def test_israeli_and_us_jurisdiction_metadata_remains_distinct():
    documents = ProtocolRetriever(hazard="air_pollution").documents
    assert documents["israel-particulate-advisory"]["jurisdiction"] == "Israel"
    for document_id in {"us-airnow-ozone", "us-airnow-no2", "us-airnow-so2", "us-airnow-ambient-co"}:
        document = documents[document_id]
        assert document["jurisdiction"] == "United States"
        assert "US EPA AQI category" in document["scope"]


def test_hazard_indexes_are_disjoint_even_for_cross_hazard_queries():
    pollution, fire = ProtocolRetriever(hazard="air_pollution"), ProtocolRetriever(hazard="fire")
    assert set(pollution.documents).isdisjoint(fire.documents)
    assert not any(c["document_id"] in fire.documents for c in pollution.retrieve("fire evacuation", top_k=20))
    assert not any(c["document_id"] in pollution.documents for c in fire.retrieve("PM10 pollution", top_k=20))


@pytest.mark.parametrize("pollutant", list(ACTION_DOCUMENTS))
def test_planner_produces_only_cited_pollutant_scoped_actions(pollutant):
    retriever = ProtocolRetriever(hazard="air_pollution")
    llm = FakeLLM(grounded_proposal(retriever, pollutant))
    event = pollution_event(pollutant)
    result = AirPollutionResponsePlanner(llm_service=llm).plan_response(event)
    assert result.plan.status == "success"
    assert result.event.anomaly == event
    verified = {c.chunk_id for c in result.plan.protocol_references if c.verified}
    for action in result.plan.actions:
        assert set(action.supporting_chunk_ids).issubset(verified)
    assert "Reviewed actions" in llm.calls[0]["user_text"]


def test_us_guidance_is_conditional_and_does_not_map_israeli_aqi():
    retriever = ProtocolRetriever(hazard="air_pollution")
    proposal = grounded_proposal(retriever, "O3")
    result = AirPollutionResponsePlanner(llm_service=FakeLLM(proposal)).plan_response(
        pollution_event("O3")
    )
    recommendation = result.plan.actions[0].recommendation
    assert recommendation.startswith("If an authorized source explicitly reports")
    assert "US EPA AQI category" in recommendation
    assert "Israeli AQI" not in recommendation


def test_ambient_co_corpus_excludes_indoor_poisoning_guidance():
    retriever = ProtocolRetriever(hazard="air_pollution")
    document = retriever.documents["us-airnow-ambient-co"]
    text = (retriever.corpus_path / document["filename"]).read_text(encoding="utf-8").lower()
    assert "outdoor ambient" in text
    assert "indoor carbon-monoxide poisoning guidance is outside scope" in text
    assert all("indoor" not in action["recommendation"].lower() for action in document["reviewed_actions"])


@pytest.mark.parametrize("pollutant", ["NO", "NOx", "H2S", "Benzene"])
def test_unsupported_pollutants_fail_before_claude(pollutant):
    event = pollution_event(pollutant)
    llm = FakeLLM(None)
    result = AirPollutionResponsePlanner(llm_service=llm).plan_response(event)
    assert result.plan.reason == "guidance_unavailable"
    assert not llm.calls and result.event.anomaly == event


def test_pollutant_scope_mismatch_fails_closed():
    event = anomaly().model_dump()
    gas = {**event["pollutant_observations"][0], "pollutant": "O3", "unit": "ppb"}
    event["pollutant_observations"].append(gas)
    llm = FakeLLM(None)
    result = AirPollutionResponsePlanner(llm_service=llm).plan_response(type(anomaly()).model_validate(event))
    assert result.plan.reason == "guidance_unavailable" and not llm.calls


@pytest.mark.parametrize("unsupported", [
    "Evacuate all nearby settlements.", "Close nearby roads.",
    "Shut down an industrial facility.", "Dispatch three emergency vehicles.",
])
def test_verified_citation_cannot_authorize_unsupported_action(unsupported):
    retriever = ProtocolRetriever(hazard="air_pollution")
    payload = grounded_proposal(retriever, "O3").model_dump()
    payload["actions"][0]["recommendation"] = unsupported
    llm = FakeLLM(AirPollutionPlanProposal.model_validate(payload))
    result = AirPollutionResponsePlanner(llm_service=llm).plan_response(pollution_event("O3"))
    assert result.plan.reason == "ungrounded_response"
    assert result.plan.actions == []


def test_removed_review_metadata_cannot_silently_activate_corpus():
    retriever = ProtocolRetriever(hazard="air_pollution")
    retriever.documents = deepcopy(retriever.documents)
    for doc in retriever.documents.values():
        doc.pop("reviewed_actions")
    llm = FakeLLM(None)
    result = AirPollutionResponsePlanner(llm_service=llm, retriever=retriever).plan_response(anomaly())
    assert result.plan.reason == "guidance_unavailable" and not llm.calls
