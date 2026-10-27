# ClusterFuzzLite builder for the atheris targets in fuzz/.
#
# The base image ships Python, atheris, and PyInstaller (compile_python_fuzzer).
# The base is pinned by digest; Dependabot's docker ecosystem can bump it.
# The build_fuzzers action replaces $SRC/grc-lake with the commit under test
# before build.sh runs, so the source copied here only serves local builds.
FROM gcr.io/oss-fuzz-base/base-builder-python:v1@sha256:756c7196c97d62a66c448e70bdeecce400e68ae2ee96d4393cb38d58ffca18d2
# All targets replay with Python -S in tests; production parsers and signature
# verification need no optional server or database packages.
COPY . $SRC/grc-lake
WORKDIR $SRC/grc-lake
COPY .clusterfuzzlite/build.sh $SRC/
