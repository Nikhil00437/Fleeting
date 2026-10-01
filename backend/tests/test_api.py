"""End-to-end API tests: capture → heuristic enrich → search → tasks."""

from __future__ import annotations

from conftest import wait_done


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["db"] is True


def test_text_capture_full_pipeline(client):
    r = client.post(
        "/api/capture/text",
        json={"text": "todo: water the plants tomorrow. The balcony tomatoes are ripening."},
    )
    assert r.status_code == 200
    note = r.json()
    assert note["status"] == "pending"
    assert note["type"] == "text"

    note = wait_done(client, note["id"])
    assert note["status"] == "done", note.get("error")
    assert note["title"], "heuristic must produce a title"
    assert note["source"]["enrichment"] == "heuristic"
    assert any("water the plants" in t["text"].lower() for t in note["action_items"])


def test_youtube_url_in_text_routes_to_youtube(client, monkeypatch):
    # don't let the background worker hit the network
    monkeypatch.setattr(client.app.state.st.processor, "enqueue", lambda _id: None)
    r = client.post(
        "/api/capture/text",
        json={"text": "https://www.youtube.com/watch?v=aircAruvnKk"},
    )
    assert r.status_code == 200
    note = r.json()
    assert note["type"] == "youtube"
    assert note["source"]["url"].startswith("https://youtu.be/")


def test_youtube_invalid_url_rejected(client):
    r = client.post("/api/capture/youtube", json={"url": "https://vimeo.com/12345"})
    assert r.status_code == 422


def test_empty_capture_rejected(client):
    r = client.post("/api/capture/text", json={"text": "   "})
    assert r.status_code == 422


def test_search_finds_content(client):
    client.post("/api/capture/text", json={"text": "quantum entanglement notes for the physics seminar"})
    r = client.get("/api/search", params={"q": "quantum"})
    assert r.status_code == 200
    results = r.json()
    assert len(results) == 1
    assert "[[quantum]]" in (results[0].get("snippet") or "").lower() or "quantum" in results[0]["raw_text"].lower()


def test_search_empty_query(client):
    assert client.get("/api/search", params={"q": "  "}).json() == []


def test_pin_archive_delete(client):
    note = client.post("/api/capture/text", json={"text": "pin me"}).json()
    wait_done(client, note["id"])

    assert client.post(f"/api/notes/{note['id']}/pin").json()["pinned"] is True
    assert client.post(f"/api/notes/{note['id']}/archive").json()["archived"] is True
    assert client.get("/api/notes", params={"archived": False}).json() == []
    assert client.delete(f"/api/notes/{note['id']}").json()["ok"] is True
    assert client.get(f"/api/notes/{note['id']}").status_code == 404


def test_task_completion_updates_tasks(client):
    note = client.post(
        "/api/capture/text",
        json={"text": "todo: book dentist appointment"},
    ).json()
    note = wait_done(client, note["id"])
    assert note["action_items"], "todo line must become an action item"

    tasks = client.get("/api/tasks").json()
    assert any(t["note_id"] == note["id"] and t.get("done") is False for t in tasks)

    items = [{**it, "done": True} for it in note["action_items"]]
    updated = client.patch(f"/api/notes/{note['id']}", json={"action_items": items}).json()
    assert all(it["done"] for it in updated["action_items"])
    assert client.get("/api/tasks").json() == []
    all_tasks = client.get("/api/tasks", params={"include_done": True}).json()
    assert any(t["note_id"] == note["id"] and t.get("done") is True for t in all_tasks)


def test_tags_endpoint(client):
    note = client.post("/api/capture/text", json={"text": "kubernetes networking deep dive"}).json()
    wait_done(client, note["id"])
    client.patch(f"/api/notes/{note['id']}", json={"tags": ["k8s", "networking"]})
    tags = {t["tag"]: t["count"] for t in client.get("/api/tags").json()}
    assert tags.get("k8s") == 1


