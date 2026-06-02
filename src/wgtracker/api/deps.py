"""FastAPI dependencies: DB session, settings, and Basic-auth gate."""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session

from wgtracker.db.session import session_scope
from wgtracker.settings import Settings

_basic = HTTPBasic(auto_error=False)


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_session(request: Request) -> Iterator[Session]:
    factory = request.app.state.session_factory
    with session_scope(factory) as session:
        yield session


def require_ui_auth(
    request: Request,
    credentials: Annotated[HTTPBasicCredentials | None, Depends(_basic)],
) -> None:
    """Enforce Basic auth when configured; open for local dev when unset."""
    settings: Settings = request.app.state.settings
    user = settings.ui_basic_auth_user
    if not user:
        return  # auth disabled (no credentials configured)
    ok = (
        credentials is not None
        and secrets.compare_digest(credentials.username, user)
        and secrets.compare_digest(credentials.password, settings.ui_basic_auth_pass or "")
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )


SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
