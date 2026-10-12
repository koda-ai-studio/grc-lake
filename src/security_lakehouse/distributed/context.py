"""Request-local workspace and transaction; copied into FastAPI worker threads."""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection


@dataclass(frozen=True)
class WorkspaceBinding:
    tenant_id: str
    path: Path
    connection: Connection | None = None
    owner: str | None = None
    fence: int | None = None
    check_active: Callable[[], None] | None = None


binding: ContextVar[WorkspaceBinding | None] = ContextVar("distributed_workspace", default=None)


def check_write_lease() -> None:
    """Cooperative cancellation only; the database fence still owns publication."""
    workspace = binding.get()
    if workspace is not None and workspace.check_active is not None:
        workspace.check_active()
