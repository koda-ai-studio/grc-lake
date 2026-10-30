"""Connection primitives must not import their API or scheduling callers."""

import ast
from pathlib import Path


def test_connection_dependencies_do_not_point_back_to_callers():
    root = Path(__file__).parents[1] / "src/security_lakehouse"
    forbidden = {
        "connection_api": {"api_v1"},
        "api_contract": {"connection_api"},
        "connection_registry": {"connector_state", "connections", "connector_runner"},
        "connection_inputs": {"connections", "connector_runner", "lake_eval"},
        "connector_state": {"connections", "connection_inputs"},
        "connections": {"scheduler"},
    }
    for module, callers in forbidden.items():
        tree = ast.parse((root / f"{module}.py").read_text())
        imports = {n.module.rsplit(".", 1)[-1] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert not imports & callers, (module, imports & callers)
