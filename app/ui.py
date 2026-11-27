"""Static training cockpit UI served at /ui/."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

UI_DIR = (Path(__file__).parent / "static" / "ui").resolve()

router = APIRouter(include_in_schema=False)


@router.get("/ui")
@router.get("/propuesta3")
@router.get("/propuesta3/")
def ui_redirect() -> RedirectResponse:
    return RedirectResponse("/ui/", status_code=307)


@router.get("/ui/{asset_path:path}")
def ui_asset(asset_path: str) -> FileResponse:
    if "\x00" in asset_path:
        raise HTTPException(404, "Asset not found")
    try:
        target = (UI_DIR / (asset_path or "index.html")).resolve()
    except (OSError, ValueError) as exc:
        raise HTTPException(404, "Asset not found") from exc
    if not target.is_relative_to(UI_DIR):
        raise HTTPException(404, "Asset not found")
    if target.is_dir():
        target = (target / "index.html").resolve()
        if not target.is_relative_to(UI_DIR):
            raise HTTPException(404, "Asset not found")
    if not target.is_file():
        raise HTTPException(404, "Asset not found")
    return FileResponse(target)
