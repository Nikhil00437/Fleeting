"""Unit tests for smart Markdown parser and metadata formatter."""

from __future__ import annotations

import pytest
from fleeting.services.markdown import parse_note_md, render_note_md


def test_render_action_items_metadata_tags():
    note = {
        "id": "note-1",
        "type": "text",
        "title": "Tasks Note",
        "action_items": [
            {
                "id": "t1",
                "text": "Fix responsive navigation layout",
                "done": True,
                "priority": "P1",
                "due_date": "2026-10-05",
                "repo": "fleeting",
            },
            {
                "id": "t2",
                "text": "Add due date picker",
                "done": False,
                "priority": "P3",
                "due_date": "2026-10-10",
            },
            {
                "id": "t3",
                "text": "Default priority task",
                "done": False,
                "priority": "P2",
            },
        ],
    }
    md = render_note_md(note)
    assert "- [x] Fix responsive navigation layout [P1] [due:2026-10-05] [repo:fleeting]" in md
    assert "- [ ] Add due date picker [P3] [due:2026-10-10]" in md
    assert "- [ ] Default priority task" in md
    # P2 should be omitted by default to avoid visual clutter
    assert "[P2]" not in md


def test_parse_yaml_frontmatter():
    content = """---
id: test-uuid-123
type: text
created: 2026-10-02T12:00:00+00:00
app: fleeting
tags:
  - engineering
  - sync
source: https://example.com/spec
channel: tech
---

# Frontmatter Note

A summary paragraph.
"""
    parsed = parse_note_md(content)
    assert parsed["id"] == "test-uuid-123"
    assert parsed["type"] == "text"
    assert parsed["created"] == "2026-10-02T12:00:00+00:00"
    assert parsed["tags"] == ["engineering", "sync"]
    assert parsed["source"] == {"url": "https://example.com/spec", "channel": "tech"}
    assert parsed["title"] == "Frontmatter Note"
    assert parsed["summary"] == "A summary paragraph."


def test_parse_yaml_frontmatter_inline_tags():
    content = """---
id: inline-tags-note
tags: [alpha, beta, gamma]
---

# Inline Tags
"""
    parsed = parse_note_md(content)
    assert parsed["id"] == "inline-tags-note"
    assert parsed["tags"] == ["alpha", "beta", "gamma"]


def test_parse_title_extraction():
    content = """---
id: note-title
---

# The Real Title of the Note

Intro paragraph.

## Subheading Title Should Be Ignored
"""
    parsed = parse_note_md(content)
    assert parsed["title"] == "The Real Title of the Note"


def test_parse_summary_paragraphs():
    content = """# My Captured Note

First summary paragraph here.

Second summary paragraph with extra context.

## Action items
- [ ] First task
"""
    parsed = parse_note_md(content)
    assert parsed["title"] == "My Captured Note"
    assert parsed["summary"] == "First summary paragraph here.\n\nSecond summary paragraph with extra context."


def test_parse_action_items_checkbox_and_indentation():
    content = """# Checklist Test

## Action items
- [ ] Unchecked item
- [x] Checked lowercase item
- [X] Checked uppercase item
  - [ ] Indented with two spaces
\t- [x] Indented with tab
"""
    parsed = parse_note_md(content)
    items = parsed["action_items"]
    assert len(items) == 5
    assert items[0]["text"] == "Unchecked item"
    assert items[0]["done"] is False
    assert items[1]["text"] == "Checked lowercase item"
    assert items[1]["done"] is True
    assert items[2]["text"] == "Checked uppercase item"
    assert items[2]["done"] is True
    assert items[3]["text"] == "Indented with two spaces"
    assert items[3]["done"] is False
    assert items[4]["text"] == "Indented with tab"
    assert items[4]["done"] is True


def test_parse_action_items_metadata_tags_and_strip():
    content = """# Task Metadata Test

## Action items
- [x] Fix responsive navigation layout [P1] [repo:fleeting]
- [ ] Plan sprint [due:2026-10-15]
- [ ] Review PR [P3] [due:2026-10-20] [repo:backend]
- [ ] Ordinary task without tags
- [ ] Task with [P2] explicit [repo:frontend]
- [ ] Task preserving other brackets like [README] and [v1.0] [P1]
"""
    parsed = parse_note_md(content)
    items = parsed["action_items"]
    assert len(items) == 6

    # Item 1: P1, repo
    assert items[0]["text"] == "Fix responsive navigation layout"
    assert items[0]["done"] is True
    assert items[0]["priority"] == "P1"
    assert items[0]["due_date"] is None
    assert items[0]["repo"] == "fleeting"

    # Item 2: due_date, default priority P2
    assert items[1]["text"] == "Plan sprint"
    assert items[1]["done"] is False
    assert items[1]["priority"] == "P2"
    assert items[1]["due_date"] == "2026-10-15"
    assert items[1]["repo"] is None

    # Item 3: P3, due_date, repo
    assert items[2]["text"] == "Review PR"
    assert items[2]["done"] is False
    assert items[2]["priority"] == "P3"
    assert items[2]["due_date"] == "2026-10-20"
    assert items[2]["repo"] == "backend"

    # Item 4: defaults
    assert items[3]["text"] == "Ordinary task without tags"
    assert items[3]["done"] is False
    assert items[3]["priority"] == "P2"
    assert items[3]["due_date"] is None
    assert items[3]["repo"] is None

    # Item 5: explicit P2
    assert items[4]["text"] == "Task with explicit"
    assert items[4]["priority"] == "P2"
    assert items[4]["repo"] == "frontend"

    # Item 6: preserve non-metadata brackets
    assert items[5]["text"] == "Task preserving other brackets like [README] and [v1.0]"
    assert items[5]["priority"] == "P1"


