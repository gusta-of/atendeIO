from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool

from ..deps import COOKIE, current_user, get_container, session_token
from ..schemas import Credentials

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_cookie(request: Request, response: Response, token: str) -> None:
    cfg = get_container(request).settings
    response.set_cookie(COOKIE, token, max_age=cfg.session_ttl_s, httponly=True,
                        samesite="strict", secure=cfg.cookie_secure, path="/")


@router.post("/register")
async def register(body: Credentials, request: Request, response: Response):
    username, token = await run_in_threadpool(get_container(request).auth.register,
                                              body.username, body.password)
    _set_cookie(request, response, token)
    return {"username": username}


@router.post("/login")
async def login(body: Credentials, request: Request, response: Response):
    ip = request.client.host if request.client else "?"
    username, token = await run_in_threadpool(get_container(request).auth.login,
                                              body.username, body.password, ip)
    _set_cookie(request, response, token)
    return {"username": username}


@router.post("/logout")
def logout(request: Request, response: Response):
    get_container(request).auth.logout(session_token(request))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return {"username": user["username"]}


@router.get("/config")
def config(request: Request):
    return {"signup": get_container(request).settings.allow_signup}
