"""Vault Router — search, get, propose, reindex endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.infrastructure.auth import require_auth
from app.services.vault_indexer_service import get_vault_indexer
from app.services.vault_retrieval_service import get_vault_retrieval
from app.services.vault_writer_service import get_vault_writer

router = APIRouter(
    prefix="/api/vault",
    tags=["vault"],
    dependencies=[Depends(require_auth)],
)


class VaultSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    partitions: Optional[list[str]] = Field(
        default=None,
        description="Filter to: reference|projects|journal|inbox. Empty = all.",
    )
    top_k: int = Field(default=10, ge=1, le=50)


class VaultProposeRequest(BaseModel):
    relative_path: str = Field(..., description="Path under 00_Meta/_agent/**")
    content: str
    source: str = "agent"


@router.get("/status")
async def status():
    indexer = get_vault_indexer()
    writer = get_vault_writer()
    return {
        "vault_available": indexer.available(),
        "vault_path": str(indexer._root),
        "writer_available": writer.available(),
    }


@router.post("/search")
async def search(req: VaultSearchRequest):
    svc = get_vault_retrieval()
    return await svc.search(req.query, partitions=req.partitions, top_k=req.top_k)


@router.get("/file")
async def get_file(path: str):
    svc = get_vault_retrieval()
    result = await svc.get_file(path)
    if not result.get("exists"):
        raise HTTPException(404, f"No indexed chunks for path: {path}")
    return result


@router.post("/propose")
async def propose_write(req: VaultProposeRequest):
    """Free-write into 00_Meta/_agent/** namespace. Other paths must use cyanheads MCP."""
    writer = get_vault_writer()
    if not writer.available():
        raise HTTPException(503, "vault unavailable")
    try:
        return writer.write_agent_file(
            req.relative_path, req.content, source=req.source
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/reindex")
async def reindex(force: bool = False, max_files: int = 500):
    indexer = get_vault_indexer()
    if not indexer.available():
        raise HTTPException(503, "vault unavailable")
    return await indexer.reindex(force=force, max_files=max_files)