def test_parse_content_and_transcript():
    content_note = """# Regular Note

Summary here.

## Content
Detailed body content.
Multiple lines of text.

### Nested Header
Code block:
```python
x = 1
```
"""
    parsed = parse_note_md(content_note)
    assert "Detailed body content." in parsed["raw_text"]
    assert "### Nested Header" in parsed["raw_text"]
    assert "```python" in parsed["raw_text"]

    voice_note = """# Voice Note

## Transcript
Spoken audio transcription text.
"""
    parsed_voice = parse_note_md(voice_note)
    assert parsed_voice["raw_text"] == "Spoken audio transcription text."


def test_parse_note_without_frontmatter_or_subheadings():
    # Only a heading and a paragraph
    content = """# Quick Thought

Just capturing an idea directly in Markdown without any YAML or subheadings.
"""
    parsed = parse_note_md(content)
    assert parsed["id"] is None
    assert parsed["type"] == "text"
    assert parsed["created"] == ""
    assert parsed["tags"] == []
    assert parsed["source"] == {}
    assert parsed["title"] == "Quick Thought"
    assert parsed["summary"] == "Just capturing an idea directly in Markdown without any YAML or subheadings."
    assert parsed["raw_text"] == ""
    assert parsed["action_items"] == []


def test_parse_note_plain_text_only():
    # Completely plain text (no title, no frontmatter, no subheadings)
    content = "Just raw unformatted thoughts typed into a text file."
    parsed = parse_note_md(content)
    assert parsed["id"] is None
    assert parsed["title"] == ""
    assert parsed["summary"] == ""
    assert parsed["raw_text"] == "Just raw unformatted thoughts typed into a text file."
    assert parsed["action_items"] == []


def test_roundtrip_render_and_parse():
    original = {
        "id": "roundtrip-uuid-456",
        "type": "text",
        "title": "Comprehensive Roundtrip",
        "summary": "This summary should survive serialization and deserialization intact.",
        "raw_text": "This is raw body content under the Content section.",
        "tags": ["sync", "obsidian", "fleeting"],
        "action_items": [
            {
                "id": "t1",
                "text": "High priority task",
                "done": False,
                "priority": "P1",
                "due_date": "2026-10-05",
                "repo": "fleeting",
            },
            {
                "id": "t2",
                "text": "Completed task with due date",
                "done": True,
                "priority": "P2",
                "due_date": "2026-10-08",
                "repo": None,
            },
            {
                "id": "t3",
                "text": "Low priority task",
                "done": False,
                "priority": "P3",
                "due_date": None,
                "repo": None,
            },
        ],
        "source": {"url": "https://fleeting.local", "channel": "main"},
        "created_at": "2026-10-02T12:00:00+00:00",
    }

    md = render_note_md(original)
    parsed = parse_note_md(md)

    assert parsed["id"] == original["id"]
    assert parsed["type"] == original["type"]
    assert parsed["created"] == original["created_at"]
    assert parsed["title"] == original["title"]
    assert parsed["summary"] == original["summary"]
    assert parsed["raw_text"] == original["raw_text"]
    assert parsed["tags"] == original["tags"]
    assert parsed["source"] == original["source"]

    assert len(parsed["action_items"]) == 3
    it1 = parsed["action_items"][0]
    assert it1["text"] == "High priority task"
    assert it1["done"] is False
    assert it1["priority"] == "P1"
    assert it1["due_date"] == "2026-10-05"
    assert it1["repo"] == "fleeting"

    it2 = parsed["action_items"][1]
    assert it2["text"] == "Completed task with due date"
    assert it2["done"] is True
    assert it2["priority"] == "P2"
    assert it2["due_date"] == "2026-10-08"
    assert it2["repo"] is None

    it3 = parsed["action_items"][2]
    assert it3["text"] == "Low priority task"
    assert it3["done"] is False
    assert it3["priority"] == "P3"
    assert it3["due_date"] is None
    assert it3["repo"] is None
