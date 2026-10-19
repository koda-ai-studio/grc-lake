# ClusterFuzzLite builder for the atheris targets in fuzz/.
#
# The base image ships Python, atheris, and PyInstaller (compile_python_fuzzer).
# It and uv are pinned by digest; Dependabot's docker ecosystem can bump them.
# The build_fuzzers action replaces $SRC/grc-lake with the commit under test
# before build.sh runs, so the source copied here only serves local builds.
FROM ghcr.io/astral-sh/uv:0.13.1@sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336 AS uv

FROM gcr.io/oss-fuzz-base/base-builder-python:v1@sha256:756c7196c97d62a66c448e70bdeecce400e68ae2ee96d4393cb38d58ffca18d2
COPY --from=uv /uv /usr/local/bin/uv
# Third-party imports (the Stripe webhook target needs SQLAlchemy) come from
# uv.lock with sha256 hashes; nothing unpinned is resolved.
COPY pyproject.toml uv.lock /tmp/grc-lake-lock/
RUN uv export --frozen --no-dev --no-emit-project --extra server \
      --project /tmp/grc-lake-lock --output-file /tmp/grc-lake-requirements.txt \
  && pip3 install --no-cache-dir --require-hashes --no-deps -r /tmp/grc-lake-requirements.txt \
  && rm -rf /tmp/grc-lake-lock /tmp/grc-lake-requirements.txt
COPY . $SRC/grc-lake
WORKDIR $SRC/grc-lake
COPY .clusterfuzzlite/build.sh $SRC/
