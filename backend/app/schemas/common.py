"""Common reusable API schemas."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class StatusMessageResponse(BaseModel):
    """Standard response carrying a status and optional message."""

    model_config = ConfigDict(extra="allow")

    status: str
    message: Optional[str] = None


class ErrorResponse(BaseModel):
    """Standard error response shape used by existing workflow-style results."""

    model_config = ConfigDict(extra="allow")

    status: str = "error"
    message: str
    details: Optional[Any] = None
