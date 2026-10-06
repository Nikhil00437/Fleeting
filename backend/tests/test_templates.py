"""#1 templates + #427 output modes."""

from __future__ import annotations

import json

import pytest

import fleeting.services.templates as tmpl


def test_output_modes():
    assert tmpl.apply_output_mode("hello there", "raw") == "hello there"
    cleaned = tmpl.apply_output_mode("um so like we should, uh, ship it", "cleaned")
    assert "um" not in cleaned.lower() and cleaned[0].isupper()
    bullets = tmpl.apply_output_mode("First thing. Second thing! Third?", "bullets")
    assert bullets == "- First thing.\n- Second thing!\n- Third?"
    with pytest.raises(ValueError):
        tmpl.apply_output_mode("x", "email")


def test_templates_file_roundtrip(tmp_path, monkeypatch):
    p = tmp_path / "templates.json"
    monkeypatch.setattr(tmpl, "TEMPLATES_PATH", p)
    assert tmpl.load_templates() == {}
    tmpl.save_templates({"idea": {"tags": ["idea"], "prompt": "p"}})
    assert tmpl.get_template("idea")["tags"] == ["idea"]


def test_capture_text_with_template_and_mode(client, tmp_path, monkeypatch):
    import fleeting.services.templates as t

    monkeypatch.setattr(t, "TEMPLATES_PATH", tmp_path / "templates.json")
    t.save_templates({"idea": {"type": "idea", "tags": ["idea"], "mode": "cleaned", "prompt": "Summarise as an idea"}})

    r = client.post("/api/capture/text", json={"text": "um app that, uh, does things", "template": "idea"})
    assert r.status_code == 200, r.text
    note = r.json()
    assert note["type"] == "idea"
    assert "idea" in note["tags"]
    assert "um" not in note["raw_text"].lower().split()
    assert note["source"]["template"]["prompt"] == "Summarise as an idea"


def test_unknown_template_rejected(client, tmp_path, monkeypatch):
    import fleeting.services.templates as t

    monkeypatch.setattr(t, "TEMPLATES_PATH", tmp_path / "templates.json")
    r = client.post("/api/capture/text", json={"text": "hello", "template": "nope"})
    assert r.status_code == 422


def test_bad_mode_rejected(client):
    r = client.post("/api/capture/text", json={"text": "hello", "mode": "email"})
    assert r.status_code == 422


def test_templates_api(client, tmp_path, monkeypatch):
    import fleeting.services.templates as t

    monkeypatch.setattr(t, "TEMPLATES_PATH", tmp_path / "templates.json")
    r = client.put("/api/templates", json={"bug": {"tags": ["bug"], "mode": "bullets"}})
    assert r.status_code == 200
    assert (tmp_path / "templates.json").exists()
    assert client.get("/api/templates").json()["bug"]["mode"] == "bullets"


# ---- #472 template fields -------------------------------------------------

def test_template_with_typed_fields_round_trips(client, tmp_path, monkeypatch):
    monkeypatch.setattr(tmpl, "TEMPLATES_PATH", tmp_path / "templates.json")
    body = {
        "review": {
            "type": "text",
            "fields": [
                {"name": "Rating", "type": "rating"},
                {"name": "Status", "type": "status", "options": ["to watch", "watched"]},
                {"name": "URL", "type": "url"},
                {"name": "Cost", "type": "cost"},
            ],
        }
    }
    client.put("/api/templates", json=body)
    stored = client.get("/api/templates").json()["review"]
    assert [f["name"] for f in stored["fields"]] == ["rating", "status", "url", "cost"]
    assert stored["fields"][1]["options"] == ["to watch", "watched"]


def test_template_field_validation(client, tmp_path, monkeypatch):
    monkeypatch.setattr(tmpl, "TEMPLATES_PATH", tmp_path / "templates.json")
    client.put(
        "/api/templates",
        json={"bad": {"fields": [{"name": "s", "type": "status"}]}},
    )
    # status without options is rejected, so the template must not have been saved
    assert "bad" not in client.get("/api/templates").json()

    client.put(
        "/api/templates",
        json={"bad2": {"fields": [{"name": "x", "type": "hologram"}]}},
    )
    assert "bad2" not in client.get("/api/templates").json()


def test_notes_carry_typed_fields_values(client, tmp_path, monkeypatch):
    """A note created from a template exposes source.template.name for the
    drawer to resolve the field schema; values live in note.fields."""
    monkeypatch.setattr(tmpl, "TEMPLATES_PATH", tmp_path / "templates.json")
    client.put(
        "/api/templates",
        json={"book": {"type": "text", "tags": ["reading"], "fields": [{"name": "rating", "type": "rating"}]}},
    )
    r = client.post("/api/capture/text", json={"text": "notes on a book", "template": "book"})
    assert r.status_code == 200
    note = r.json()
    assert note["source"]["template"]["name"] == "book"
    assert note["fields"] == {}

    patched = client.patch(f"/api/notes/{note['id']}", json={"fields": {"rating": 4}}).json()
    assert patched["fields"] == {"rating": 4}
