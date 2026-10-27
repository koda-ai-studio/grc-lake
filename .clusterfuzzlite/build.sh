#!/bin/bash
set -euo pipefail
# Package every fuzz/fuzz_*.py target with its seed corpus.
#
# PyInstaller bundles project source directly from src/ (--paths). The targets
# need no optional application dependencies or project build-backend download.
selected="${CFL_EXTRA_FUZZ_TARGET:-}"
built=0
for fuzzer in "$SRC"/grc-lake/fuzz/fuzz_*.py; do
  name=$(basename -s .py "$fuzzer")
  if [ -n "$selected" ] && [ "$selected" != "$name" ]; then
    continue
  fi
  compile_python_fuzzer "$fuzzer" --paths "$SRC/grc-lake/src" --paths "$SRC/grc-lake/fuzz"
  corpus="$SRC/grc-lake/fuzz/corpus/$name"
  if [ -d "$corpus" ]; then
    (cd "$corpus" && zip -q -r "$OUT/${name}_seed_corpus.zip" .)
  fi
  built=$((built + 1))
done
if [ "$built" -eq 0 ]; then
  echo "No fuzz target matched the requested selection" >&2
  exit 1
fi
