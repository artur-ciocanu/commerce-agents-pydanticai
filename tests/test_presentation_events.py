from commerce_agents.events import AgentEvent
from commerce_agents.presentation import progress, ui_partial


def test_source_presentation_sse_events_are_available() -> None:
    partial = AgentEvent.ui_partial("itinerary", {"days": []})
    progress = AgentEvent.progress("x" * 200)

    assert partial.type == "ui_partial"
    assert partial.data["component"] == "itinerary"
    assert progress.type == "progress"
    assert len(progress.data["message"]) == 140


def test_presentation_helpers_do_not_introduce_model_markup() -> None:
    event = ui_partial("plan_matrix", {"plans": []})
    update = progress("Loading source-backed data")

    assert event.data == {"component": "plan_matrix", "payload": {"plans": []}}
    assert update.data["message"] == "Loading source-backed data"
