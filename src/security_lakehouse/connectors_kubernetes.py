"""Kubernetes configuration-baseline evidence collector (read-only).

Reads cluster configuration with ``list`` calls only and emits it in the lake's
raw evidence shape:

* ``kubernetes.rbac.cluster_admin_binding`` — (Cluster)RoleBindings granting the
  ``cluster-admin`` ClusterRole (CIS Kubernetes Benchmark v1.10 5.1.1).
* ``kubernetes.workload.pod_security`` — privileged containers, hostPath
  volumes, host namespaces, root users, privilege escalation (CIS 5.2.2-5.2.7,
  5.2.12).
* ``kubernetes.namespace.network_policy`` — namespaces without any
  NetworkPolicy (CIS 5.3.2).
* ``kubernetes.workload.image_registry`` — image sources and unpinned tags.
* ``kubernetes.workload.secret_env`` — Secrets injected as environment
  variables (CIS 5.4.1). Secret objects are never listed or read.
* ``kubernetes.cluster.audit_logging`` — kube-apiserver audit flags (CIS
  1.2.16 / 3.2.1), only when the apiserver runs as a visible static pod. Managed
  control planes (EKS, GKE, AKS) do not expose it, so no event is emitted there
  rather than guessing either way.
* ``kubernetes.workload.accelerator_inventory`` — workloads requesting GPUs
  (``nvidia.com/gpu``, ``amd.com/gpu``) or InfiniBand (``rdma/ib``), with the
  serving runtime and the namespace's NetworkPolicy count. Inventory only: it
  is ``observed``, never a pass or a failure.
* ``kubernetes.service.network_exposure`` — LoadBalancer and NodePort Services,
  judged from the address the cluster assigned and ``loadBalancerSourceRanges``;
  bound to the CCF network safeguard.
* ``kubernetes.inference.network_exposure`` — KServe InferenceServices
  (``serving.kserve.io/v1beta1``): cluster-local endpoints pass; an external URL
  is ``not_evaluated`` because endpoint authentication is not visible through
  the Kubernetes API.

GPU and InfiniBand resource names follow the NVIDIA device plugin and the
CoreWeave and Nebius GPU documentation, so the same evidence comes from CoreWeave
Kubernetes Service, Nebius Managed Kubernetes, and any cluster running those
plugins. Services and InferenceServices are optional reads: a 403 becomes a
coverage-gap row instead of failing the sync, and a cluster without KServe (404)
has no InferenceServices.

CIS check numbers follow the CIS Kubernetes Benchmark v1.10 as encoded in
aquasecurity/kube-bench ``cfg/cis-1.10``. Object shapes follow the Kubernetes
API reference (core/v1 Pod, apps/v1, batch/v1, rbac.authorization.k8s.io/v1,
networking.k8s.io/v1; current docs v1.37).

:class:`KubernetesClient` uses the official ``kubernetes`` Python client
(kubernetes-client/python, verified against v36.0.3), installed through the
``kubernetes`` extra. It authenticates from a kubeconfig (optionally a named
context) or the in-cluster service account, pages every list with
``limit``/``_continue``, retries 429/5xx honoring ``Retry-After``, and converts
responses with ``ApiClient.sanitize_for_serialization`` so records carry the
same camelCase JSON as ``kubectl get -o json`` — which is what the fixtures
hold. The API server is the operator-configured cluster endpoint (usually a
private address), so the public-address egress guard used for SaaS APIs does
not apply here.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import urllib.parse
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from security_lakehouse.connector_errors import CollectionGapError, ConnectorConfigError
from security_lakehouse.ingestion import backoff
from security_lakehouse.ingestion.paginate import object_rows, paginate
from security_lakehouse.io import read_json
from security_lakehouse.models import utc_iso

SOURCE = "kubernetes"
PAGE_LIMIT = 500
CLUSTER_ADMIN_ROLE = "cluster-admin"
DOCKER_HUB = "docker.io"
SYSTEM_NAMESPACES = frozenset({"kube-system", "kube-public", "kube-node-lease"})

# Controls verified to exist in controls/catalog.json.
RBAC_CONTROLS = ["FEDRAMP-AC-6", "FEDRAMP-AC-6.5", "CMMC-3.1.5", "SOC2-CC6.3", "ISO27001-A.8.2", "NIST-CSF-PR.AA-05"]
POD_SECURITY_CONTROLS = [
    "FEDRAMP-CM-6",
    "FEDRAMP-CM-7",
    "CMMC-3.4.2",
    "CMMC-3.4.6",
    "ISO27001-A.8.9",
    "CIS-CONTROLS-4",
    "NIST-CSF-PR.PS-01",
]
NETWORK_POLICY_CONTROLS = ["FEDRAMP-SC-7", "CMMC-3.13.1", "ISO27001-A.8.22"]
IMAGE_REGISTRY_CONTROLS = ["FEDRAMP-CM-7.5", "NIST-CSF-PR.PS-05", "CIS-CONTROLS-2"]
SECRET_ENV_CONTROLS = ["FEDRAMP-SC-28", "CMMC-3.13.16", "NIST-CSF-PR.DS-01"]
AUDIT_LOGGING_CONTROLS = [
    "FEDRAMP-AU-2",
    "FEDRAMP-AU-12",
    "CMMC-3.3.1",
    "ISO27001-A.8.15",
    "NIST-CSF-PR.PS-04",
    "CIS-CONTROLS-8",
]

# Every tag is in SG-NETWORK-001's crosswalk; the CCF assessment reads the
# safeguard binding, never these hints.
NETWORK_EXPOSURE_CONTROLS = ["FEDRAMP-SC-7", "NIST-800-53-SC-7", "CMMC-3.13.6", "NIST-CSF-PR.IR-01"]
NETWORK_SAFEGUARD = "SG-NETWORK-001"
ACCELERATOR_INVENTORY_CONTROLS = ["NIST-CSF-ID.AM-02", "NIST-800-53-CM-8", "FEDRAMP-CM-8"]

GPU_RESOURCES = ("nvidia.com/gpu", "amd.com/gpu")
INFINIBAND_RESOURCE = "rdma/ib"
NIM_IMAGE_PREFIX = "nvcr.io/nim/"
KSERVE_GROUP = "serving.kserve.io"
KSERVE_VERSION = "v1beta1"
KSERVE_PLURAL = "inferenceservices"
# KServe pkg/constants: the label and domain that keep an InferenceService off
# the external ingress gateway.
KSERVE_VISIBILITY_LABEL = "networking.kserve.io/visibility"
KSERVE_CLUSTER_LOCAL = "cluster-local"
CLUSTER_LOCAL_DOMAIN = ".svc.cluster.local"
EXPOSED_SERVICE_TYPES = ("LoadBalancer", "NodePort")

# kind -> (API path prefix, plural). Pod templates are evaluated on the
# controller that owns them; controller-owned ReplicaSets/Jobs/Pods are skipped
# so one workload is never counted twice.
WORKLOAD_KINDS: dict[str, tuple[str, str]] = {
    "Deployment": ("/apis/apps/v1", "deployments"),
    "DaemonSet": ("/apis/apps/v1", "daemonsets"),
    "StatefulSet": ("/apis/apps/v1", "statefulsets"),
    "ReplicaSet": ("/apis/apps/v1", "replicasets"),
    "CronJob": ("/apis/batch/v1", "cronjobs"),
    "Job": ("/apis/batch/v1", "jobs"),
    "Pod": ("/api/v1", "pods"),
}
_HIGH_FINDINGS = {
    "privileged_container",
    "host_path_volume",
    "host_network",
    "host_pid",
    "host_ipc",
    "unsafe_added_capability",
}
_BASELINE_CAPABILITIES = {
    "AUDIT_WRITE",
    "CHOWN",
    "DAC_OVERRIDE",
    "FOWNER",
    "FSETID",
    "KILL",
    "MKNOD",
    "NET_BIND_SERVICE",
    "SETFCAP",
    "SETGID",
    "SETPCAP",
    "SETUID",
    "SYS_CHROOT",
}
_AUDIT_POLICY_FLAG = "--audit-policy-file"
_AUDIT_SINK_FLAGS = ("--audit-log-path", "--audit-webhook-config-file")


class KubernetesClient:
    """Read-only Kubernetes API client built on the official Python client."""

    def __init__(
        self,
        cluster_name: str,
        *,
        context: str | None = None,
        kubeconfig_path: str | None = None,
        in_cluster: bool = False,
        apis: Mapping[str, Any] | None = None,
        serialize: Callable[[Any], Any] | None = None,
    ) -> None:
        self.cluster_name = cluster_name
        if apis is None:
            apis, serialize = _default_apis(context=context, kubeconfig_path=kubeconfig_path, in_cluster=in_cluster)
        self._apis = apis
        self._serialize = serialize or (lambda obj: obj)

    def cluster_role_bindings(self) -> list[dict[str, Any]]:
        return self._list("rbac", "list_cluster_role_binding")

    def role_bindings(self) -> list[dict[str, Any]]:
        return self._list("rbac", "list_role_binding_for_all_namespaces")

    def namespaces(self) -> list[dict[str, Any]]:
        return self._list("core", "list_namespace")

    def network_policies(self) -> list[dict[str, Any]]:
        return self._list("networking", "list_network_policy_for_all_namespaces")

    def pods(self) -> list[dict[str, Any]]:
        return _with_kind(self._list("core", "list_pod_for_all_namespaces"), "Pod", "v1")

    def workloads(self) -> list[dict[str, Any]]:
        return [
            *_with_kind(self._list("apps", "list_deployment_for_all_namespaces"), "Deployment", "apps/v1"),
            *_with_kind(self._list("apps", "list_daemon_set_for_all_namespaces"), "DaemonSet", "apps/v1"),
            *_with_kind(self._list("apps", "list_stateful_set_for_all_namespaces"), "StatefulSet", "apps/v1"),
            *_with_kind(self._list("apps", "list_replica_set_for_all_namespaces"), "ReplicaSet", "apps/v1"),
            *_with_kind(self._list("batch", "list_cron_job_for_all_namespaces"), "CronJob", "batch/v1"),
            *_with_kind(self._list("batch", "list_job_for_all_namespaces"), "Job", "batch/v1"),
        ]

    def apiserver_pods(self) -> list[dict[str, Any]]:
        return self._list(
            "core", "list_namespaced_pod", namespace="kube-system", label_selector="component=kube-apiserver"
        )

    def services(self) -> list[dict[str, Any]]:
        return self._optional(
            "services", "list services", lambda: self._list("core", "list_service_for_all_namespaces")
        )

    def inference_services(self) -> list[dict[str, Any]]:
        def read() -> list[dict[str, Any]]:
            return self._list(
                "custom", "list_cluster_custom_object", group=KSERVE_GROUP, version=KSERVE_VERSION, plural=KSERVE_PLURAL
            )

        return self._optional(
            "inference_services", f"list {KSERVE_PLURAL}.{KSERVE_GROUP}", read, missing_means_empty=True
        )

    @staticmethod
    def _optional(
        collection: str,
        permission: str,
        read: Callable[[], list[dict[str, Any]]],
        *,
        missing_means_empty: bool = False,
    ) -> list[dict[str, Any]]:
        try:
            return read()
        except Exception as exc:
            status = getattr(exc, "status", None)
            if status == 404 and missing_means_empty:
                # The CRD is not installed, so the cluster has none of these objects.
                return []
            if status in (401, 403):
                raise CollectionGapError(
                    f"Kubernetes {collection} were not collected (permission denied)",
                    collection=collection,
                    reason="permission_denied",
                    permission=permission,
                ) from None
            raise

    def _list(self, api: str, method: str, **kwargs: Any) -> list[dict[str, Any]]:
        call = getattr(self._apis[api], method)

        def fetch_page(token: str | None) -> dict[str, Any]:
            params = {**kwargs, "limit": PAGE_LIMIT, **({"_continue": token} if token else {})}
            raw = backoff.retry(
                lambda: call(**params),
                is_retryable=_is_retryable_api_error,
                retry_after=_api_retry_after,
            )
            page = self._serialize(raw)
            if not isinstance(page, dict):
                raise ValueError("Kubernetes collection incomplete: expected an object")
            return page

        return list(
            paginate(
                fetch_page,
                lambda page: object_rows(page.get("items", []), label="Kubernetes"),
                lambda page: str((page.get("metadata") or {}).get("continue") or "") or None,
            )
        )


def reject_kubeconfig_command_plugins(kubeconfig_path: str, *, context: str | None) -> None:
    """Fail when the selected context's user would make the client run a local command.

    A kubeconfig ``users[].user.exec`` plugin, or an ``auth-provider`` (whose
    ``cmd-path`` the client runs), executes on the collecting host. Hosted mode
    calls this before building the client. It only parses, with a safe loader,
    and mirrors the client's merge of an ``os.pathsep``-separated path list:
    missing files are skipped, the first entry for a name wins, and the last
    ``current-context`` wins. Anything it cannot inspect fails closed.
    """
    try:
        import yaml
    except ImportError as exc:
        raise ConnectorConfigError(
            "kubernetes-cluster live collection requires the kubernetes extra to inspect the kubeconfig"
        ) from exc
    contexts: dict[str, Any] = {}
    users: dict[str, Any] = {}
    current: str | None = None
    found = False
    for raw in kubeconfig_path.split(os.pathsep):
        path = Path(raw).expanduser() if raw else None
        if path is None or not path.exists():
            continue
        try:
            config = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise ConnectorConfigError("the tenant kubeconfig could not be read as YAML") from exc
        if not isinstance(config, dict):
            raise ConnectorConfigError("the tenant kubeconfig is empty or is not a kubeconfig mapping")
        found = True
        for key, merged in (("contexts", contexts), ("users", users)):
            entries = config.get(key) or []
            if not isinstance(entries, list):
                raise ConnectorConfigError(f"the tenant kubeconfig {key} entry is not a list")
            for entry in entries:
                if isinstance(entry, dict) and "name" in entry:
                    merged.setdefault(str(entry["name"]), entry)
        if config.get("current-context"):
            current = str(config["current-context"])
    if not found:
        raise ConnectorConfigError("kubeconfig_ref does not name a readable tenant kubeconfig")
    selected = context or current
    context_entry = contexts.get(selected or "")
    if not isinstance(context_entry, dict) or not isinstance(context_entry.get("context"), dict):
        raise ConnectorConfigError("the selected kubeconfig context was not found in the tenant kubeconfig")
    user_entry = users.get(str(context_entry["context"].get("user") or ""))
    user = user_entry.get("user") if isinstance(user_entry, dict) else None
    if isinstance(user, dict) and ("exec" in user or "auth-provider" in user):
        raise ConnectorConfigError(
            "hosted mode does not accept a kubeconfig whose user runs an exec or auth-provider command; "
            "use a service account token or client certificate for the tenant kubeconfig"
        )


def _default_apis(
    *, context: str | None, kubeconfig_path: str | None, in_cluster: bool
) -> tuple[dict[str, Any], Callable[[Any], Any]]:
    try:
        from kubernetes import client as k8s_client
        from kubernetes import config as k8s_config
    except ImportError as exc:
        raise RuntimeError(
            "kubernetes-cluster live collection requires the official kubernetes client; install the "
            "kubernetes extra (pip install 'grc-lake[kubernetes]') or use --fixture-dir"
        ) from exc
    if in_cluster:
        configuration = k8s_client.Configuration()
        k8s_config.load_incluster_config(client_configuration=configuration)
        api_client = k8s_client.ApiClient(configuration)
    else:
        api_client = k8s_config.new_client_from_config(
            config_file=kubeconfig_path, context=context, persist_config=False
        )
    apis = {
        "core": k8s_client.CoreV1Api(api_client),
        "rbac": k8s_client.RbacAuthorizationV1Api(api_client),
        "networking": k8s_client.NetworkingV1Api(api_client),
        "apps": k8s_client.AppsV1Api(api_client),
        "batch": k8s_client.BatchV1Api(api_client),
        "custom": k8s_client.CustomObjectsApi(api_client),
    }
    return apis, api_client.sanitize_for_serialization


def _is_retryable_api_error(exc: Exception) -> bool:
    status = getattr(exc, "status", None)
    return isinstance(status, int) and status in backoff.RETRYABLE_STATUS


def _api_retry_after(exc: Exception) -> float | None:
    headers = getattr(exc, "headers", None)
    raw = headers.get("Retry-After") if headers is not None and hasattr(headers, "get") else None
    try:
        return float(str(raw).strip()) if raw not in (None, "") else None
    except ValueError:
        return None


def _with_kind(items: list[dict[str, Any]], kind: str, api_version: str) -> list[dict[str, Any]]:
    # List responses omit per-item kind/apiVersion; kubectl adds them, so do the same.
    return [{"kind": kind, "apiVersion": api_version, **item} for item in items]


class KubernetesFixtureClient:
    """Offline client reading ``kubectl get -o json`` shaped fixtures."""

    def __init__(self, fixture_dir: str | Path, *, cluster_name: str) -> None:
        self.fixture = Path(fixture_dir)
        self.cluster_name = cluster_name

    def cluster_role_bindings(self) -> list[dict[str, Any]]:
        return self._read("cluster_role_bindings.json")

    def role_bindings(self) -> list[dict[str, Any]]:
        return self._read("role_bindings.json")

    def namespaces(self) -> list[dict[str, Any]]:
        return self._read("namespaces.json")

    def network_policies(self) -> list[dict[str, Any]]:
        return self._read("network_policies.json")

    def pods(self) -> list[dict[str, Any]]:
        return [{"kind": "Pod", **item} for item in self._read("pods.json")]

    def workloads(self) -> list[dict[str, Any]]:
        return self._read("workloads.json")

    def apiserver_pods(self) -> list[dict[str, Any]]:
        return self._read("apiserver_pods.json")

    def services(self) -> list[dict[str, Any]]:
        return self._read("services.json")

    def inference_services(self) -> list[dict[str, Any]]:
        return self._read("inference_services.json")

    def _read(self, name: str) -> list[dict[str, Any]]:
        path = self.fixture / name
        payload = read_json(path) if path.exists() else []
        items = payload.get("items") if isinstance(payload, dict) else payload
        return [item for item in items or [] if isinstance(item, dict)]


def collect_kubernetes_evidence(
    client: KubernetesClient | KubernetesFixtureClient,
    *,
    allowed_registries: list[str] | None = None,
    collected_at: datetime | None = None,
    tenant_id: str = "customer-managed",
) -> list[dict[str, Any]]:
    """Emit configuration-baseline events for one cluster."""
    now = collected_at or datetime.now(UTC)
    cluster = client.cluster_name
    allowlist = [entry.strip().lower().rstrip("/") for entry in allowed_registries or [] if entry.strip()]
    rows: list[dict[str, Any]] = []

    for binding, kind in [
        *((b, "ClusterRoleBinding") for b in client.cluster_role_bindings()),
        *((b, "RoleBinding") for b in client.role_bindings()),
    ]:
        row = _cluster_admin_event(cluster, binding, kind, now, tenant_id)
        if row:
            rows.append(row)

    policy_counts: dict[str, int] = {}
    for policy in client.network_policies():
        namespace = str((policy.get("metadata") or {}).get("namespace") or "")
        policy_counts[namespace] = policy_counts.get(namespace, 0) + 1
    for ns in client.namespaces():
        name = str((ns.get("metadata") or {}).get("name") or "")
        if name:
            rows.append(_network_policy_event(cluster, name, policy_counts.get(name, 0), now, tenant_id))

    accelerated_templates: list[tuple[str, dict[str, Any]]] = []
    for workload in [*client.workloads(), *client.pods()]:
        rows.extend(_workload_events(cluster, workload, allowlist, now, tenant_id))
        inventory = _accelerator_event(cluster, workload, policy_counts, now, tenant_id)
        if inventory:
            rows.append(inventory)
            accelerated_templates.append((str(inventory["attributes"]["namespace"]), _template_labels(workload)))

    audit = _audit_logging_event(cluster, client.apiserver_pods(), now, tenant_id)
    if audit:
        rows.append(audit)

    gaps: list[CollectionGapError] = []
    for service in _optional_read(client.services, gaps):
        row = _service_exposure_event(cluster, service, accelerated_templates, now, tenant_id)
        if row:
            rows.append(row)
    for item in _optional_read(client.inference_services, gaps):
        row = _inference_exposure_event(cluster, item, now, tenant_id)
        if row:
            rows.append(row)
    rows.extend(_gap_event(cluster, gap, now, tenant_id) for gap in gaps)
    return rows


def _optional_read(read: Callable[[], list[dict[str, Any]]], gaps: list[CollectionGapError]) -> list[dict[str, Any]]:
    try:
        return read()
    except CollectionGapError as gap:
        gaps.append(gap)
        return []


# --- RBAC -------------------------------------------------------------------


def _cluster_admin_event(
    cluster: str, binding: dict[str, Any], kind: str, now: datetime, tenant_id: str
) -> dict[str, Any] | None:
    role_ref = binding.get("roleRef") or {}
    if role_ref.get("kind") != "ClusterRole" or role_ref.get("name") != CLUSTER_ADMIN_ROLE:
        return None
    meta = binding.get("metadata") or {}
    name = str(meta.get("name") or "")
    namespace = str(meta.get("namespace") or "")
    subjects = [
        {"kind": s.get("kind"), "name": s.get("name"), "namespace": s.get("namespace")}
        for s in binding.get("subjects") or []
        if isinstance(s, dict)
    ]
    non_system = [s for s in subjects if not str(s.get("name") or "").startswith("system:")]
    broad_system = [
        s
        for s in subjects
        if (s.get("kind"), s.get("name"))
        in {
            ("Group", "system:authenticated"),
            ("Group", "system:unauthenticated"),
            ("Group", "system:serviceaccounts"),
            ("User", "system:anonymous"),
        }
    ]
    if non_system or broad_system:
        status, severity, reason = "open", "high", "cluster_admin_granted"
    else:
        # The built-in binding to system:masters (or a subject-less binding) is
        # recorded as inventory, not a pass.
        status, severity, reason = "observed", "info", None
    if kind == "ClusterRoleBinding":
        path = f"/apis/rbac.authorization.k8s.io/v1/clusterrolebindings/{name}"
        ref = f"{kind}:{name}"
    else:
        path = f"/apis/rbac.authorization.k8s.io/v1/namespaces/{namespace}/rolebindings/{name}"
        ref = f"{kind}:{namespace}/{name}"
    return _event(
        cluster=cluster,
        entity="rbac",
        signal="cluster_admin_binding",
        object_ref=ref,
        asset_type="kubernetes_rbac_binding",
        controls=RBAC_CONTROLS,
        status=status,
        severity=severity,
        evidence_path=path,
        attributes={
            "cluster": cluster,
            "binding_kind": kind,
            "binding_name": name,
            "namespace": namespace or None,
            "role": CLUSTER_ADMIN_ROLE,
            "subjects": subjects,
            "non_system_subject_count": len(non_system),
            "broad_system_subject_count": len(broad_system),
            "benchmark_ref": "CIS Kubernetes 5.1.1",
            "finding_reason": reason,
        },
        collected_at=now,
        tenant_id=tenant_id,
    )


# --- Namespaces ---------------------------------------------------------------


def _network_policy_event(cluster: str, namespace: str, count: int, now: datetime, tenant_id: str) -> dict[str, Any]:
    ok = count > 0
    return _event(
        cluster=cluster,
        entity="namespace",
        signal="network_policy",
        object_ref=f"Namespace:{namespace}",
        asset_type="kubernetes_namespace",
        controls=NETWORK_POLICY_CONTROLS,
        status="pass" if ok else "open",
        severity="info" if ok else "medium",
        evidence_path=f"/apis/networking.k8s.io/v1/namespaces/{namespace}/networkpolicies",
        attributes={
            "cluster": cluster,
            "namespace": namespace,
            "system_namespace": namespace in SYSTEM_NAMESPACES,
            "network_policy_count": count,
            "benchmark_ref": "CIS Kubernetes 5.3.2",
            "finding_reason": None if ok else "no_network_policy",
        },
        collected_at=now,
        tenant_id=tenant_id,
    )


# --- Workloads ----------------------------------------------------------------


def _pod_spec(workload: dict[str, Any]) -> dict[str, Any] | None:
    kind = workload.get("kind")
    spec = workload.get("spec") or {}
    if kind == "Pod":
        return spec
    if kind == "CronJob":
        return ((((spec.get("jobTemplate") or {}).get("spec") or {}).get("template") or {}).get("spec")) or None
    if kind in WORKLOAD_KINDS:
        return ((spec.get("template") or {}).get("spec")) or None
    return None


def _containers(pod_spec: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        c
        for key in ("initContainers", "containers", "ephemeralContainers")
        for c in pod_spec.get(key) or []
        if isinstance(c, dict)
    ]


def _workload_events(
    cluster: str, workload: dict[str, Any], allowlist: list[str], now: datetime, tenant_id: str
) -> list[dict[str, Any]]:
    kind = str(workload.get("kind") or "")
    meta = workload.get("metadata") or {}
    # Controller-owned objects are evaluated through their owner's template.
    if kind not in WORKLOAD_KINDS or meta.get("ownerReferences"):
        return []
    pod_spec = _pod_spec(workload)
    name = str(meta.get("name") or "")
    namespace = str(meta.get("namespace") or "")
    if pod_spec is None or not name:
        return []
    prefix, plural = WORKLOAD_KINDS[kind]
    base = {
        "cluster": cluster,
        "workload_kind": kind,
        "workload_name": name,
        "namespace": namespace,
        "system_namespace": namespace in SYSTEM_NAMESPACES,
    }
    common = {
        "cluster": cluster,
        "entity": "workload",
        "object_ref": f"{kind}:{namespace}/{name}",
        "asset_type": "kubernetes_workload",
        "evidence_path": f"{prefix}/namespaces/{namespace}/{plural}/{name}",
        "collected_at": now,
        "tenant_id": tenant_id,
    }
    containers = _containers(pod_spec)
    return [
        _pod_security_event(pod_spec, containers, base, common),
        _image_registry_event(containers, allowlist, base, common),
        _secret_env_event(containers, base, common),
    ]


def pod_security_findings(pod_spec: dict[str, Any]) -> list[dict[str, str | None]]:
    """Return ``{"reason", "target"}`` findings (target = container or volume name) for one pod spec."""
    findings: list[dict[str, str | None]] = []
    for field, reason in (("hostNetwork", "host_network"), ("hostPID", "host_pid"), ("hostIPC", "host_ipc")):
        if pod_spec.get(field) is True:
            findings.append({"reason": reason, "target": None})
    for volume in pod_spec.get("volumes") or []:
        if isinstance(volume, dict) and volume.get("hostPath") is not None:
            findings.append({"reason": "host_path_volume", "target": str(volume.get("name") or "")})
    pod_sc = pod_spec.get("securityContext") or {}
    for container in _containers(pod_spec):
        cname = str(container.get("name") or "")
        sc = container.get("securityContext") or {}
        if sc.get("privileged") is True:
            findings.append({"reason": "privileged_container", "target": cname})
        # Pod Security Standards Baseline explicit-add allowlist. This check
        # alone does not claim conformance to the full Restricted profile.
        capabilities = (sc.get("capabilities") or {}).get("add") or []
        if any(str(capability) not in _BASELINE_CAPABILITIES for capability in capabilities):
            findings.append({"reason": "unsafe_added_capability", "target": cname})
        run_as_user = sc.get("runAsUser", pod_sc.get("runAsUser"))
        run_as_non_root = sc.get("runAsNonRoot", pod_sc.get("runAsNonRoot"))
        if run_as_user == 0:
            findings.append({"reason": "runs_as_root", "target": cname})
        elif run_as_user is None and run_as_non_root is not True:
            findings.append({"reason": "run_as_non_root_not_enforced", "target": cname})
        if sc.get("allowPrivilegeEscalation") is not False:
            findings.append({"reason": "privilege_escalation_allowed", "target": cname})
    return findings


def _pod_security_event(
    pod_spec: dict[str, Any], containers: list[dict[str, Any]], base: dict[str, Any], common: dict[str, Any]
) -> dict[str, Any]:
    findings = pod_security_findings(pod_spec)
    reasons = sorted({str(f["reason"]) for f in findings})
    if not findings:
        status, severity = "pass", "info"
    elif _HIGH_FINDINGS & set(reasons):
        status, severity = "open", "high"
    else:
        status, severity = "open", "medium"
    return _event(
        **common,
        signal="pod_security",
        controls=POD_SECURITY_CONTROLS,
        status=status,
        severity=severity,
        attributes={
            **base,
            "container_count": len(containers),
            "findings": findings,
            "benchmark_ref": "CIS Kubernetes 5.2.2-5.2.7, 5.2.12",
            "finding_reason": ",".join(reasons) or None,
        },
    )


def parse_image(image: str) -> dict[str, Any]:
    """Split an image reference into registry, repository, tag, and digest.

    Follows the distribution reference grammar: the first path component is a
    registry only if it contains ``.`` or ``:`` or is ``localhost``; otherwise
    the image is on Docker Hub, where single-component names live under
    ``library/``.
    """
    ref = image.strip()
    digest = None
    if "@" in ref:
        ref, digest = ref.split("@", 1)
    tag = None
    last = ref.rsplit("/", 1)[-1]
    if ":" in last:
        ref, tag = ref.rsplit(":", 1)
    parts = ref.split("/")
    if len(parts) > 1 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
        registry, path = parts[0].lower(), "/".join(parts[1:])
    else:
        registry, path = DOCKER_HUB, ref
    if registry in {"index.docker.io", "registry-1.docker.io"}:
        registry = DOCKER_HUB
    if registry == DOCKER_HUB and "/" not in path:
        path = f"library/{path}"
    return {"image": image, "registry": registry, "repository": f"{registry}/{path}", "tag": tag, "digest": digest}


def _registry_allowed(parsed: dict[str, Any], allowlist: list[str]) -> bool:
    repository = str(parsed["repository"]).lower()
    return any(repository == entry or repository.startswith(f"{entry}/") for entry in allowlist)


def _image_registry_event(
    containers: list[dict[str, Any]], allowlist: list[str], base: dict[str, Any], common: dict[str, Any]
) -> dict[str, Any]:
    images = [parse_image(str(c.get("image") or "")) for c in containers if c.get("image")]
    disallowed = sorted({i["registry"] for i in images if allowlist and not _registry_allowed(i, allowlist)})
    unpinned = sorted({i["image"] for i in images if not i["digest"] and i["tag"] in (None, "latest")})
    if disallowed:
        status, severity, reason = "open", "medium", "registry_not_allowed"
    elif unpinned:
        status, severity, reason = "open", "low", "unpinned_image_tag"
    elif allowlist:
        status, severity, reason = "pass", "info", None
    else:
        status, severity, reason = "observed", "info", None
    return _event(
        **common,
        signal="image_registry",
        controls=IMAGE_REGISTRY_CONTROLS,
        status=status,
        severity=severity,
        attributes={
            **base,
            "images": [i["image"] for i in images],
            "registries": sorted({i["registry"] for i in images}),
            "allowlist_configured": bool(allowlist),
            "disallowed_registries": disallowed,
            "unpinned_images": unpinned,
            "finding_reason": reason,
        },
    )


def _secret_env_event(containers: list[dict[str, Any]], base: dict[str, Any], common: dict[str, Any]) -> dict[str, Any]:
    # Only env var names are kept — never values, and Secret objects are never read.
    env_names: list[str] = []
    env_from = 0
    for container in containers:
        cname = str(container.get("name") or "")
        for env in container.get("env") or []:
            if isinstance(env, dict) and ((env.get("valueFrom") or {}).get("secretKeyRef")) is not None:
                env_names.append(f"{cname}/{env.get('name')}")
        env_from += sum(
            1 for src in container.get("envFrom") or [] if isinstance(src, dict) and src.get("secretRef") is not None
        )
    exposed = bool(env_names or env_from)
    return _event(
        **common,
        signal="secret_env",
        controls=SECRET_ENV_CONTROLS,
        status="open" if exposed else "pass",
        severity="low" if exposed else "info",
        attributes={
            **base,
            "secret_env_vars": env_names,
            "secret_env_from_count": env_from,
            "benchmark_ref": "CIS Kubernetes 5.4.1",
            "finding_reason": "secret_exposed_as_env" if exposed else None,
        },
    )


# --- Audit logging --------------------------------------------------------------


def _flags(container: dict[str, Any]) -> set[str]:
    tokens = [str(t) for t in [*(container.get("command") or []), *(container.get("args") or [])]]
    return {token.split("=", 1)[0] for token in tokens if token.startswith("--")}


def _audit_logging_event(
    cluster: str, apiserver_pods: list[dict[str, Any]], now: datetime, tenant_id: str
) -> dict[str, Any] | None:
    if not apiserver_pods:
        # Managed control plane: audit configuration is not visible in-cluster.
        return None
    missing: list[str] = []
    names: list[str] = []
    for pod in apiserver_pods:
        names.append(str((pod.get("metadata") or {}).get("name") or ""))
        flags: set[str] = set()
        for container in (pod.get("spec") or {}).get("containers") or []:
            if isinstance(container, dict):
                flags |= _flags(container)
        if _AUDIT_POLICY_FLAG not in flags or not any(f in flags for f in _AUDIT_SINK_FLAGS):
            missing.append(names[-1])
    ok = not missing
    return _event(
        cluster=cluster,
        entity="cluster",
        signal="audit_logging",
        object_ref="Cluster:apiserver",
        asset_type="kubernetes_cluster",
        controls=AUDIT_LOGGING_CONTROLS,
        status="pass" if ok else "open",
        severity="info" if ok else "high",
        evidence_path="/api/v1/namespaces/kube-system/pods?labelSelector=component%3Dkube-apiserver",
        attributes={
            "cluster": cluster,
            "apiserver_pods": names,
            "apiserver_pods_without_audit": missing,
            "benchmark_ref": "CIS Kubernetes 1.2.16, 3.2.1",
            "finding_reason": None if ok else "audit_logging_disabled",
        },
        collected_at=now,
        tenant_id=tenant_id,
    )


# --- Accelerator inventory ------------------------------------------------------


def _quantity(value: Any) -> int:
    """Whole-device count of an extended resource; device plugins only advertise integers."""
    try:
        return max(0, int(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def accelerator_requests(containers: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Per accelerator resource, the devices the containers ask for (limit, else request)."""
    totals: dict[str, int] = {}
    for container in containers:
        resources = container.get("resources") or {}
        limits = resources.get("limits") or {}
        requests = resources.get("requests") or {}
        for name in (*GPU_RESOURCES, INFINIBAND_RESOURCE):
            count = _quantity(limits.get(name)) or _quantity(requests.get(name))
            if count:
                totals[name] = totals.get(name, 0) + count
    return totals


