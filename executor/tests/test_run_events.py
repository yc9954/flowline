"""Agent events (agent-ts/run.mjs → POST /runs/{id}/events) map onto the four RunSteps."""
import tempfile

from runs import Run, RunContext

LABELS = ["READ THE SHEET", "FILL THE DECK", "CHECK THE TOTAL", "LEAVE IT FOR YOU"]


def make_ctx():
    ctx = RunContext(Run(id="run-test", skill_id="fill_deck_from_sheet", target="desk1"), runs_dir=tempfile.mkdtemp())
    ctx.set_steps(LABELS)
    return ctx


def test_explicit_step_events():
    ctx = make_ctx()
    ctx.apply_event({"type": "step", "step": 1, "status": "now", "detail": "Reading the sheet"})
    assert ctx.run.steps[0].status == "now" and ctx.run.steps[0].detail == "Reading the sheet"
    ctx.apply_event({"type": "step", "step": 1, "status": "done", "detail": "Three items and the total: $4,290"})
    ctx.apply_event({"type": "step", "step": 2, "status": "now", "detail": "Typing", "progress": [2, 4]})
    assert [s.status for s in ctx.run.steps] == ["done", "now", "pending", "pending"]
    assert ctx.run.steps[1].progress == (2, 4)
    assert ctx.run.steps[0].detail.startswith("Three items")


def test_inferred_steps_from_tool_calls():
    ctx = make_ctx()
    ctx.apply_event({"type": "tool_call", "name": "read_sheet", "input": "{}", "seconds": 0.3, "ok": True})
    assert ctx.run.steps[0].status == "now"
    ctx.apply_event({"type": "tool_call", "name": "computer", "action": "screenshot", "input": "{}", "seconds": 0.5, "ok": True, "screenshot": "/x/shot-001.png"})
    assert [s.status for s in ctx.run.steps[:2]] == ["done", "now"]
    for _ in range(3):
        ctx.apply_event({"type": "tool_call", "name": "computer", "action": "left_click", "input": "{}", "seconds": 0.4, "ok": True})
        ctx.apply_event({"type": "tool_call", "name": "computer", "action": "type", "input": "{}", "seconds": 0.4, "ok": True})
    assert ctx.run.steps[1].progress == (3, 4)
    ctx.apply_event({"type": "tool_call", "name": "read_deck_cells", "input": "{}", "seconds": 0.4, "ok": True, "output": "{}"})
    assert [s.status for s in ctx.run.steps] == ["done", "done", "now", "pending"]
    kinds = [a.kind for a in ctx.run.actions]
    assert "computer.screenshot" in kinds and "read_deck_cells" in kinds
    assert any("shot-001.png" in a.detail for a in ctx.run.actions)


def test_done_and_error_events_are_logged():
    ctx = make_ctx()
    ctx.apply_event({"type": "done", "status": "finished", "steps": 9, "text": "done", "seconds": 40.2})
    ctx.apply_event({"type": "error", "error": "boom", "seconds": 1.0})
    assert [a.kind for a in ctx.run.actions] == ["agent_done", "agent_error"]
    assert ctx.run.status == "running"  # the Python side decides the final status after verification
