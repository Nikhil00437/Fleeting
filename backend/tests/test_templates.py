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
