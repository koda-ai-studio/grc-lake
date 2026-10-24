/**
 * Text fallback marks when no brand SVG is mapped (see connector-brand-logos.ts).
 */

export interface ConnectorVisual {
  vendor: string;
  mark: string;
  accent: string;
  bg: string;
  categoryLabel: string;
}

const CATEGORY_LABELS: Record<string, string> = {
  warehouse: "Data warehouse",
  analytics_lake: "Analytics lake",
  evidence_store: "Evidence store",
  developer_platform: "Developer platform",
  identity: "Identity",
  cloud: "Cloud posture",
  workflow: "Workflow",
  detections: "Detections",
  runtime_security: "Runtime security",
  starter_mode: "Local evidence",
};

export const CONNECTOR_VISUALS: Record<string, ConnectorVisual> = {
  "snowflake-evidence-lake": {
    vendor: "Snowflake",
    mark: "SF",
    accent: "#29B5E8",
    bg: "#ecfeff",
    categoryLabel: "Data warehouse",
  },
  "bigquery-evidence-lake": {
    vendor: "Google BigQuery",
    mark: "BQ",
    accent: "#4285F4",
    bg: "#eef4ff",
    categoryLabel: "Data warehouse",
  },
  "iceberg-parquet-lake": {
    vendor: "Apache Iceberg",
    mark: "ICE",
    accent: "#2E6FD8",
    bg: "#eef4ff",
    categoryLabel: "Analytics lake",
  },
  "clickhouse-telemetry-lake": {
    vendor: "ClickHouse",
    mark: "CH",
    accent: "#FFCC01",
    bg: "#fffbeb",
    categoryLabel: "Analytics lake",
  },
  "object-storage-evidence": {
    vendor: "Object storage",
    mark: "S3",
    accent: "#FF9900",
    bg: "#fff7ed",
    categoryLabel: "Evidence store",
  },
  "github-security": {
    vendor: "GitHub",
    mark: "GH",
    accent: "#24292f",
    bg: "#f6f8fa",
    categoryLabel: "Developer platform",
  },
  "gitlab-security": {
    vendor: "GitLab",
    mark: "GL",
    accent: "#FC6D26",
    bg: "#fff7ed",
    categoryLabel: "Developer platform",
  },
  "okta-identity": {
    vendor: "Okta",
    mark: "OKTA",
    accent: "#007DC1",
    bg: "#eff6ff",
    categoryLabel: "Identity",
  },
  "okta-system-log": {
    vendor: "Okta",
    mark: "LOG",
    accent: "#007DC1",
    bg: "#eff6ff",
    categoryLabel: "Identity",
  },
  "aws-posture": {
    vendor: "Amazon Web Services",
    mark: "AWS",
    accent: "#FF9900",
    bg: "#fff7ed",
    categoryLabel: "Cloud posture",
  },
  "identity-provider": {
    vendor: "Identity provider",
    mark: "IdP",
    accent: "#6366f1",
    bg: "#eef2ff",
    categoryLabel: "Identity",
  },
  ticketing: {
    vendor: "Ticketing",
    mark: "TMS",
    accent: "#6366f1",
    bg: "#eef2ff",
    categoryLabel: "Workflow",
  },
  "siem-alerts": {
    vendor: "SIEM",
    mark: "SIEM",
    accent: "#dc2626",
    bg: "#fef2f2",
    categoryLabel: "Detections",
  },
  "runtime-gateway": {
    vendor: "Runtime gateway",
    mark: "RT",
    accent: "#7c3aed",
    bg: "#f5f3ff",
    categoryLabel: "Runtime security",
  },
  "managed-local-evidence": {
    vendor: "Local lake",
    mark: "LOC",
    accent: "#64748b",
    bg: "#f1f5f9",
    categoryLabel: "Local evidence",
  },
  "google-workspace-identity": {
    vendor: "Google Workspace",
    mark: "G",
    accent: "#4285F4",
    bg: "#eff6ff",
    categoryLabel: "Identity",
  },
  "gcp-posture": {
    vendor: "Google Cloud",
    mark: "GCP",
    accent: "#4285F4",
    bg: "#eff6ff",
    categoryLabel: "Cloud posture",
  },
  "azure-posture": {
    vendor: "Microsoft Azure",
    mark: "AZ",
    accent: "#0078D4",
    bg: "#eff6ff",
    categoryLabel: "Cloud posture",
  },
  "entra-identity": {
    vendor: "Microsoft Entra",
    mark: "ID",
    accent: "#0078D4",
    bg: "#eff6ff",
    categoryLabel: "Identity",
  },
  "intune-devices": {
    vendor: "Microsoft Intune",
    mark: "IN",
    accent: "#0078D4",
    bg: "#eff6ff",
    categoryLabel: "Device posture",
  },
  "bamboohr-personnel": {
    vendor: "BambooHR",
    mark: "HR",
    accent: "#73C41D",
    bg: "#f0fdf4",
    categoryLabel: "Personnel",
  },
  "rippling-personnel": {
    vendor: "Rippling",
    mark: "RP",
    accent: "#7a3f00",
    bg: "#fff7ed",
    categoryLabel: "Personnel",
  },
  "workday-personnel": {
    vendor: "Workday",
    mark: "WD",
    accent: "#0875e1",
    bg: "#eff6ff",
    categoryLabel: "Personnel",
  },
  "training-completion": {
    vendor: "Training export",
    mark: "TR",
    accent: "#0f766e",
    bg: "#f0fdfa",
    categoryLabel: "Security training",
  },
  "jamf-devices": {
    vendor: "Jamf",
    mark: "JF",
    accent: "#4a5d6e",
    bg: "#f1f5f9",
    categoryLabel: "Device posture",
  },
  "crowdstrike-falcon": {
    vendor: "CrowdStrike",
    mark: "CS",
    accent: "#e01f3d",
    bg: "#fff1f2",
    categoryLabel: "Endpoint protection",
  },
  "snyk-vulnerabilities": {
    vendor: "Snyk",
    mark: "SK",
    accent: "#4c4a73",
    bg: "#f3f2f8",
    categoryLabel: "Vulnerability scanning",
  },
  "kubernetes-cluster": {
    vendor: "Kubernetes",
    mark: "K8s",
    accent: "#326CE5",
    bg: "#eff6ff",
    categoryLabel: "Container platform",
  },
  "lambda-cloud": {
    vendor: "Lambda",
    mark: "λ",
    accent: "#5b3fd1",
    bg: "#f3f0ff",
    categoryLabel: "GPU cloud",
  },
  "databricks-evidence-lake": {
    vendor: "Databricks",
    mark: "DB",
    accent: "#FF3621",
    bg: "#fff1ee",
    categoryLabel: "Evidence lake",
  },
  "jira-ticketing": {
    vendor: "Atlassian Jira",
    mark: "Jira",
    accent: "#0052CC",
    bg: "#eff6ff",
    categoryLabel: "Workflow",
  },
};

export function connectorVisual(
  connectorId: string,
  fallback?: { name?: string; category?: string },
): ConnectorVisual {
  const known = CONNECTOR_VISUALS[connectorId];
  if (known) return known;
  const name = fallback?.name ?? connectorId;
  const category = fallback?.category ?? "connector";
  return {
    vendor: name,
    mark: name.slice(0, 3).toUpperCase(),
    accent: "#2563eb",
    bg: "#eff6ff",
    categoryLabel: CATEGORY_LABELS[category] ?? category.replace(/_/g, " "),
  };
}
