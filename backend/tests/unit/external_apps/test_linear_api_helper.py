"""The bundled ``linear_api.py`` sandbox helper: ``create-issue`` input
construction (the new project/state/priority/label/estimate/parent flags) and the
``projects`` team-linkage selection. The helper is a standalone script under the
skills dir (not an importable package), so load it by path."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

_HELPER = (
    Path(__file__).resolve().parents[3] / "onyx/skills/builtin" / "linear/linear_api.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("linear_api", _HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


linear = _load()


def _capture_gql(monkeypatch: Any) -> list[tuple[str, dict[str, Any]]]:
    """Monkeypatch ``_gql`` to record (query, variables) and return a benign
    success envelope so ``_dispatch`` runs without touching the network."""
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_gql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        calls.append((query, variables))
        return {"data": {"issueCreate": {"success": True, "issue": {"id": "I1"}}}}

    monkeypatch.setattr(linear, "_gql", fake_gql)
    return calls


def test_create_issue_sets_all_new_fields(monkeypatch: Any) -> None:
    calls = _capture_gql(monkeypatch)
    args = linear._build_parser().parse_args(
        [
            "create-issue",
            "TEAM1",
            "My title",
            "--description",
            "Body",
            "--assignee",
            "USER1",
            "--project",
            "PROJ1",
            "--state",
            "STATE1",
            "--priority",
            "2",
            "--label",
            "LBL1",
            "--label",
            "LBL2",
            "--estimate",
            "5",
            "--parent",
            "ISSUE_PARENT",
        ]
    )
    result = linear._dispatch(args)

    assert result["ok"] is True
    assert len(calls) == 1
    _query, variables = calls[0]
    inp = variables["input"]

    assert inp["teamId"] == "TEAM1"
    assert inp["title"] == "My title"
    assert inp["description"] == "Body"
    assert inp["assigneeId"] == "USER1"
    assert inp["projectId"] == "PROJ1"
    assert inp["stateId"] == "STATE1"
    assert inp["priority"] == 2
    assert inp["labelIds"] == ["LBL1", "LBL2"]
    assert inp["estimate"] == 5
    assert inp["parentId"] == "ISSUE_PARENT"


def test_create_issue_priority_zero_is_kept(monkeypatch: Any) -> None:
    # priority 0 (no priority) is a real value, not "omitted" — it must be sent.
    calls = _capture_gql(monkeypatch)
    args = linear._build_parser().parse_args(
        ["create-issue", "TEAM1", "Title", "--priority", "0"]
    )
    linear._dispatch(args)
    inp = calls[0][1]["input"]
    assert inp["priority"] == 0


def test_create_issue_minimal_only_team_and_title(monkeypatch: Any) -> None:
    calls = _capture_gql(monkeypatch)
    args = linear._build_parser().parse_args(["create-issue", "TEAM1", "Just a title"])
    linear._dispatch(args)

    inp = calls[0][1]["input"]
    assert inp == {"teamId": "TEAM1", "title": "Just a title"}
    for omitted in (
        "description",
        "assigneeId",
        "projectId",
        "stateId",
        "priority",
        "labelIds",
        "estimate",
        "parentId",
    ):
        assert omitted not in inp


def test_projects_query_includes_team_linkage(monkeypatch: Any) -> None:
    """The ``projects`` selection must surface each project's teams so the right
    teamId can be picked, while remaining backward compatible (id/name/state/url)."""
    captured: list[tuple[str, dict[str, Any]]] = []

    def fake_gql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        captured.append((query, variables))
        return {
            "data": {
                "projects": {
                    "nodes": [
                        {
                            "id": "P1",
                            "name": "Roadmap",
                            "state": "started",
                            "url": "https://linear.app/p/P1",
                            "teams": {
                                "nodes": [{"id": "T1", "key": "ENG", "name": "Eng"}]
                            },
                        }
                    ],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            }
        }

    monkeypatch.setattr(linear, "_gql", fake_gql)
    args = linear._build_parser().parse_args(["projects", "--limit", "10"])
    result = linear._dispatch(args)

    query = captured[0][0]
    # nested teams are bounded and carry a truncation hint (not silently capped)
    assert "teams(first:50) { nodes { id key name } pageInfo { hasNextPage } }" in query
    # still backward compatible
    assert "id name state url" in query
    assert result["ok"] is True
    assert result["projects"][0]["teams"]["nodes"][0]["key"] == "ENG"