def serving_runtime(images: Iterable[str], names: Iterable[str] = ()) -> str | None:
    """Recognize the common GPU model servers from image references and names."""
    combined = " ".join([*images, *names]).lower()
    for marker, runtime in (
        ("vllm", "vllm"),
        ("triton", "triton"),
        ("text-generation-inference", "tgi"),
        ("tgi", "tgi"),
        (NIM_IMAGE_PREFIX.rstrip("/"), "nim"),
    ):
        if marker in combined:
            return runtime
    return None


def _template_labels(workload: dict[str, Any]) -> dict[str, Any]:
    kind = workload.get("kind")
    spec = workload.get("spec") or {}
    if kind == "Pod":
        return dict((workload.get("metadata") or {}).get("labels") or {})
    if kind == "CronJob":
        template = ((spec.get("jobTemplate") or {}).get("spec") or {}).get("template") or {}
    else:
        template = spec.get("template") or {}
    return dict((template.get("metadata") or {}).get("labels") or {})


def _accelerator_event(
    cluster: str, workload: dict[str, Any], policy_counts: dict[str, int], now: datetime, tenant_id: str
) -> dict[str, Any] | None:
    kind = str(workload.get("kind") or "")
    meta = workload.get("metadata") or {}
    if kind not in WORKLOAD_KINDS or meta.get("ownerReferences"):
        return None
    pod_spec = _pod_spec(workload)
    name = str(meta.get("name") or "")
    namespace = str(meta.get("namespace") or "")
    if pod_spec is None or not name:
        return None
    containers = _containers(pod_spec)
    requested = accelerator_requests(containers)
    if not requested:
        return None
    images = [str(c.get("image") or "") for c in containers if c.get("image")]
    prefix, plural = WORKLOAD_KINDS[kind]
    return _event(
        cluster=cluster,
        entity="workload",
        signal="accelerator_inventory",
        object_ref=f"{kind}:{namespace}/{name}",
        asset_type="kubernetes_workload",
        controls=ACCELERATOR_INVENTORY_CONTROLS,
        status="observed",
        severity="info",
        evidence_path=f"{prefix}/namespaces/{namespace}/{plural}/{name}",
        attributes={
            "cluster": cluster,
            "workload_kind": kind,
            "workload_name": name,
            "namespace": namespace,
            "system_namespace": namespace in SYSTEM_NAMESPACES,
            "gpu_count": sum(requested.get(resource, 0) for resource in GPU_RESOURCES),
            "accelerator_resources": sorted(requested),
            "infiniband": INFINIBAND_RESOURCE in requested,
            "images": images,
            "serving_runtime": serving_runtime(images, [str(c.get("name") or "") for c in containers]),
            "nim_image": any(image.startswith(NIM_IMAGE_PREFIX) for image in images),
            "namespace_network_policy_count": policy_counts.get(namespace, 0),
            "finding_reason": None,
        },
        collected_at=now,
        tenant_id=tenant_id,
    )