def test_vault_export_and_removal(client, tmp_path):
    note = client.post("/api/capture/text", json={"text": "vault mirror test"}).json()
    wait_done(client, note["id"])
    vault = tmp_path / "vault"
    files = list(vault.rglob("*.md"))
    assert len(files) == 1, "done note must be mirrored to the vault"

    client.delete(f"/api/notes/{note['id']}")
    assert list(vault.rglob("*.md")) == [], "deleting a note removes its markdown"


def test_vault_export_disabled(client, tmp_path, monkeypatch):
    r = client.put("/api/settings", json={"vault_sync": False})
    assert r.status_code == 200
    note = client.post("/api/capture/text", json={"text": "no vault for me"}).json()
    wait_done(client, note["id"])
    assert list((tmp_path / "vault").rglob("*.md")) == []
    # export endpoint refuses when sync is off
    assert client.post(f"/api/notes/{note['id']}/export").status_code == 400


def test_settings_roundtrip_and_persistence(client, tmp_path):
    body = client.put(
        "/api/settings",
        json={"transcribe_model": "small", "yt_max_duration_min": 90},
    ).json()
    assert body["transcribe_model"] == "small"
    assert body["yt_max_duration_min"] == 90
    # config.toml persisted
    assert (tmp_path / "config.toml").exists()
    content = (tmp_path / "config.toml").read_text()
    assert "small" in content

    r = client.put("/api/settings", json={"transcribe_model": "bogus"})
    assert r.status_code == 422


def test_event_bus_fanout():
    """SSE streaming itself is verified manually (TestClient can't read
    infinite streams); the bus is what's worth unit-testing."""
    import asyncio

    from fleeting.events import EventBus, sse_format

    async def run():
        bus = EventBus()
        q = bus.subscribe()
        bus.publish("note.updated", {"id": "x"})
        payload = await asyncio.wait_for(q.get(), timeout=1)
        assert '"note.updated"' in payload and '"x"' in payload
        bus.unsubscribe(q)
        bus.publish("note.updated", {"id": "y"})  # no subscribers — must not raise
        assert sse_format(payload).startswith("data: ")

    asyncio.run(run())


def test_stats_counts(client):
    before = client.get("/api/stats").json()
    note = client.post("/api/capture/text", json={"text": "stats test"}).json()
    wait_done(client, note["id"])
    after = client.get("/api/stats", params={"days": 14}).json()
    assert after["total"] == before["total"] + 1
    assert after["today"] == before["today"] + 1
    assert len(after["notes_per_day"]) == 14
    assert after["by_type"]["text"] >= 1


def test_whisper_progress_and_test_endpoint(client, monkeypatch):
    s = client.get("/api/settings").json()
    assert "transcribe_cached_models" in s
    assert isinstance(s["transcribe_cached_models"], list)
    assert "transcribe_progress" in s
    assert s["transcribe_progress"]["status"] in ("idle", "downloading", "loading", "ready", "error")

    st = client.app.state.st

    def fake_transcribe_wav(wav_path, language=None):
        st.transcriber._emit_progress(
            status="downloading",
            model=st.cfg.transcribe.model,
            percent=45,
            downloaded_bytes=10 * 1024 * 1024,
            total_bytes=22 * 1024 * 1024,
            speed_bps=5 * 1024 * 1024,
            detail="Downloading weights…",
        )
        st.transcriber.loaded_model_size = st.cfg.transcribe.model
        st.transcriber._emit_progress(
            status="ready",
            model=st.cfg.transcribe.model,
            percent=100,
            downloaded_bytes=22 * 1024 * 1024,
            total_bytes=22 * 1024 * 1024,
            speed_bps=0.0,
            detail="Ready",
        )
        return {"text": "", "duration": 1.0, "language": "en"}

    monkeypatch.setattr(st.transcriber, "transcribe_wav", fake_transcribe_wav)
    r = client.post("/api/settings/test-whisper")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    after_s = client.get("/api/settings").json()
    assert after_s["transcribe_progress"]["status"] == "ready"
    assert after_s["transcribe_progress"]["percent"] == 100


