from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).resolve().parent / "static"


def register_study_ui(app: FastAPI) -> None:
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def root_redirect():
        return RedirectResponse(url="/ui", status_code=302)

    @app.get("/ui", include_in_schema=False)
    def study_ui():
        return FileResponse(STATIC_DIR / "study.html", media_type="text/html; charset=utf-8")
