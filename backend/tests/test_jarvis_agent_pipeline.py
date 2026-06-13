"""Tests for Jarvis multi-agent operational pipeline builder."""

from __future__ import annotations

from app.jarvis.execution.agent_pipeline import AGENT_ORDER, build_agent_pipeline


def test_build_agent_pipeline_idle_agents_without_task():
    result = build_agent_pipeline({})
    assert len(result["agents"]) == len(AGENT_ORDER)
    assert all(a["status"] in {"idle", "pending", "skipped"} for a in result["agents"])


def test_build_agent_pipeline_phase3_maps_logs():
    task = {
        "task_id": "t-1",
        "status": "completed",
        "estimated_cost_usd": 0.08,
        "actual_cost_usd": 0.06,
        "plan": {
            "steps": [{"estimated_cost_usd": 0.02}],
            "total_estimated_cost_usd": 0.08,
        },
        "execution_log": [
            {"log_id": "1", "agent": "service", "tool": "submit", "output_summary": "queued", "duration_ms": 0},
            {"log_id": "2", "agent": "planner_agent", "tool": "build_plan", "output_summary": "steps=3", "duration_ms": 5},
            {"log_id": "3", "agent": "repository_agent", "tool": "investigate_objective", "output_summary": "queries=2", "duration_ms": 10},
            {"log_id": "4", "agent": "executor_agent", "tool": "inspect_health", "output_summary": "ok", "duration_ms": 100},
        ],
    }
    result = build_agent_pipeline(task)
    by_id = {a["id"]: a for a in result["agents"]}

    assert result["workflow_type"] == "phase3_investigation"
    assert by_id["supervisor"]["status"] == "completed"
    assert by_id["planner"]["status"] == "completed"
    assert by_id["repository"]["status"] == "completed"
    assert by_id["patch"]["status"] == "skipped"
    assert by_id["reviewer"]["status"] == "skipped"
    assert by_id["test"]["status"] == "completed"
    assert by_id["test"]["duration_ms"] == 100


def test_build_agent_pipeline_phase4_full_pipeline():
    task = {
        "task_id": "t-2",
        "status": "waiting_for_approval",
        "plan": {"workflow_type": "phase4_change", "steps": []},
        "execution_log": [
            {"log_id": "1", "agent": "planner_agent", "tool": "build_plan", "output_summary": "steps=2", "duration_ms": 1},
            {"log_id": "2", "agent": "repository_agent", "tool": "investigate", "output_summary": "modules=5", "duration_ms": 2},
            {"log_id": "3", "agent": "patch_agent", "tool": "create_patch", "output_summary": "patch ready", "duration_ms": 3},
            {"log_id": "4", "agent": "reviewer_agent", "tool": "review_patch", "output_summary": "risk=40", "duration_ms": 4},
            {"log_id": "5", "agent": "test_agent", "tool": "run_tests", "output_summary": "passed", "duration_ms": 50},
        ],
    }
    result = build_agent_pipeline(task)
    by_id = {a["id"]: a for a in result["agents"]}

    assert result["workflow_type"] == "phase4_change"
    assert by_id["patch"]["status"] == "completed"
    assert by_id["reviewer"]["status"] == "completed"
    assert by_id["test"]["last_action"] == "run_tests: passed"
