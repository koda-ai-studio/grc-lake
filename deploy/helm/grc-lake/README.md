# GRC Lake Helm chart

Run the GRC Lake API and console with operator-managed storage, credentials,
TLS and backups. See the repository's [deployment guide](https://github.com/koda-ai-studio/grc-lake/blob/main/docs/DEPLOYMENT.md)
and [sample values](https://github.com/koda-ai-studio/grc-lake/blob/main/deploy/examples/self-hosted-values.yaml).

## Install a published version

OCI chart publication starts with the next release after 0.3.16. Select a version
whose GitHub release includes the chart package; earlier releases have no chart
at this registry location.

```bash
VERSION=<published-version>
helm upgrade --install grc-lake \
  oci://ghcr.io/koda-ai-studio/charts/grc-lake \
  --version "$VERSION" --namespace grc-lake --create-namespace \
  --values self-hosted-values.yaml
```

Check your rendered configuration with `helm template` before applying it.
This chart does not provision cloud infrastructure or certify deployment capacity.

## Verify provenance

The release workflow validates the chart after the container gates, publishes it,
pulls it back and compares its bytes, then signs provenance for both the package
and OCI manifest digest. Python publication waits for this job to succeed.

```bash
helm pull oci://ghcr.io/koda-ai-studio/charts/grc-lake --version "$VERSION"
gh attestation verify "grc-lake-${VERSION}.tgz" --repo koda-ai-studio/grc-lake
```

The GitHub release also retains `chart-provenance.sigstore.json` for offline
verification with `gh attestation verify --bundle`. These are Sigstore
attestations; they are not Helm's GPG `.prov` format.

## Artifact Hub registration

After the first successful chart publication, register
`oci://ghcr.io/koda-ai-studio/charts/grc-lake` in Artifact Hub. Publication to GHCR
does not automatically create an Artifact Hub listing. Set the assigned
repository ID and actual Artifact Hub owner in `deploy/helm/artifacthub-repo.yml`,
then publish the metadata as documented by
[Artifact Hub](https://artifacthub.io/docs/topics/repositories/helm-charts/#oci-support).
Do not claim a listing or verified publisher status until Artifact Hub reports it.
