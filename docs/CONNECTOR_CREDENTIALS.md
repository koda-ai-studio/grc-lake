# Connector credentials

In the console: **Connections → choose a source → Test → Enable → Sync**. For
automation, use the [headless setup playbook](playbooks/HEADLESS_CONNECTOR_SETUP.md).
Cloud connectors use short-lived or workload identity credentials. Settings keep
a credential reference (an environment variable name or mounted secret file),
not the secret itself.

- **AWS** uses STS AssumeRole, one External ID per deployed role, short-lived session credentials, and read-only IAM posture APIs. Temporary credentials expire after each session; GRC Lake stores no long-lived access keys. The connection hub stores one active account role per workspace; changing the target replaces that connection. StackSets or Terraform role deployment does not register organization members for collection. Bulk account import and per-connection scheduling are planned. See the [cloud setup guide](LIVE_CLOUD_POC.md) and the [credential lifecycle](images/grc-lake-aws-sts-lifecycle.svg).
- **Azure** uses a customer-owned Entra application, managed identity, or federated workload identity with Reader scope.
- **GCP** uses Application Default Credentials or workload identity; a service-account key file also works.
- **Snowflake** uses a read-only service identity with a key-pair or OAuth token reference. GRC Lake stores identifiers, not passwords or private-key contents. Snowflake is one of the existing-lake readers.
- **GitHub** uses a GitHub App installation token, which expires within an hour.
- **SaaS sources** use scoped API tokens or an integration-user login.
- **Snyk** uses a read-only API token by reference (`credential_ref`, default `SNYK_TOKEN`), sent only to the allowlisted API host of the configured Snyk region. See [Snyk](CONNECTORS.md#snyk-vulnerability-issues-per-project-preview).

Ship your own connector as a Python package: [adding connectors](ADDING_CONNECTORS.md#shipping-a-connector-as-a-package).
