"""The one boundary for connector reads from the server's local disk.

Local reads are disabled until an operator names a root directory in
``GRC_LAKE_LAKE_LOCAL_ROOT``. In hosted mode the root is shared by the whole
server, so each tenant may read only its own ``<root>/<tenant_id>`` subtree.
Paths are resolved (symlinks and ``..`` included) before the check.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from security_lakehouse.execution_mode import in_server_mode, server_tenant_id
from security_lakehouse.runtime_environment import runtime_env

LOCAL_ROOT_ENV = "GRC_LAKE_LAKE_LOCAL_ROOT"


def confine_local_path(text: str, env: Mapping[str, str] | None, *, label: str) -> Path:
    """Resolve an absolute local path and require it to sit under the allowed root."""
    env = runtime_env(env)
    value = str(text or "").strip()
    if "\x00" in value or "://" in value or not value.startswith("/"):
        raise ValueError(f"local {label} paths must be absolute local paths")
    root = str(env.get(LOCAL_ROOT_ENV) or "").strip()
    if not root:
        raise ValueError(f"local {label} paths are disabled; set {LOCAL_ROOT_ENV} to the directory they may read")
    resolved = Path(value).resolve()
    allowed = Path(root).resolve()
    if in_server_mode(env):
        tenant_id = server_tenant_id()
        if not tenant_id or "/" in tenant_id or tenant_id in {".", ".."}:
            raise ValueError(f"local {label} paths in hosted mode need a tenant context")
        allowed = (allowed / tenant_id).resolve()
        if resolved != allowed and allowed not in resolved.parents:
            raise ValueError(f"local {label} path is outside this tenant's directory under {LOCAL_ROOT_ENV}")
        return resolved
    if resolved != allowed and allowed not in resolved.parents:
        raise ValueError(f"local {label} path is outside {LOCAL_ROOT_ENV}")
    return resolved
