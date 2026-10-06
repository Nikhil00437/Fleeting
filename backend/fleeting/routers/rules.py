"""Auto-filing rules (#272) — CRUD + on-demand backfill run."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..db import Database

router = APIRouter(prefix="/api/rules", tags=["rules"])


class RuleIn(BaseModel):
    match_field: str = Field(pattern="^(tag|type|title)$")
    match_value: str = Field(min_length=1, max_length=120)
    action: str = Field(pattern="^(add_tag|star|archive|set_color|add_to_collection)$")
    action_value: str | None = Field(default=None, max_length=200)


class RuleEnabledIn(BaseModel):
    enabled: bool


@router.get("")
def list_rules(request: Request) -> list[dict]:
    return request.app.state.st.db.filing_rules()


@router.post("")
def create_rule(body: RuleIn, request: Request) -> dict:
    st = request.app.state.st
    try:
        rule = st.db.insert_filing_rule(
            body.match_field, body.match_value, body.action, body.action_value
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return rule


@router.post("/{rule_id}/enabled")
def toggle_rule(rule_id: int, body: RuleEnabledIn, request: Request) -> dict:
    st = request.app.state.st
    if not st.db.set_filing_rule_enabled(rule_id, body.enabled):
        raise HTTPException(404, "rule not found")
    return {"ok": True, "id": rule_id, "enabled": body.enabled}


@router.delete("/{rule_id}")
def delete_rule(rule_id: int, request: Request) -> dict:
    st = request.app.state.st
    if not st.db.delete_filing_rule(rule_id):
        raise HTTPException(404, "rule not found")
    return {"ok": True, "id": rule_id}


@router.post("/run")
def run_rules(request: Request) -> dict:
    """Apply every enabled rule to every non-trashed note, then report.

    Rules are idempotent, so this is safe to re-run after editing them; it is
    the backfill path for rules created after the notes existed.
    """
    st = request.app.state.st
    changed = 0
    for note in st.db.list_notes(limit=500):
        _updated, filed = st.db.apply_filing_rules(note)
        if filed:
            changed += 1
    st.bus.publish("collections.changed", {"action": "rules-run"})
    return {"ok": True, "changed": changed}
