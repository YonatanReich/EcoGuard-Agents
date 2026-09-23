"""Acceptance tests for the committed Flood protocol corpus."""

import json

import pytest

from ecoguard.planners.shared.planner import EmergencyResponsePlanner
from ecoguard.planners.shared.schemas import EmergencyResponsePlanInput
from ecoguard.shared.protocols import ProtocolRetriever


FLOOD_FILENAMES = {
    "wollondilly-shire-flood-response.md",
    "bayside-flood-response.md",
    "armidale-regional-flood-response.md",
    "israel-moe-field-trip-flood-safety.md",
    "israel-mot-transport-flood-preparedness.md",
    "netivei-israel-storm-response.md",
    "israel-national-flood-reference-scenario.md",
    "oman-wadi-flash-flood-safety.md",
    "israel-dead-sea-flood-reference-scenario.md",
    "israel-ims-coastal-rainfall-scenarios.md",
    "israel-ims-extreme-weather-scenarios-2023.md",
    "israel-fire-lehava-diving-procedure.md",
    "israel-fire-underground-parking-flood.md",
}


def test_flood_manifest_and_all_approved_documents_load():
    retriever = ProtocolRetriever(hazard="flood")
    manifest = json.loads(
        (retriever.corpus_path / "manifest.json").read_text(encoding="utf-8")
    )
    on_disk = {path.name for path in retriever.corpus_path.glob("*.md")}

    assert retriever.available is True
    assert manifest["hazard"] == "flood"
    assert manifest["corpus_version"] == "1.0.0"
    assert len(manifest["documents"]) == 13
    assert len(retriever.documents) == 13
    assert on_disk == FLOOD_FILENAMES
    assert {item["filename"] for item in manifest["documents"]} == FLOOD_FILENAMES
    assert len(retriever.documents) == len(set(retriever.documents))
    assert {chunk["document_id"] for chunk in retriever.chunks} == set(
        retriever.documents
    )


@pytest.mark.parametrize(
    "query,expected_documents",
    [
        (
            "underground parking flood trapped civilians",
            {"israel-fire-underground-parking-flood"},
        ),
        (
            "flooded road closure police",
            {"netivei-israel-storm-response", "israel-mot-transport-flood-preparedness"},
        ),
        (
            "desert flash flood wadi",
            {"oman-wadi-flash-flood-safety", "israel-moe-field-trip-flood-safety"},
        ),
        (
            "evacuation",
            {
                "wollondilly-shire-flood-response",
                "bayside-flood-response",
                "armidale-regional-flood-response",
            },
        ),
        (
            "diving water rescue",
            {"israel-fire-lehava-diving-procedure"},
        ),
        (
            "infrastructure restoration",
            {"israel-dead-sea-flood-reference-scenario"},
        ),
    ],
)
def test_representative_flood_queries_retrieve_relevant_documents(
    query, expected_documents
):
    results = ProtocolRetriever(hazard="flood").retrieve(query, top_k=5)

    assert results
    assert expected_documents & {result["document_id"] for result in results}


def test_fire_and_flood_corpora_are_isolated():
    fire_ids = {
        chunk["document_id"] for chunk in ProtocolRetriever(hazard="fire").chunks
    }
    flood_ids = {
        chunk["document_id"] for chunk in ProtocolRetriever(hazard="flood").chunks
    }

    assert fire_ids
    assert flood_ids
    assert fire_ids.isdisjoint(flood_ids)


def test_foreign_supplementary_metadata_reaches_the_claude_prompt():
    retriever = ProtocolRetriever(hazard="flood")
    chunk = retriever.retrieve("desert flash flood wadi", top_k=1)[0]
    analysis = EmergencyResponsePlanInput(
        hazard_type="flood",
        event_description="A flash flood is moving through a desert wadi.",
    )
    _, prompt = EmergencyResponsePlanner.build_prompt(analysis, [chunk])

    assert chunk["document_id"] == "oman-wadi-flash-flood-safety"
    assert chunk["jurisdiction"] == "Oman"
    assert chunk["applicability"] == "supplementary operational guidance"
    assert chunk["local_adaptation_required"] is True
    assert "Jurisdiction: Oman" in prompt
    assert "Applicability: supplementary operational guidance" in prompt
    assert "Local adaptation required: true" in prompt


def test_transport_protocol_is_normalized_to_markdown():
    corpus = ProtocolRetriever(hazard="flood").corpus_path

    assert (corpus / "israel-mot-transport-flood-preparedness.md").is_file()
    assert not (corpus / "israel-mot-transport-flood-preparedness").exists()
