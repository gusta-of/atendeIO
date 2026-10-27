from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse

from ..deps import get_container, session_token

router = APIRouter(include_in_schema=False)


def _authed(request: Request) -> bool:
    return get_container(request).auth.user_for_token(session_token(request)) is not None


@router.get("/")
def index(request: Request):
    if not _authed(request):
        return RedirectResponse("/login", status_code=303)
    return FileResponse(get_container(request).settings.static_dir / "index.html")


@router.get("/login")
def login_page(request: Request):
    if _authed(request):
        return RedirectResponse("/", status_code=303)
    return FileResponse(get_container(request).settings.static_dir / "login.html")
