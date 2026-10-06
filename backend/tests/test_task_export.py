"""#40 task export rendering."""

from __future__ import annotations

from fleeting.services.task_export import render_markdown, render_todo_txt


def make(**over) -> dict:
    base = {"id": "t1", "text": "write tests", "done": False, "priority": "P2", "due_date": None, "repo": None}
    base.update(over)
    return base


def test_todo_txt_one_line_per_task():
    out = render_todo_txt([make(id="a", text="first"), make(id="b", text="second")])
    assert out == "(A) first\n(A) second\n"


def test_todo_txt_marks_done_with_x():
    out = render_todo_txt([make(text="open")], [make(text="closed", done=True)])
    assert "x (A) closed" in out
    assert "(A) open" in out


def test_todo_txt_appends_due_dates():
    assert "@2026-10-09" in render_todo_txt([make(due_date="2026-10-09")])


def test_undated_work_sorts_above_dated_work():
    out = render_todo_txt([make(id="dated", text="later", due_date="2026-10-01"), make(id="anytime", text="anytime")])
    assert out.index("anytime") < out.index("later")


def test_markdown_groups_by_priority_with_checkboxes():
    tasks = [
        make(id="a", text="urgent thing", priority="P1"),
        make(id="b", text="normal thing", priority="P2"),
        make(id="c", text="later thing", priority="P3"),
    ]
    out = render_markdown(tasks, day="2026-10-06")
    assert out.startswith("# Tasks")
    assert "## P1" in out and "## P2" in out and "## P3" in out
    assert "- [ ] urgent thing" in out
    assert out.index("## P1") < out.index("## P2")


def test_markdown_records_repo_and_due_date():
    out = render_markdown([make(repo="fleeting", due_date="2026-10-09")], day="2026-10-06")
    assert "`#fleeting`" in out
    assert "_due 2026-10-09_" in out


def test_markdown_done_section_only_when_there_is_done_work():
    assert "## Done" not in render_markdown([make()], day="2026-10-06")
    assert "## Done" in render_markdown([], [make(text="shipped", done=True)], day="2026-10-06")


def test_empty_export_is_still_valid():
    assert render_todo_txt([]) == ""
    assert render_markdown([], day="2026-10-06").startswith("# Tasks")