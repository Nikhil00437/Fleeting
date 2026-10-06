"""Capture templates (#1) — tiny CRUD over templates.json."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..services import templates as tmpl

router = APIRouter(prefix="/api/templates", tags=["templates"])
profiles_router = APIRouter(prefix="/api/profiles", tags=["profiles"])


class TemplateIn(BaseModel):
    type: str | None = Field(default=None, max_length=32)
    tags: list[str] = Field(default_factory=list)
    prompt: str | None = None
    mode: str | None = None
    # #472: typed custom fields rendered on notes created from this template.
    fields: list[dict] | None = None


@router.get("")
def list_templates() -> dict[str, dict]:
    return tmpl.load_templates()


@router.put("")
def replace_templates(body: dict[str, TemplateIn], request: Request) -> dict:
    data: dict[str, dict] = {}
    for name, t in body.items():
        if t.mode is not None and t.mode not in tmpl.OUTPUT_MODES:
            raise HTTPException(422, f"template '{name}': mode must be one of {', '.join(tmpl.OUTPUT_MODES)}")
        entry = t.model_dump(exclude_none=True)
        try:
            fields = tmpl.validate_template_fields(t.fields)
        except ValueError as exc:
            raise HTTPException(422, f"template '{name}': {exc}") from exc
        if fields is not None:
            entry["fields"] = fields
        data[name] = entry
    tmpl.save_templates(data)
    return data


@profiles_router.get("")
def list_profiles() -> dict[str, dict]:
    from ..services import profiles as prof

    return prof.load_profiles()


@profiles_router.put("")
def replace_profiles(body: dict) -> dict:
    from ..services import profiles as prof

    if not all(isinstance(v, dict) for v in body.values()):
        raise HTTPException(422, "each profile must be an object")
    prof.save_profiles(body)
    return body
