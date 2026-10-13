#!/usr/bin/env bash
# Check out your current commit in the cluster clone, so jobs run exactly the code you have
# locally. The cluster fetches from GitHub with its read-only deploy key (hpc/README.md), so the
# commit has to be pushed first.
#
#   hpc/deploy.sh                      # ssh host from XN_HPC_HOST, default "explorer"
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
host="${XN_HPC_HOST:-explorer}"
sha=$(git rev-parse HEAD)

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    echo "Commit your changes first; the cluster only sees commits." >&2
    exit 1
fi
if [ -z "$(git branch -r --contains "$sha")" ]; then
    echo "Push this commit to GitHub first: git push -u origin HEAD" >&2
    exit 1
fi
ssh "$host" "cd ~/xn-molecular-extraction && git fetch -q origin && git checkout -q --detach $sha && git log --oneline -1"
