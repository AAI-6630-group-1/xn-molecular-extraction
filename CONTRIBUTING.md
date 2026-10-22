# How we work

Everything we work on is an issue on the [project board](https://github.com/orgs/AAI-6630-group-1/projects/1). If it is not on the board, the rest of the team cannot see it.

## Issues

- Click **New issue** and pick a template (Task, Bug, or Meeting notes). Templates add the issue to the project board for you.
- Graded course tasks are the issues with the **Deliverable** issue type ([#1](https://github.com/AAI-6630-group-1/xn-molecular-extraction/issues/1) to [#12](https://github.com/AAI-6630-group-1/xn-molecular-extraction/issues/12)). Individual deliverables have one sub-issue per person; group deliverables have sub-issues for the work. Break work down further with your own sub-issues.
- Assign yourself when you pick something up, and move its **Status** as it progresses: Backlog, Todo, In Progress, In Review, Done.
- Set **Due** on anything with a deadline so it shows up in the [Due Soon](https://github.com/orgs/AAI-6630-group-1/projects/1/views/5) view.

## Where files go

Everything lives in this one repo, in a subfolder named after your GitHub handle (agreed 2026-10-06, #73):

| What | Where |
|---|---|
| 1.1 setup proposal | `setup-proposals/<handle>/` |
| 1.2 benchmarking code | `benchmarks/<handle>/` (results in `benchmarks/results/<handle>/`) |
| Benchmark code the team shares (scorers, readers) | `benchmarks/` |
| 1.3 and other individual reports | `reports/<handle>/` |
| Pipeline modules (Part 2) | `pipeline/` |

Share files through GitHub, not Slack. Slack is for discussion; a file in the repo is versioned, and everyone (and their AI tools) can find it.

## Branches and pull requests

- Branch from `main` and name the branch `<your-handle>/<issue-number>-short-description`, for example `liba-jin/34-molscribe-benchmark`.
- Put `Closes #<issue-number>` in the PR description. The issue closes, and its card moves to Done, when the PR merges.
- Ask at least one teammate for a review before merging. Squash merging keeps the history of `main` easy to read.
- Commit code, configs, small results files, and your own reports and proposals. Do not commit papers' PDFs, datasets, model weights, API keys, or `.env` files. PDFs are gitignored, so use `git add -f` for a report or proposal PDF.

## Code

- Python with a pinned environment (see the README). Record tool and package versions for every benchmark result.
- GPU-only inference is fine; run it on Explorer (see [hpc/README.md](hpc/README.md)) or your own GPU. Commit each run's predictions and `run.json` so scoring and analysis rerun on a laptop CPU from those files.
- Docstrings on non-trivial functions; `pytest` tests for pipeline modules (task 2.3).
- The course expects agentic AI (Claude, VS Code) for the extraction code. Read and run what it writes before opening a PR, and say in the PR which parts it generated.

## Weekly routine

1. Before Tuesday class: update the status of your items and check the **Due Soon** view.
2. After Tuesday class: short team sync. Take notes with the Meeting notes template.
3. When Canvas publishes an assignment: update that deliverable's **Due** date, set **Date Status** to Confirmed, and paste the requirements into the issue.
4. At the start of each phase: move that phase's items from Backlog to Todo.
