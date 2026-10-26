# Multi-stage Dockerfile: builds the Next.js workbench, installs the Python
# package with the workbench bundled in, ships a slim runtime image.
#
# The web and Python builders produce the application. A separate APK stage
# installs signed, version-pinned system packages into an empty runtime root.
# CPython and native libraries come from the same vendor; the scratch stage keeps
# the runtime shell-free while retaining vendor package records and licenses.
#
# Build:  docker build -t grc-lake:dev .
# Run: see deploy/README.md for authenticated Compose and Kubernetes profiles.

# Base images are pinned by multi-arch index digest to prevent silent tag
# changes. Dependabot updates those pins; runtime package versions are tracked
# separately in tools/runtime-packages.txt. uv also uses its official digest.
FROM ghcr.io/astral-sh/uv:0.13.1@sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336 AS uv

# Signed runtime packages --------------------------------------------
FROM cgr.dev/chainguard/wolfi-base:latest@sha256:256c88bb066424045021090932d50be93c8e3f2ce3586707702a401b146f3e43 AS runtime-system
COPY tools/runtime-packages.txt /tmp/runtime-packages.txt
# Signature verification uses the keys and repository configuration in the
# digest-pinned builder. No shell or package manager is installed in the root.
RUN apk add --root /runtime-root --initdb --no-scripts --no-cache \
      --keys-dir /etc/apk/keys --repositories-file /etc/apk/repositories \
      $(cat /tmp/runtime-packages.txt)

# Use the same interpreter and native libraries for building and running.
FROM runtime-system AS python-base
RUN apk add --no-cache $(cat /tmp/runtime-packages.txt) \
  && mkdir -p /usr/local/bin \
  && ln -s /usr/bin/python3.14 /usr/local/bin/python

# React workbench ----------------------------------------------------
# The static export is the same on every architecture, so it builds on the
# build host's platform instead of under emulation.
FROM --platform=$BUILDPLATFORM node:22-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392 AS web-build
WORKDIR /workbench
COPY app/web/package*.json ./
RUN npm ci --no-audit --no-fund
COPY app/web/ ./
RUN npm run build

# Python package + analytics venv -----------------------------------
FROM python-base AS py-build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /src
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
COPY connectors/ ./connectors/
COPY controls/ ./controls/
COPY docs/reviews/2026-10-15-repaired-proposals.json docs/reviews/2026-10-25-soc2-iso27001-pending-queue.json ./docs/reviews/
COPY frameworks/ ./frameworks/
COPY mappings/ ./mappings/
COPY programs/ ./programs/
COPY mockup_companies/ ./mockup_companies/
COPY policy_templates/ ./policy_templates/
COPY agent-skills/ ./agent-skills/
# Bring the static export into the package tree before install so wheel
# package-data picks it up.
COPY --from=web-build /src/security_lakehouse/web/dist/ ./src/security_lakehouse/web/dist/
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
# Dependencies come from uv.lock with their sha256 hashes, and the install
# refuses any distribution whose hash does not match. The project itself is
# then built from this source tree with --no-deps, so nothing unpinned is
# resolved at build time.
# The image binds 0.0.0.0, so it must be able to run the authenticated
# server. Without the `server` extra the CMD below silently falls back to
# local mode, which has no authentication at all.
RUN python -m venv --without-pip /opt/grc-lake-venv \
  && uv export --frozen --no-dev --no-emit-project \
       --extra server --extra analytics --extra cloud --extra mcp --extra iceberg \
       --output-file /tmp/grc-lake-requirements.txt \
  && uv pip install --python /opt/grc-lake-venv/bin/python \
       --require-hashes --requirement /tmp/grc-lake-requirements.txt \
  && uv pip install --python /opt/grc-lake-venv/bin/python --no-deps \
       ".[server,analytics,cloud,mcp,iceberg]"

# Runtime identity and Python entrypoints -----------------------------------
FROM python-base AS runtime-deps
COPY tools/build_runtime_root.py tools/runtime-packages.txt /tmp/
RUN python /tmp/build_runtime_root.py /runtime-root

# Shell-free runtime ------------------------------------------------
FROM scratch AS runtime
LABEL org.opencontainers.image.title="GRC Lake"
LABEL org.opencontainers.image.source="https://github.com/koda-ai-studio/grc-lake"
LABEL org.opencontainers.image.licenses="Apache-2.0"

ENV PATH="/opt/grc-lake-venv/bin:/usr/local/bin:/usr/bin" \
    LD_LIBRARY_PATH=/usr/local/lib \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GRC_LAKE_LAKE=/lake \
    GRC_LAKE_DATA_DIR=/opt/grc-lake-data

COPY --from=runtime-deps /runtime-root/ /

COPY --from=py-build /opt/grc-lake-venv /opt/grc-lake-venv
# Ship the framework / control / connector / mapping catalogs inside the
# image so the wheel-installed Python package can find them. The env var
# GRC_LAKE_DATA_DIR (set above) tells security_lakehouse where to look.
COPY frameworks/ /opt/grc-lake-data/frameworks/
COPY controls/ /opt/grc-lake-data/controls/
COPY connectors/ /opt/grc-lake-data/connectors/
COPY mappings/ /opt/grc-lake-data/mappings/
COPY programs/ /opt/grc-lake-data/programs/
COPY mockup_companies/ /opt/grc-lake-data/mockup_companies/
COPY policy_templates/ /opt/grc-lake-data/policy_templates/
COPY agent-skills/ /opt/grc-lake-data/agent-skills/

USER grc-lake
WORKDIR /home/grc-lake
EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/healthz', timeout=2)"]

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["grc-lake", "serve", "--server", "--lake", "/lake", "--host", "0.0.0.0", "--port", "8787"]
