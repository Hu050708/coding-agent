from __future__ import annotations

import os

from fastapi import APIRouter, Depends

from clearloop.api.dependencies import get_run_manager, get_settings
from clearloop.api.schemas import WorkspaceValidateRequest, WorkspaceValidateResponse
from clearloop.config import AppSettings
from clearloop.runs.run_manager import RunManager


router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.post("/validate", response_model=WorkspaceValidateResponse)
def validate_workspace(
    payload: WorkspaceValidateRequest,
    manager: RunManager = Depends(get_run_manager),
    settings: AppSettings = Depends(get_settings),
) -> dict[str, object]:
    workspace = manager.validate_workspace(payload.workspace)
    return {
        "valid": True,
        "workspace": os.fspath(workspace),
        "allowed_root": os.fspath(settings.allowed_root),
    }


__all__ = ["router"]