# --- Network exposure -------------------------------------------------------------


def _is_world(cidr: Any) -> bool:
    try:
        return ipaddress.ip_network(str(cidr).strip(), strict=False).prefixlen == 0
    except ValueError:
        # An unparseable range cannot be shown to restrict anything.
        return True


def _address_scope(ingress: list[Any]) -> str:
    """``public``, ``private`` or ``unknown`` from the load balancer addresses the cluster reports."""
    scopes: set[str] = set()
    for entry in ingress:
        raw = entry.get("ip") if isinstance(entry, dict) else None
        if not raw:
            scopes.add("unknown")
            continue
        try:
            address = ipaddress.ip_address(str(raw).strip())
        except ValueError:
            scopes.add("unknown")
            continue
        scopes.add("public" if address.is_global else "private")
    if "public" in scopes:
        return "public"
    if scopes == {"private"}:
        return "private"
    return "unknown"


def _service_exposure_event(
    cluster: str,
    service: dict[str, Any],
    accelerated_templates: list[tuple[str, dict[str, Any]]],
    now: datetime,
    tenant_id: str,
) -> dict[str, Any] | None:
    spec = service.get("spec") or {}
    service_type = str(spec.get("type") or "ClusterIP")
    if service_type not in EXPOSED_SERVICE_TYPES:
        return None
    meta = service.get("metadata") or {}
    name = str(meta.get("name") or "")
    namespace = str(meta.get("namespace") or "")
    if not name:
        return None
    selector = spec.get("selector") or {}
    fronts_accelerator = bool(selector) and any(
        ns == namespace and all(labels.get(key) == value for key, value in selector.items())
        for ns, labels in accelerated_templates
    )
    ranges = [str(item) for item in spec.get("loadBalancerSourceRanges") or []]
    unrestricted = not ranges or any(_is_world(item) for item in ranges)
    scope = _address_scope(((service.get("status") or {}).get("loadBalancer") or {}).get("ingress") or [])
    if service_type == "NodePort":
        status, severity, reason = "not_evaluated", "info", "node_port_reachability_not_visible"
    elif scope == "public" and unrestricted:
        status, reason = "open", "public_load_balancer_unrestricted"
        severity = "high" if fronts_accelerator else "medium"
    elif scope == "public":
        status, severity, reason = "pass", "info", "public_load_balancer_source_restricted"
    elif scope == "private":
        status, severity, reason = "pass", "info", "internal_load_balancer"
    else:
        status, severity, reason = "not_evaluated", "info", "load_balancer_address_unknown"
    return _event(
        cluster=cluster,
        entity="service",
        signal="network_exposure",
        object_ref=f"Service:{namespace}/{name}",
        asset_type="network",
        controls=NETWORK_EXPOSURE_CONTROLS,
        status=status,
        severity=severity,
        evidence_path=f"/api/v1/namespaces/{namespace}/services/{name}",
        attributes={
            "cluster": cluster,
            "namespace": namespace,
            "service_name": name,
            "service_type": service_type,
            "address_scope": scope if service_type == "LoadBalancer" else None,
            "source_ranges_restricted": not unrestricted,
            "ports": [
                {"port": port.get("port"), "protocol": port.get("protocol") or "TCP"}
                for port in spec.get("ports") or []
                if isinstance(port, dict)
            ],
            "selects_accelerator_workload": fronts_accelerator,
            "finding_reason": reason,
        },
        collected_at=now,
        tenant_id=tenant_id,
        safeguard_ids=[NETWORK_SAFEGUARD],
    )


