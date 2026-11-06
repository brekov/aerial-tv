"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import Depends, Request

from . import auth
from .config import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def require_device_dep(request: Request, settings: Settings = Depends(get_settings)) -> str:
    token = auth.provided_device_token(request)
    auth.require_device(settings, token)
    return token


def require_admin_dep(request: Request, settings: Settings = Depends(get_settings)) -> None:
    auth.require_admin(request, settings)
