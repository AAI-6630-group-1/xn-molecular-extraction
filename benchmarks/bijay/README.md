# Reader benchmark: DECIMER, MolGrapher and DeepSeek-OCR-2 on BioVista

Tasks 1.2 and 1.3 (issue #36). Each reader gets the same BioVista OCSR crops that MolScribe and MolGlyph
read in [`benchmarks/willdaly/run_biovista.py`](../willdaly/run_biovista.py), so the reader is the only
variable. Output is in the team's results format ([`benchmarks/README.md`](../README.md)) and is scored
by the shared [`score_biovista.py`](../score_biovista.py). Scored runs are in
[`benchmarks/results/ArkAngel101/`](../results/ArkAngel101).

## Results

BioVista OCSR, test split (8,006 crops), exact match of canonical SMILES. Will's MolScribe and MolGlyph rows
are in [`benchmarks/results/comparison.md`](../results/comparison.md).

| Reader | Exact match | Stereo-blind | Mean Tanimoto | Plain structures | Chiral | Markush | Invalid output |
|---|---|---|---|---|---|---|---|
| DECIMER 2.8.0 | 30.0% | 32.7% | 0.632 | 54.5% | 33.4% | 0.0% | 14.3% |
| MolGrapher (no-stereo model) | 23.8% | 36.5% | 0.620 | 43.2% | 0.0% | 0.0% | 6.0% |
| DeepSeek-OCR-2 (SMILES prompt) | 13.3% | 14.6% | 0.401 | 24.1% | 8.8% | 0.0% | 16.9% |

Read these numbers with the following in mind:

- **Markush is 0% by construction.** BioVista writes an R-group as `*`. None of the three readers' predictions
  contains `*` (checked in each run's `matches.csv`), so an exact match is impossible. The 0% means these
  readers can't write R-groups the way BioVista expects, not that they misread the rest of the molecule.
- **MolGrapher's chiral 0% is a setup choice.** It ran its default `gc_no_stereo_model`, which doesn't predict
  stereochemistry. Its stereo-blind score on chiral crops is 46.3%.
- **DeepSeek-OCR-2 is a general document model, not a chemistry model.** The prompt is
  `Convert the chemical structure in this image to a SMILES string. Output only the SMILES.`; it was not tuned.
  It answers as `<smiles>...</smiles>`, which `reader.py` strips (`raw` keeps the original). It gives no confidence.
- Nothing was tuned on the test split. Every run is the tool as configured here.

## Layout

| Path | What it is |
|---|---|
| `common/ocsr_run.py` | One runner for every reader: crops in, `predictions.csv` and `run.json` out. Standard library only, so it runs in any reader's environment. Supports `--shard I/N`, `--limit` and `--resume`, and stops after 3 chunks in a row where every crop failed |
| `common/merge_shards.py` | Joins the shard files into the `predictions.csv` and `run.json` the scorer reads |
| `<reader>/reader.py` | The reader itself: `load(device) -> (predict, versions)`. `predict(paths)` returns `[{"smiles", "confidence", "raw"}, ...]`, one per crop |
| `<reader>/requirements.txt`, `setup_env.sh` | The reader's own environment (they can't share one: DECIMER needs TensorFlow, DeepSeek-OCR-2 pins torch 2.6, MolGrapher is installed from a clone) |
| `<reader>/run.sbatch` | One array job per reader; each array task reads one shard of the crops |
| `submit_all.sh` | Submits all three readers at once (see the job-limit note below) |
| `freeze_env.sh` | Writes `<reader>/requirements.lock.txt` from a working environment |

Readers are `decimer`, `molgrapher` and `deepseek_ocr2`. This folder is named `bijay`; results are under
`benchmarks/results/ArkAngel101/` because that is the GitHub handle the team's format uses.

## What was checked

- The runner's sharding, `--resume`, batch-failure retry, per-crop error handling and the merge (including
  its missing-part and duplicate checks), with a fake reader. All shell scripts pass `bash -n`.
- Each reader on real crops: a 10–20 crop smoke test, then the full 8,861 crops. No crop crashed (no empty
  answers in any run).
- The crop IDs in each run are identical to Will's MolScribe and MolGlyph runs, and the scoring files
  (`score.py`, `score_biovista.py`, `score_boxes.py`) are the repo's, unmodified.

## Run it on Explorer

Set `<account>` to your Slurm account and `$P` to the project folder on the cluster. Nothing in the code is tied to a username.

**1. Get the crops (laptop).** From the repo root, after `uv sync`:

```bash
uv run python benchmarks/willdaly/download_data.py --biovista     # leaves data/biovista/ocsr.tar.gz
scp data/biovista/ocsr.tar.gz explorer:$P/
scp -r benchmarks/bijay explorer:$P/
```

Explorer creates small files slowly, so the crops travel as one archive.

**2. Unpack the crops and build the environments (cluster, inside `srun ... --pty bash`, never on the login node).**