def _inference_exposure_event(
    cluster: str, item: dict[str, Any], now: datetime, tenant_id: str
) -> dict[str, Any] | None:
    meta = item.get("metadata") or {}
    name = str(meta.get("name") or "")
    namespace = str(meta.get("namespace") or "")
    if not name:
        return None
    predictor = (item.get("spec") or {}).get("predictor") or {}
    model = predictor.get("model") or {}
    containers = [c for c in [model, *(predictor.get("containers") or [])] if isinstance(c, dict) and c]
    images = [str(c.get("image") or "") for c in containers if c.get("image")]
    names = [str(model.get("runtime") or ""), *(str(c.get("name") or "") for c in containers)]
    requested = accelerator_requests(containers)
    host = urllib.parse.urlsplit(str((item.get("status") or {}).get("url") or "")).hostname or ""
    cluster_local = (meta.get("labels") or {}).get(KSERVE_VISIBILITY_LABEL) == KSERVE_CLUSTER_LOCAL
    if cluster_local or host.endswith(CLUSTER_LOCAL_DOMAIN):
        url_scope, status, reason = "cluster_local", "pass", "cluster_local"
    elif host:
        url_scope, status, reason = "external", "not_evaluated", "external_url_authentication_not_visible"
    else:
        url_scope, status, reason = "none", "not_evaluated", "no_url_reported"
    return _event(
        cluster=cluster,
        entity="inference",
        signal="network_exposure",
        object_ref=f"InferenceService:{namespace}/{name}",
        asset_type="service",
        controls=NETWORK_EXPOSURE_CONTROLS,
        status=status,
        severity="info",
        evidence_path=f"/apis/{KSERVE_GROUP}/{KSERVE_VERSION}/namespaces/{namespace}/{KSERVE_PLURAL}/{name}",
        attributes={
            "cluster": cluster,
            "namespace": namespace,
            "inference_service": name,
            "model_format": (model.get("modelFormat") or {}).get("name"),
            "serving_runtime": serving_runtime(images, names),
            "images": images,
            "gpu_count": sum(requested.get(resource, 0) for resource in GPU_RESOURCES),
            "url_scope": url_scope,
            "finding_reason": reason,
        },
        collected_at=now,
        tenant_id=tenant_id,
        safeguard_ids=[NETWORK_SAFEGUARD],
    )


