"""Static design proposals for the study UI (served at /propuesta1..3)."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

STATIC_DIR = Path(__file__).parent / "static"
PROPOSALS = ("propuesta1", "propuesta2", "propuesta3")

router = APIRouter(include_in_schema=False)


@router.get("/propuestas")
def proposals_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "propuestas.html")


@router.get("/propuesta{number}")
def proposal_redirect(number: int) -> RedirectResponse:
    if f"propuesta{number}" not in PROPOSALS:
        raise HTTPException(404, "Proposal not found")
    return RedirectResponse(f"/propuesta{number}/", status_code=307)


@router.get("/propuesta{number}/{asset_path:path}")
def proposal_asset(number: int, asset_path: str) -> FileResponse:
    name = f"propuesta{number}"
    if name not in PROPOSALS:
        raise HTTPException(404, "Proposal not found")
    base = (STATIC_DIR / name).resolve()
    target = (base / (asset_path or "index.html")).resolve()
    if not target.is_relative_to(base):
        raise HTTPException(404, "Asset not found")
    if target.is_dir():
        target = target / "index.html"
    if not target.is_file() or target.name == "DESIGN.md":
        raise HTTPException(404, "Asset not found")
    return FileResponse(target)
