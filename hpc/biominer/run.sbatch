#!/bin/bash
#SBATCH --job-name=xn-biominer
#SBATCH --partition=gpu
#SBATCH --gres=gpu:h200:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=160G
#SBATCH --time=03:00:00
#SBATCH --output=/scratch/%u/xn/logs/%x-%j.out
#
# Full BioMiner (MinerU layout -> MolDetV2 boxes -> MolGlyph SMILES -> BioMiner-Instruct
# grounding and Markush enumeration) on internal papers, on one H200. Submit from the repo root:
#
#   sbatch hpc/biominer/run.sbatch            # all six internal papers
#   sbatch hpc/biominer/run.sbatch 16         # some papers, e.g. a smoke test
#
# Needs hpc/biominer/setup.sbatch run in both modes first. BioMiner's own instructions assume
# four 80 GB GPUs; hpc/biominer/biominer.patch cuts its servers to one GPU, and BioMiner-Instruct
# (about 67 GB in bf16) fits on one 141 GB H200 next to the three smaller models.
#
# Everything BioMiner writes goes to the node's local disk and is packed into
# $XN_SCRATCH/biominer/runs/<run_id>.tar at the end; nothing is written to the repo.
set -euo pipefail
source hpc/env.sh
source hpc/biominer/env.sh
xn_provenance
repo="$PWD"

