from commerce_agents.events import AgentEvent


def test_source_presentation_sse_events_are_available() -> None:
    partial = AgentEvent.ui_partial("itinerary", {"days": []})
    progress = AgentEvent.progress("x" * 200)

    assert partial.type == "ui_partial"
    assert partial.data["component"] == "itinerary"
    assert progress.type == "progress"
    assert len(progress.data["message"]) == 140
