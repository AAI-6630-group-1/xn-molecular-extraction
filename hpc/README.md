# Running on Northeastern's Explorer cluster

Scripts for running this repo's code on [Explorer](https://rc-docs.northeastern.edu/), Northeastern's Slurm cluster, from a laptop. You (or an AI coding tool on your laptop) run short `ssh explorer '<command>'` calls; all computing happens in Slurm jobs on compute nodes. Code reaches the cluster through GitHub, so a job always runs a pushed commit.

| File | What it does |
|---|---|
| `env.sh` | Sourced by every job: puts uv on `PATH`, sends caches (uv, Hugging Face, torch) to scratch, and defines `xn_provenance`, which logs node, GPU, commit, and the exact package list |
| `setup.sbatch` | Builds the pinned environment on a compute node with the CUDA 12.6 torch build, then runs the tests |
| `track3_gpu.sbatch` | Runs `benchmarks/willdaly/run_track3.py` on a GPU and scores the run |
| `deploy.sh` | Run on your laptop: checks out your current pushed commit in the cluster clone |
| `fetch.sh` | Run on your laptop: copies result folders from the cluster clone back into yours |
| `biominer/` | Full BioMiner on one H200, with its own environments ([biominer/README.md](biominer/README.md)) |

## GPUs and the torch build

Explorer's GPU drivers predate CUDA 13, which the default Linux torch wheel (`torch==2.14.0` from PyPI) needs; with it, torch silently falls back to the CPU. `pyproject.toml` therefore has two torch groups. Laptops get `torch-pypi` by default and nothing changes for them. The cluster syncs with `--no-group torch-pypi --group torch-cu126`, the CUDA 12.6 build of the same version, which runs on these drivers. `env.sh` sets `UV_NO_SYNC=1` so that `uv run` doesn't swap the default build back in.

Checked on 2026-10-13 with `nvidia-smi` in `gpu-short` jobs:

| GPU | Driver (max CUDA) | Compute capability | Memory |
|---|---|---|---|
| Tesla T4 | 570.86.15 (12.8) | 7.5 | 16 GB |
| Tesla V100-SXM2 | 545.23.08 (12.3) | 7.0 | 32 GB |
| NVIDIA H200 | 570.86.15 (12.8) | 9.0 | 141 GB |

| Partition | Time limit | GPUs |
|---|---|---|
| `gpu-short`, `gpu-interactive` | 2 h | V100, T4, A100, H200 (same nodes as `gpu`) |
| `gpu` | 8 h | V100, T4, A100, H200 |
| `courses-gpu` | 24 h | P100, V100 |
| `short` | 2 days | CPU only |

Ask for any GPU with `--gres=gpu:1`, or a type with `--gres=gpu:a100:1` (types: `t4`, `v100-pcie`, `v100-sxm2`, `a100`, `h200`, `p100`). Options on the `sbatch` command line override the `#SBATCH` lines in the scripts.

## One-time setup