papers=("$@")
[ ${#papers[@]} -gt 0 ] || papers=(1 2 4 6 16 19)
if [ "${papers[*]}" = "1 2 4 6 16 19" ]; then tool=biominer; else tool="biominer-p$(IFS=-; echo "${papers[*]}")"; fi
run_id="$(date +%F)_${tool}_internal"
echo "run:     $run_id (papers ${papers[*]})"

if [ -e "$BIOMINER_ROOT" ]; then
    echo "$BIOMINER_ROOT already exists on $(hostname); is another BioMiner job running here?" >&2
    exit 1
fi
logs="$BIOMINER_ROOT/logs"
cleanup() {
    jobs -p | xargs -r kill 2>/dev/null || true
    sleep 5
    jobs -p | xargs -r kill -9 2>/dev/null || true
    # Keep the server logs even when the job fails; everything else on local disk goes.
    if [ -d "$logs" ]; then
        mkdir -p "$XN_SCRATCH/biominer/runs/$run_id-logs"
        cp -r "$logs"/. "$XN_SCRATCH/biominer/runs/$run_id-logs/"
        echo "logs:    $XN_SCRATCH/biominer/runs/$run_id-logs"
    fi
    rm -rf "$BIOMINER_ROOT"
}
trap cleanup EXIT

# --- Environments, code, weights -------------------------------------------------------------
before=$(date +%s)
tar -C "$(dirname "$BIOMINER_ROOT")" -xf "$BIOMINER_ENV_TAR"
echo "unpack:  $(( $(date +%s) - before )) s; $(df -h /tmp | tail -1)"

src="$BIOMINER_ROOT/src"
git init -q "$src"
git -C "$src" fetch -q --depth 1 "$BIOMINER_REPO" "$BIOMINER_COMMIT"
git -C "$src" checkout -q FETCH_HEAD
git -C "$src" apply "$repo/hpc/biominer/biominer.patch"
echo "biominer: $(git -C "$src" rev-parse --short HEAD) + hpc/biominer/biominer.patch"

ln -s "$(hf_snapshot UniParser/MolDetv2 "$MOLDETV2_REV")/moldet_v2_yolo11n_960_doc.pt" "$src/scripts/"
ln -s "$(hf_snapshot jiaxianustc/MolGlyph "$MOLGLYPH_REV")/molglyph_large.pt" "$src/scripts/"
# BioMiner-Instruct is read once at startup. Copy it to local disk with parallel reads (scratch
# serves several streams faster than one) so vLLM doesn't page it in over the network.
snapshot="$(hf_snapshot jiaxianustc/BioMiner-Instruct "$BIOMINER_INSTRUCT_REV")"
mkdir -p "$BIOMINER_ROOT/biominer-instruct"
before=$(date +%s)
ls "$snapshot" | xargs -P 8 -I{} cp -L "$snapshot/{}" "$BIOMINER_ROOT/biominer-instruct/"
seconds=$(( $(date +%s) - before ))
echo "model:   copied $(du -sm --apparent-size "$BIOMINER_ROOT/biominer-instruct" | cut -f1) MiB to local disk in $seconds s"
ln -s "$BIOMINER_ROOT/biominer-instruct" "$src/scripts/local-biominer-instruct"
for f in "$src"/scripts/{moldet_v2_yolo11n_960_doc.pt,molglyph_large.pt,local-biominer-instruct/config.json}; do
    [ -e "$f" ] || { echo "missing weights: $f (run setup.sbatch weights)" >&2; exit 1; }
done

# MinerU reads its settings from this file. Same as BioMiner's magic-pdf.json except the
# model paths, which point at the pinned snapshots instead of the authors' machine.
export MINERU_TOOLS_CONFIG_JSON="$BIOMINER_ROOT/magic-pdf.json"
"$BIOMINER_ROOT/main/bin/python" - "$src/magic-pdf.json" "$MINERU_TOOLS_CONFIG_JSON" \
    "$(hf_snapshot jiaxianustc/BioMiner-MinerU-Model "$MINERU_MODELS_REV")/mineru_old_version_models" \
    "$(hf_snapshot hantian/layoutreader "$LAYOUTREADER_REV")" <<'EOF'
import json, sys
src, dst, models_dir, layoutreader_dir = sys.argv[1:]
config = json.load(open(src))
config["models-dir"] = models_dir
config["layoutreader-model-dir"] = layoutreader_dir
json.dump(config, open(dst, "w"), indent=4)
EOF

# Keep every cache these tools write (vLLM's compiled graphs, Triton kernels, Ultralytics
# settings) on local disk rather than in home.
export XDG_CACHE_HOME="$BIOMINER_ROOT/cache" XDG_CONFIG_HOME="$BIOMINER_ROOT/config"
export VLLM_CACHE_ROOT="$BIOMINER_ROOT/cache/vllm" TRITON_CACHE_DIR="$BIOMINER_ROOT/cache/triton"
export TORCHINDUCTOR_CACHE_DIR="$BIOMINER_ROOT/cache/inductor" YOLO_CONFIG_DIR="$BIOMINER_ROOT/config/ultralytics"
export PATH="$PATH:$BIOMINER_ROOT/poppler/bin"   # appended, so poppler's bin can't shadow system tools
export PYTHONPATH=.                              # BioMiner imports itself from the checkout
# Explorer's compute nodes set http_proxy, and curl, requests and the OpenAI client would send
# even 127.0.0.1 through it, so BioMiner could never reach its own servers (job 11040623).
export no_proxy=localhost,127.0.0.1,0.0.0.0 NO_PROXY=localhost,127.0.0.1,0.0.0.0
mkdir -p "$logs"
cd "$src"

wait_for() {
    # wait_for <name> <url> <seconds> <pid>: poll until the server answers, or fail if it exits.
    local t=0
    until curl -sf --noproxy "*" "$2" >/dev/null; do
        kill -0 "$4" 2>/dev/null || { echo "$1 exited; last lines of its log:" >&2; tail -40 "$logs/$1.log" >&2; exit 1; }
        [ "$t" -lt "$3" ] || { echo "$1 not up after $3 s" >&2; tail -40 "$logs/$1.log" >&2; exit 1; }
        sleep 10; t=$((t + 10))
    done
    echo "$1 up after $t s"
}

# --- Servers ----------------------------------------------------------------------------------
# vLLM starts first: it measures free GPU memory while it loads, and asserts if other processes
# change it meanwhile. 0.75 of 141 GB holds the 67 GB of weights plus about 30 GB of KV cache,
# leaving about 35 GB for the other three servers. BioMiner's own script
# (scripts/run_local_vllm_server_biominer_instruct.bash) uses 4-way tensor parallelism, a
# 128k context and --allowed-local-media-path /data, which errors when /data doesn't exist.
"$BIOMINER_ROOT/vllm/bin/python" -m vllm.entrypoints.openai.api_server \
    --model scripts/local-biominer-instruct \
    --served-model-name local-biominer-instruct \
    --trust-remote-code \
    --tensor-parallel-size 1 \
    --gpu-memory-utilization 0.75 \
    --max-model-len 65536 \
    --swap-space 32 \
    --async-scheduling \
    --port 8613 > "$logs/vllm.log" 2>&1 &
wait_for vllm http://127.0.0.1:8613/health 2400 $!
grep -E "Loading weights took|Model loading took|torch.compile takes|Graph capturing finished|init engine|GPU KV cache size|Maximum concurrency" \
    "$logs/vllm.log" | sed -E 's/^.*\] //' | cut -c1-160 | sed 's/^/vllm:    /' || true

"$BIOMINER_ROOT/main/bin/python" scripts/mineru_server.py > "$logs/mineru.log" 2>&1 &
mineru=$!
"$BIOMINER_ROOT/main/bin/python" scripts/moldet_server.py > "$logs/moldet.log" 2>&1 &
moldet=$!
"$BIOMINER_ROOT/main/bin/python" scripts/ocsr_server.py > "$logs/ocsr.log" 2>&1 &
ocsr=$!
wait_for mineru http://127.0.0.1:8002/health 900 $mineru
wait_for moldet http://127.0.0.1:8001/health 600 $moldet
wait_for ocsr http://127.0.0.1:8003/health 600 $ocsr
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader | sed 's/^/gpu mem: /'

# --- Pipeline ---------------------------------------------------------------------------------
mkdir -p "$BIOMINER_ROOT/pdfs"
for p in "${papers[@]}"; do cp "$repo/data/internal/$p.pdf" "$BIOMINER_ROOT/pdfs/"; done
out="$BIOMINER_ROOT/out/$run_id"
before=$(date +%s)
set +e
"$BIOMINER_ROOT/main/bin/python" example_open_source.py \
    --config_path BioMiner/config/default_open_source.yaml \
    --pdf "$BIOMINER_ROOT/pdfs" --output_dir "$out" 2>&1 | tee "$logs/pipeline.log"
status=${PIPESTATUS[0]}
set -e
echo "pipeline: exit $status after $(( $(date +%s) - before )) s"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader | sed 's/^/gpu mem: /'

# BioMiner reports a failed LLM call as an empty answer rather than an error, so count them.
echo "llm calls that failed: $(grep -c 'try failed' "$logs/pipeline.log" || true)"

# --- Keep the results -------------------------------------------------------------------------
mkdir -p "$XN_SCRATCH/biominer/runs"
cp "$MINERU_TOOLS_CONFIG_JSON" "$logs/"
tar -C "$BIOMINER_ROOT" -cf "$XN_SCRATCH/biominer/runs/$run_id.tar" "out/$run_id" logs
echo "results: $XN_SCRATCH/biominer/runs/$run_id.tar ($(du -h "$XN_SCRATCH/biominer/runs/$run_id.tar" | cut -f1))"
exit "$status"