def _gap_event(cluster: str, gap: CollectionGapError, now: datetime, tenant_id: str) -> dict[str, Any]:
    """A coverage-gap row: an actionable open item that neither passes nor fails a control."""
    return _event(
        cluster=cluster,
        entity="collection",
        signal="gap",
        object_ref=f"Collection:{gap.collection}",
        asset_type="collection_scope",
        controls=[],
        status="open",
        severity="low",
        evidence_path=f"kubernetes:{cluster}:collection-gap:{gap.collection}",
        attributes={"cluster": cluster, **gap.attributes()},
        collected_at=now,
        tenant_id=tenant_id,
    )


# --- Event shape ------------------------------------------------------------------


def _stable_id(parts: Iterable[str]) -> str:
    raw = ":".join(parts).lower()
    slug = re.sub(r"[^a-z0-9_.:-]+", "-", raw).strip("-")
    if len(slug) <= 96:
        return slug
    return f"{slug[:83]}-{hashlib.sha256(raw.encode()).hexdigest()[:12]}"


def _event(
    *,
    cluster: str,
    entity: str,
    signal: str,
    object_ref: str,
    asset_type: str,
    controls: list[str],
    status: str,
    severity: str,
    evidence_path: str,
    attributes: dict[str, Any],
    collected_at: datetime,
    tenant_id: str,
    safeguard_ids: list[str] | None = None,
) -> dict[str, Any]:
    stable = _stable_id([cluster, signal, object_ref])
    row: dict[str, Any] = {
        "event_id": f"kubernetes-{stable}",
        "tenant_id": tenant_id,
        "workspace_id": "default",
        "event_time": utc_iso(collected_at),
        "source": SOURCE,
        "event_type": f"kubernetes.{entity}.{signal}",
        "entity": {
            "asset_id": f"kubernetes:{cluster}:{object_ref}",
            "asset_type": asset_type,
            "asset_owner": cluster,
            "environment": "prod",
            "org": cluster,
        },
        "severity": severity,
        "status": status,
        "controls": list(controls),
        "evidence": {
            "evidence_id": f"ev-{stable}",
            "evidence_ref": evidence_path,
            "evidence_collected_at": utc_iso(collected_at),
        },
        "attributes": attributes,
    }
    if safeguard_ids:
        row["safeguard_ids"] = sorted(safeguard_ids)
    return row
