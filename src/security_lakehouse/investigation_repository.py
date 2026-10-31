"""Attach bronze repository topology without joining different source accounts."""

from pathlib import Path

from security_lakehouse.domain_identity import source_asset_key
from security_lakehouse.event_identity import event_identity
from security_lakehouse.graph import _add_embedded_code_graph, _add_governance_signal, _add_repository_signal_paths
from security_lakehouse.io import canonical_sha256, iter_jsonl


def add_repository_context(lake: Path, node, edge, identity, evidence_by_event) -> None:
    for row in iter_jsonl(lake / "bronze/raw_events.jsonl", missing_ok=True, base_dir=lake):
        event = row.get("raw") or {}
        entity = event.get("entity") or {}
        event_type = str(event.get("event_type") or "")
        repo = str(entity.get("asset_id") or "")
        if not repo or not (event_type.startswith("repository.") or entity.get("asset_type") == "repository"):
            continue
        account, _ = source_asset_key({**event, "asset_id": repo})
        aid = identity("asset", account, repo)
        observed = {
            "source_account_id": account,
            "provider": event.get("source"),
            "owner": entity.get("asset_owner"),
            "environment": entity.get("environment"),
            "observed_at": event.get("event_time"),
        }
        node(
            "repository",
            aid,
            entity.get("repo") or repo,
            **observed,
            asset_id=repo,
            basis="Recorded repository observation; authenticated gaps stay explicit",
        )
        if environment := entity.get("environment"):
            env = node(
                "environment", identity("environment", account, environment), environment, source_account_id=account
            )
            edge(env, aid, "contains")
        evidence = event.get("evidence") or {}
        matching = evidence_by_event.get((account, event_identity(event), repo), [])
        if not matching:
            eid = node(
                "evidence",
                "bronze:" + canonical_sha256(event),
                event_type,
                **observed,
                evidence_id=evidence.get("evidence_id") or event.get("event_id"),
                evidence_ref=evidence.get("evidence_ref"),
                basis="Bronze observation; not an evaluated result",
            )
            edge(eid, aid, "evidence_covers_asset")

        def mapped(raw_id, aid=aid, repo=repo, account=account):
            return aid if raw_id == repo else identity("repo_context", account, repo, raw_id)

        def add_node(raw_id, kind, label, mapped=mapped, observed=observed, **extra):
            node(kind, mapped(raw_id), label, **{**observed, **extra})

        def add_edge(source, target, kind, mapped=mapped):
            edge(mapped(source), mapped(target), kind)

        attributes = event.get("attributes") or {}
        if event_type == "repository.code_graph":
            _add_embedded_code_graph(repo, attributes, add_node, add_edge)
        elif event_type.startswith("repository.governance."):
            _add_governance_signal(repo, event_type, attributes, add_node, add_edge)
        elif event_type == "repository.authenticated_signal_gap":
            gap = repo + ":gap"
            add_node(
                gap,
                "signal_gap",
                "Authenticated evidence unavailable",
                basis="Public repository access does not establish private governance settings",
            )
            add_edge(repo, gap, "has_signal")
        else:
            _add_repository_signal_paths(repo, event_type, attributes, add_node, add_edge)
