"""#102 slash commands in the assistant.

A slash command is a fast intent that arrived as `/find router` instead of
"find router". It resolves to the same tool call — there is no second
execution path, because two paths to the same actions is how one of them
ends up missing the confirmation gate.
"""

from __future__ import annotations

from fleeting.services.assistant import SLASH_COMMANDS, parse_slash


# ---- parsing -------------------------------------------------------------


def test_a_known_command_parses() -> None:
    assert parse_slash("/task buy milk") == ("create_task", {"text": "buy milk"})


def test_the_leading_slash_is_required() -> None:
    assert parse_slash("task buy milk") is None


def test_a_bare_command_needs_an_argument() -> None:
    assert parse_slash("/task") is None


def test_the_argument_keeps_its_punctuation() -> None:
    """A task is 'email Priya, re: Q4 pricing' — commas are content."""
    assert parse_slash("/task email Priya, re: Q4 pricing") == (
        "create_task", {"text": "email Priya, re: Q4 pricing"}
    )


def test_find_becomes_a_search_term() -> None:
    assert parse_slash("/find router firmware") == ("find", {"query": "router firmware"})


def test_summarize_today_becomes_the_digest_tool() -> None:
    assert parse_slash("/summarize today") == ("generate_daily_digest", {"rolling": True})


def test_a_quoted_multi_word_argument_works() -> None:
    assert parse_slash('/find "bridge network"') == ("find", {"query": "bridge network"})


def test_an_unknown_command_is_not_a_command() -> None:
    assert parse_slash("/frobnicate the widget") is None


def test_a_command_that_is_not_at_the_start_is_not_a_command() -> None:
    assert parse_slash("what does /task mean") is None


def test_the_command_list_is_exposed_for_the_ui() -> None:
    assert {c["name"] for c in SLASH_COMMANDS} == {"task", "find", "log", "summarize"}


def test_every_command_carries_a_hint() -> None:
    assert all(c.get("hint") for c in SLASH_COMMANDS)


# ---- the same tool, the same gates ---------------------------------------


def test_a_slash_task_runs_through_the_normal_action_path(client) -> None:
    r = client.post("/api/assistant/chat", json={
        "messages": [{"role": "user", "content": "/task buy milk"}]
    })
    assert r.status_code == 200
    assert "[[task:" in r.json()["message"]["content"]


def test_the_confirmation_gate_lives_on_the_tool(client) -> None:
    """A slash command is routed through the same tools, so it inherits the
    gate — and a spelled-out destructive intent confirms identically."""
    note = client.post("/api/capture/text", json={"text": "a note"}).json()
    task = client.post("/api/tasks", json={"text": "doomed", "note_id": note["id"]}).json()

    spelled = client.post("/api/assistant/chat", json={
        "messages": [{"role": "user", "content": f"delete task {task['id']}"}],
    }).json()
    assert spelled["pending_action"]["tool"] == "delete_tasks"

    # /task is not destructive, so it runs immediately — proving the command
    # reaches the tool at all rather than short-circuiting somewhere safer.
    made = client.post("/api/assistant/chat", json={
        "messages": [{"role": "user", "content": "/task buy milk"}],
    }).json()
    assert made["pending_action"] is None


def test_slash_commands_endpoint_lists_them(client) -> None:
    r = client.get("/api/assistant/slash-commands")
    assert r.status_code == 200
    assert [c["name"] for c in r.json()] == ["task", "find", "log", "summarize"]
