"""Capture templates (#1) — tiny CRUD over templates.json."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..services import templates as tmpl

router = APIRouter(prefix="/api/templates", tags=["templates"])


class TemplateIn(BaseModel):
    type: str | None = Field(default=None, max_length=32)
    tags: list[str] = Field(default_factory=list)
    prompt: str | None = None
    mode: str | None = None


@router.get("")
def list_templates() -> dict[str, dict]:
    return tmpl.load_templates()


@router.put("")
def replace_templates(body: dict[str, TemplateIn], request: Request) -> dict:
    for name, t in body.items():
        if t.mode is not None and t.mode not in tmpl.OUTPUT_MODES:
            raise HTTPException(422, f"template '{name}': mode must be one of {', '.join(tmpl.OUTPUT_MODES)}")
    data = {name: t.model_dump(exclude_none=True) for name, t in body.items()}
    tmpl.save_templates(data)
    return data
