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

`oci://ghcr.io/koda-ai-studio/charts/grc-lake` is registered in Artifact Hub as
`grc-lake`, owned by the `koda-ai-studio` organization (KODA AI Studio),
administered through the maintainer account. Its assigned repository ID is
`eceb1fae-e871-4fd5-8c75-0054a2ec2b34`. Registration and OCI publication do not
by themselves prove that a package is indexed or that publisher verification
has completed; check the public listing before making either claim.

The metadata in `deploy/helm/artifacthub-repo.yml` binds that registration to the
registry. After authenticating ORAS to GHCR, publish it using the
[documented OCI media types](https://artifacthub.io/docs/topics/repositories/helm-charts/#oci-support):

```bash
cd deploy/helm
oras push ghcr.io/koda-ai-studio/charts/grc-lake:artifacthub.io \
  --config /dev/null:application/vnd.cncf.artifacthub.config.v1+yaml \
  artifacthub-repo.yml:application/vnd.cncf.artifacthub.repository-metadata.layer.v1.yaml
```

The metadata tag is separate from versioned chart tags. Pull it back and compare
the YAML before waiting for Artifact Hub to reprocess the repository. The empty
`owners` list deliberately configures no email-based ownership transfer; account
ownership is managed in the Artifact Hub control panel. If ownership changes,
update the actual registration details instead of inventing an owner identity.