1. **Account.** Course access lasts only for the course. Otherwise, [request an individual account](https://rc.northeastern.edu/getting-access/) with a faculty sponsor.

2. **SSH from your laptop.** Add to `~/.ssh/config`, then log in once with your Northeastern password and set up key login (`ssh-copy-id explorer`):

   ```
   Host explorer
     HostName login.explorer.northeastern.edu
     User <your-username>
     ServerAliveInterval 60
     ControlMaster auto
     ControlPath ~/.ssh/cm-%r@%h-%p
     ControlPersist 10m
   ```

   `ControlMaster` reuses one connection, so a run of short `ssh explorer '...'` commands doesn't log in each time.

3. **uv on the cluster**, in `~/.local/bin`. Use the version from `uv --version` on your laptop, and check the release checksum:

   ```bash
   ssh explorer 'V=0.9.30; T=uv-x86_64-unknown-linux-gnu; cd $(mktemp -d) &&
     curl -fsSLO https://github.com/astral-sh/uv/releases/download/$V/$T.tar.gz &&
     curl -fsSLO https://github.com/astral-sh/uv/releases/download/$V/$T.tar.gz.sha256 &&
     sha256sum -c $T.tar.gz.sha256 && tar xzf $T.tar.gz && mkdir -p ~/.local/bin &&
     install -m 755 $T/uv $T/uvx ~/.local/bin/'
   ```

   Non-login shells read only `~/.bashrc`, so add `export PATH="$HOME/.local/bin:$PATH"` there too.

4. **Clone with a read-only deploy key.** The repo is private, and the cluster shouldn't hold your own GitHub credentials. On the cluster:

   ```bash
   ssh-keygen -t ed25519 -N "" -C "explorer $USER xn-molecular-extraction" -f ~/.ssh/xn_deploy
   cat ~/.ssh/xn_deploy.pub
   ```

   A repo admin adds the public key under **Settings > Deploy keys** with write access off. Then, on the cluster:

   ```bash
   printf 'Host github.com\n  IdentityFile ~/.ssh/xn_deploy\n  IdentitiesOnly yes\n' >> ~/.ssh/config
   git clone git@github.com:AAI-6630-group-1/xn-molecular-extraction.git ~/xn-molecular-extraction
   ```

   Check that the GitHub host key fingerprint ssh shows on first connection matches [GitHub's published fingerprints](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints). Each person's cluster account needs its own deploy key.

5. **Environment.** Create the log folder (Slurm won't create it), then build:

   ```bash
   ssh explorer 'mkdir -p /scratch/$USER/xn/logs && cd xn-molecular-extraction && sbatch hpc/setup.sbatch'
   ```

   The log is in `/scratch/$USER/xn/logs/xn-setup-<jobid>.out`. Rerun after any change to `uv.lock`.

6. **Data.** Put the internal papers in the cluster clone's `data/internal/`, the same layout as on your laptop (see [data/README.md](../data/README.md)). They are course-use only, so keep them in your home directory. Either upload `Dataset 2.zip` through the [Open OnDemand](https://ood.explorer.northeastern.edu) file browser and unzip it there, or stream your local copy. Don't use rsync from a Mac: macOS ships openrsync, which fails against the cluster's rsync with "unexpected end of file". Use tar instead:

   ```bash
   cd data && COPYFILE_DISABLE=1 tar --no-mac-metadata -cf - internal | ssh explorer 'tar -C xn-molecular-extraction/data -xf -'
   ```

   GNU tar on the cluster prints "Ignoring unknown extended header keyword" for macOS file tags; that's harmless. Home and scratch are network filesystems that create small files at only 2 or 3 a second from the login node. That's fine for the seven internal files. For anything with thousands of files, send one archive and unpack it in a job, which ran at about 90 files a second (11,651 files in 128 s):

   ```bash
   cd data && COPYFILE_DISABLE=1 tar --no-mac-metadata -cf - patent300 biovista | ssh explorer 'cat > /scratch/$USER/xn/datasets.tar'
   ssh explorer 'cd xn-molecular-extraction/data && srun -p short -c 2 --mem=4G -t 00:30:00 tar -xf /scratch/$USER/xn/datasets.tar && rm /scratch/$USER/xn/datasets.tar'
   ```

   Or download Patent300 and BioVista directly on the cluster:

   ```bash
   ssh explorer 'cd xn-molecular-extraction && source hpc/env.sh &&
     srun -p short -c 2 --mem=8G -t 00:30:00 uv run python benchmarks/willdaly/download_data.py'
   ```

## Each run

```bash
git push -u origin HEAD                      # the cluster only sees pushed commits
hpc/deploy.sh                                # check out that commit on the cluster
ssh explorer 'cd xn-molecular-extraction && sbatch hpc/track3_gpu.sbatch --tool moldetv2-molscribe-cuda'
ssh explorer 'squeue -u $USER'               # wait; then read /scratch/$USER/xn/logs/xn-track3-<jobid>.out
hpc/fetch.sh benchmarks/results/willdaly/<date>_moldetv2-molscribe-cuda_internal
```

Commit the fetched run folder as usual. `run.json` names the GPU, and the Slurm log has the node, driver, and package list.

The job writes crops to the node's local disk and packs them into `/scratch/$USER/xn/crops/<run_id>.tar`, so they don't land in the cluster clone's `data/track3_runs/`. Writing them to home cost about 0.6 s per box. To look at them on your laptop:

```bash
ssh explorer 'cat /scratch/$USER/xn/crops/<run_id>.tar' | tar -C data/track3_runs -xf -
```

## Rules

- **Login nodes** (explorer-01, explorer-02) are only for light commands: `git`, `sbatch`, `squeue`, `sacct`, `rsync`, `ls`. Anything that computes or installs runs in a job (`srun` for a short interactive step, `sbatch` for everything else). Don't start Jupyter, an IDE server, or an AI coding agent on a login node. VS Code Remote SSH gets disconnected there for this reason; use the VS Code app in Open OnDemand if you want an editor on the cluster.
- **Edit code only on your laptop.** The cluster clone stays at a pushed commit (`deploy.sh` refuses uncommitted changes), so every result traces to a commit.
- **Scratch is for caches and logs.** It isn't backed up. Copy anything you want to keep back to your laptop.
