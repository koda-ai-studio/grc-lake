#!/usr/bin/env bash
# Check both installed interpreters without requiring a shell in the image.
set -euo pipefail
image="${1:?usage: check_image_dependencies.sh IMAGE [docker run options]}"
shift
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
for interpreter in /usr/local/bin/python /opt/grc-lake-venv/bin/python; do
  docker run --rm -i "$@" --entrypoint "$interpreter" "$image" - < "$script_dir/check_runtime_dependencies.py"
done
docker run --rm "$@" --entrypoint /opt/grc-lake-venv/bin/python "$image" -c '
import cryptography.hazmat.bindings._rust
import duckdb
import lxml.etree
import pyarrow
import xmlsec
assert duckdb.sql("select 1").fetchone() == (1,)
assert pyarrow.array([1, 2, 3]).to_pylist() == [1, 2, 3]
print("Application native dependency checks passed.")
'
