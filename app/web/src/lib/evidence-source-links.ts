export const SOURCE_CONNECTOR: Record<string, string> = {
  aws_config: "aws-posture",
  github: "github-security",
  "github-public-repo": "github-security",
  "github-repo-governance": "github-security",
  okta: "okta-identity",
  azure: "azure-posture",
  gcp: "gcp-posture",
  snowflake: "snowflake-evidence-lake",
  clickhouse: "clickhouse-telemetry-lake",
};

export function sourceEvidenceHref(source: string) {
  return `/evidence?source=${encodeURIComponent(source)}`;
}
export function sourceDetailHref(source: string) {
  const connector = SOURCE_CONNECTOR[source];
  return connector
    ? `/connectors?connect=${encodeURIComponent(connector)}`
    : sourceEvidenceHref(source);
}