```bash
mkdir -p $P/biovista && tar xzf $P/ocsr.tar.gz -C $P/biovista   # gives $P/biovista/ocsr/data/*.png; about 3 minutes
cd $P/bijay
bash decimer/setup_env.sh                                        # or reuse a working DECIMER environment
XN_ENV_ROOT=$HOME/xn_envs bash molgrapher/setup_env.sh
XN_ENV_ROOT=$HOME/xn_envs bash deepseek_ocr2/setup_env.sh        # XN_CUDA_MODULE=cuda/12.3.0 is the default
```

**3. GPU choice.** DECIMER (TensorFlow 2.20) failed on every crop on a V100 (driver 545, "cuDNN status 5003")
and worked on an H200, so its job asks for an H200. MolGrapher needs CUDA 11.7 builds, which have no kernels
for the H200, so its job asks for a V100. DeepSeek-OCR-2 needs bf16 and FlashAttention, so it asks for an A100.

**4. Smoke test each reader (20 crops).** Inside a GPU session, with the reader's environment active:

```bash
python common/ocsr_run.py --reader decimer --crops-dir $P/biovista/ocsr/data --limit 20 --run-id smoke_decimer
```

MolGrapher must run from its clone, with its library folder on the path, because it loads weights from `./data`
and PaddlePaddle needs the symlinks:

```bash
export LD_LIBRARY_PATH=$HOME/xn_envs/cuda11_shim:$HOME/xn_envs/molgrapher/lib/python3.11/site-packages/torch/lib:$LD_LIBRARY_PATH
cd $HOME/xn_envs/molgrapher-src
python $P/bijay/common/ocsr_run.py --reader molgrapher --crops-dir $P/biovista/ocsr/data --limit 20 --run-id smoke_molgrapher
```

Look at the `smiles` and `raw` columns of `results/smoke_*/predictions.csv` before the full run.

**5. Full runs.** Submit from `$P/bijay` on a login node. Set `XN_RUN_ID` yourself, so every shard writes to the same folder even if a task starts after midnight.

```bash
XN_RUN_ID=<date>_decimer_biovista XN_ENV=<decimer env> XN_CROPS=$P/biovista/ocsr/data \
  sbatch --account=<account> decimer/run.sbatch
XN_RUN_ID=<date>_deepseek_ocr2_biovista XN_ENV=<deepseek env> XN_CROPS=$P/biovista/ocsr/data \
  sbatch --account=<account> deepseek_ocr2/run.sbatch
XN_RUN_ID=<date>_molgrapher_biovista XN_ENV=<molgrapher env> MOLGRAPHER_SRC=<clone> XN_CUDA11_SHIM=<shim> \
  XN_CROPS=$P/biovista/ocsr/data sbatch --account=<account> molgrapher/run.sbatch
```

Each array has 4 tasks (about 2,215 crops each). `submit_all.sh` does all three, but Explorer rejected a
submission that would have put 13 jobs in the queue and accepted 9, so submit one reader at a time if it
complains. If a task fails and you rerun just that one, pass `XN_NUM_SHARDS=4` and `--array=<index>` (the
MolGrapher script reads it), because the shard total otherwise comes from the array size. The logs print seconds per crop. A task killed at the time limit can be resubmitted:
`--resume` skips the crops already written.

Observed times on the BioVista run (4 shards each): DECIMER about 16 minutes per shard on an H200,
MolGrapher about 65–90 minutes on a V100, DeepSeek-OCR-2 about 2–2.5 hours on an A100.

**6. Merge and score.**

```bash
python3 common/merge_shards.py results/<run_id>         # on the cluster; it refuses to merge if a part is missing
scp explorer:$P/bijay/results/<run_id>/{predictions.csv,run.json} benchmarks/results/ArkAngel101/<run_id>/
python benchmarks/score.py benchmarks/results/ArkAngel101/<run_id>
```

Scoring needs only RDKit 2026.3.2 and numpy 1.26.4 on Python 3.11 (`uv sync` gives the full project environment; a
small separate environment with those two packages also works). It also reads BioVista's labels and split
lists from `data/biovista/` (`ocsr/labels/gd_SMIELS.csv`, `test_set_names.txt`, `valid_set_names.txt`), which `download_data.py --biovista` puts there.

Commit the four files (`run.json`, `predictions.csv`, and the `scores.csv` and `matches.csv` the scorer writes), not the `.part` files. Set `XN_GIT_COMMIT` (or edit `git_commit` in `run.json`) to the commit the code was run from.

## Notes

- A crop a reader fails on is written with an empty SMILES and the error in `raw`; the scorer counts it as no output.
- MolGrapher writes a `*_preprocessed.png` next to every image it reads, so `reader.py` gives it temporary copies; reading from the shared crops folder polluted it once. It also deletes its visualization folder at start-up, which crashed a shard that started while another was writing; `reader.py` skips that one delete.
- `matches.csv` has one row per unique molecule, so it has fewer rows than the number of crops.
