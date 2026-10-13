# Full BioMiner on Explorer

Runs [BioMiner](https://github.com/jiaxianyan/BioMiner) end to end on the internal papers on one H200 (#18). It uses the same detector (MolDetV2) and reader (MolGlyph) as `benchmarks/willdaly/`, and adds two stages: MinerU layout analysis, and BioMiner-Instruct, a Qwen3-VL-32B model that links each drawing to its compound label and expands scaffold-plus-R-group tables into full molecules. BioMiner-Instruct runs locally through vLLM, so there is no API cost.

BioMiner's instructions assume four 80 GB GPUs. BioMiner-Instruct is about 67 GB in bf16, so on a 141 GB H200 it fits on one card next to the three smaller models.

| File | What it is |
|---|---|
| `env.sh` | Pinned BioMiner commit and model revisions, and where the environments and token live |
| `requirements-main.txt`, `requirements-vllm.txt` | BioMiner's two conda environments as pip pins (see the comments at the top) |
| `main.lock.txt`, `vllm.lock.txt` | The same, fully resolved for Linux; what `setup.sbatch` installs |
| `biominer.patch` | One-GPU changes to BioMiner: each server runs one worker, and MinerU no longer overrides `CUDA_VISIBLE_DEVICES` |
| `download_weights.py` | Fetches the pinned weights into the Hugging Face cache on scratch (about 70 GB) |
| `setup.sbatch` | `envs` builds the environments and poppler on local disk and packs them into one archive on scratch; `weights` runs `download_weights.py` |
| `run.sbatch` | Starts vLLM and BioMiner's three model servers on one H200, runs the papers, and packs everything into `/scratch/$USER/xn/biominer/runs/<run_id>.tar` |

## One-time setup

1. On Hugging Face, accept the terms for [BioMiner-Instruct](https://huggingface.co/jiaxianustc/BioMiner-Instruct) and [MolGlyph](https://huggingface.co/jiaxianustc/MolGlyph).
2. Put a token on the cluster, readable only by you (a read-only token is enough). From your laptop:

   ```bash
   ssh explorer 'umask 077 && mkdir -p ~/.cache/huggingface && cat > ~/.cache/huggingface/token' < ~/.cache/huggingface/token
   ```

3. Build and download (both run on CPU nodes):

   ```bash
   ssh explorer 'cd xn-molecular-extraction && sbatch hpc/biominer/setup.sbatch envs && sbatch hpc/biominer/setup.sbatch weights'
   ```

## Each run

```bash
hpc/deploy.sh
ssh explorer 'cd xn-molecular-extraction && sbatch hpc/biominer/run.sbatch 16'   # one paper
ssh explorer 'cd xn-molecular-extraction && sbatch hpc/biominer/run.sbatch'      # all six
```

The Slurm log (`/scratch/$USER/xn/logs/xn-biominer-<jobid>.out`) shows how long each server took to start, GPU memory in use, and how many language-model calls failed. Copy the archive back with `ssh explorer 'cat /scratch/$USER/xn/biominer/runs/<run_id>.tar' | tar -C data/biominer_runs -xf -`. It holds MinerU's output and page images from the papers, so it stays in the gitignored `data/`.

## Things to know

- **Failed language-model calls aren't errors.** If the vLLM server isn't answering, BioMiner records an empty answer and caches it in the output folder. Every run starts from an empty output folder, and the log counts the failures.
- **One job per node.** The environments unpack to a fixed path, `/tmp/$USER-biominer`, because virtual environments record absolute paths. A second job on the same node stops with a message rather than overwriting it.
- **Fixed ports.** BioMiner's code calls its servers on ports 8001-8003 and 8613.
- **Licenses.** BioMiner's code and MolGlyph are MIT. MolDetV2 and layoutreader are CC BY-NC-SA 4.0. BioMiner-Instruct states no license (its base, Qwen3-VL-32B, is Apache 2.0). Fine for coursework; check before any other use.
