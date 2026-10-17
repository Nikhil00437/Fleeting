"""Vault endpoints: planning, conflicts and health.

Separate from `notes` because these are about the *mirror*, not about a note.
The distinction matters for a boring reason: `/api/notes/{id}` treats the first
path segment as an id, so anything vault-shaped filed under it collides with a
note called "vault".
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/vault", tags=["vault"])


@router.post("/dry-run")
def vault_dry_run(request: Request) -> dict:
    """#122: what the vault sync would do, without doing any of it.

    Computed fresh on every call rather than remembered from a previous one: a
    plan that recorded conclusions and applied them later is stale by the time it
    acts, and that window is the one that matters.
    """
    from ..services.vault_dryrun import plan_all

    st = request.app.state.st
    return plan_all(st.cfg.paths, st.db)


class ResolveIn(BaseModel):
    """#113. Three choices, and deliberately no text merge.

    A three-way merge needs the content before either side changed, which means
    storing a second copy of every note somewhere that is not the note. The sync
    log keeps a hash — enough to tell the sides apart, not enough to blend them.
    """

    resolution: str


@router.get("/conflicts")
def vault_conflicts_list(request: Request) -> dict:
    """Re-derived on every call rather than read from the log, so a conflict that
    was resolved last week does not stay on the list forever."""
    from ..services.vault_conflicts import detect

    st = request.app.state.st
    return {"conflicts": detect(st.cfg.paths, st.db)}


@router.post("/conflicts/{note_id}")
def vault_conflicts_resolve(note_id: str, body: ResolveIn, request: Request) -> dict:
    """Apply one resolution. Every outcome is audited: six months later, with no
    memory of enabling anything."""
    from ..services.vault_conflicts import resolve

    st = request.app.state.st
    try:
        return resolve(st.cfg.paths, st.db, note_id, body.resolution, bus=getattr(st, "bus", None))
    except LookupError as exc:
        raise HTTPException(404, {"error": "no_conflict", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(400, {"error": "unknown_resolution", "message": str(exc)}) from exc


class SchemaIn(BaseModel):
    """#114."""

    schema: str = ""


class FolderTemplateIn(BaseModel):
    """#115."""

    template: str = ""


@router.get("/frontmatter")
def vault_frontmatter(request: Request) -> dict:
    """The configured schema, what was rejected from it, and how many notes
    actually carry each field.

    The counts are the point of an editor: a field nothing has ever been filled
    in for is a field the user is maintaining for nothing.
    """
    from ..services.vault_layout import validate_schema

    st = request.app.state.st
    described = validate_schema(st.cfg.paths.vault_frontmatter_schema)
    populated: dict[str, int] = {name: 0 for name in described["fields"]}
    for note in st.db.list_notes(limit=2000):
        values = note.get("frontmatter") or {}
        if not isinstance(values, dict):
            continue
        for name in populated:
            if values.get(name):
                populated[name] += 1
    return {"schema": described, "populated": populated}


@router.put("/frontmatter")
def set_vault_frontmatter(body: SchemaIn, request: Request) -> dict:
    st = request.app.state.st
    st.cfg.paths.vault_frontmatter_schema = body.schema.strip()
    return vault_frontmatter(request)


@router.get("/folder/{note_id}")
def vault_folder_for(note_id: str, request: Request) -> dict:
    """Where this note's file lives, and which rule put it there."""
    from ..services.vault_layout import folder_for
    from ..services.markdown import vault_path_for

    st = request.app.state.st
    note = st.db.get_note(note_id)
    if not note:
        raise HTTPException(404, {"error": "no_such_note", "note_id": note_id})
    template = st.cfg.paths.vault_folder_template or ""
    return {
        "template": template or "{{year}}",
        "configured": bool(template),
        "folder": folder_for(template or "{{year}}", note),
        "year": str(note.get("created_at") or "")[:4] or "undated",
        "path": str(vault_path_for(st.cfg.paths, note)),
    }


@router.put("/folder-template")
def set_vault_folder_template(body: FolderTemplateIn, request: Request) -> dict:
    """Reject a template that would escape the vault, rather than sanitising it
    into something the user did not write."""
    from ..services.vault_layout import validate_template

    problem = validate_template(body.template)
    if problem:
        raise HTTPException(
            400, {"error": "unsafe_template", "message": problem, "template": body.template}
        )
    st = request.app.state.st
    st.cfg.paths.vault_folder_template = body.template.strip()
    return {"ok": True, "template": st.cfg.paths.vault_folder_template}


@router.get("/health")
def vault_health(request: Request) -> dict:
    """#118: is the vault in the state the app thinks it is?

    Read-only, and it repairs nothing. A health check that silently deleted
    orphans would be a second, un-audited destructive path — and "clean up my
    vault" is exactly the request that goes wrong while nobody is looking.
    """
    from ..services.vault_health import scan

    st = request.app.state.st
    return scan(st.cfg.paths, st.db)


@router.get("/attachments/{note_id}")
def vault_attachments_plan(note_id: str, request: Request) -> dict:
    """#120: what copying this note's attachments would do, before it does it."""
    from ..services.vault_attachments import plan

    st = request.app.state.st
    note = st.db.get_note(note_id)
    if not note:
        raise HTTPException(404, {"error": "no_such_note", "note_id": note_id})
    return plan(st.cfg.paths, st.db, note)


@router.post("/attachments/{note_id}")
def vault_attachments_copy(note_id: str, request: Request) -> dict:
    """Copy them. Idempotent — an unchanged file is left alone, because a vault
    full of touched files breaks every incremental tool the user owns."""
    from ..services.vault_attachments import copy_attachments

    st = request.app.state.st
    note = st.db.get_note(note_id)
    if not note:
        raise HTTPException(404, {"error": "no_such_note", "note_id": note_id})
    return copy_attachments(st.cfg.paths, st.db, note)


@router.get("/provenance")
def vault_provenance(request: Request) -> dict:
    """#473: how many notes came from where.

    Answered from the notes themselves rather than a maintained tally, so the
    counts cannot drift from what is actually there.
    """
    from ..services.provenance import SOURCES

    st = request.app.state.st
    counts = {name: 0 for name in SOURCES}
    for row in st.db.execute(
        "SELECT provenance, COUNT(*) c FROM notes WHERE trashed_at IS NULL GROUP BY provenance"
    ):
        counts[row["provenance"] or "text"] = row["c"]
    return {
        "counts": counts,
        "total": sum(counts.values()),
        "filter": "GET /api/notes?provenance=<name>",
    }


@router.get("/obsidian/{note_id}")
def vault_obsidian(note_id: str, request: Request) -> dict:
    """#134: the `obsidian://` URL that opens this note in Obsidian.

    Obsidian resolves by vault *name* and a path relative to it, so both are in
    the response and a mismatch is visible before anyone clicks a button that
    would silently do nothing.
    """
    from ..services.markdown import obsidian_uri

    st = request.app.state.st
    note = st.db.get_note(note_id)
    if not note:
        raise HTTPException(404, {"error": "no_such_note", "note_id": note_id})
    return obsidian_uri(st.cfg.paths, note)
