#!/usr/bin/env bash
# Copy folders from the cluster clone back into this clone, at the same paths.
#
#   hpc/fetch.sh benchmarks/results/willdaly/2026-10-13_moldetv2-molscribe-cuda_internal
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
host="${XN_HPC_HOST:-explorer}"
for path in "$@"; do
    mkdir -p "$path"
    rsync -a "$host:xn-molecular-extraction/$path/" "$path/"
    echo "fetched $path"
done
