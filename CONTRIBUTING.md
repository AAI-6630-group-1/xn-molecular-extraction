# How we work

Everything we work on is an issue on the [project board](https://github.com/orgs/AAI-6630-group-1/projects/1). If it is not on the board, the rest of the team cannot see it.

## Issues

- Click **New issue** and pick a template (Task, Bug, or Meeting notes). Templates add the issue to the project board for you.
- Graded course tasks are the issues labeled `deliverable` ([#1](https://github.com/AAI-6630-group-1/xn-molecular-extraction/issues/1) to [#12](https://github.com/AAI-6630-group-1/xn-molecular-extraction/issues/12)). Individual deliverables have one sub-issue per person; group deliverables have sub-issues for the work. Break work down further with your own sub-issues.
- Assign yourself when you pick something up, and move its **Status** as it progresses: Backlog, Todo, In Progress, In Review, Done.
- Set **Due** on anything with a deadline so it shows up in the [Due Soon](https://github.com/orgs/AAI-6630-group-1/projects/1/views/5) view.

## Branches and pull requests

- Branch from `main` and name the branch `<your-handle>/<issue-number>-short-description`, for example `liba-jin/34-molscribe-benchmark`.
- Put `Closes #<issue-number>` in the PR description. The issue closes, and its card moves to Done, when the PR merges.
- Ask at least one teammate for a review before merging. Squash merging keeps the history of `main` easy to read.
- Commit code, configs, and small results files. Do not commit PDFs, datasets, model weights, API keys, or `.env` files.

## Code

- Python with a pinned environment (see the README). Record tool and package versions for every benchmark result.
- Keep GPU use optional unless we confirm cluster access.
- Docstrings on non-trivial functions; `pytest` tests for pipeline modules (task 2.3).
- The course expects agentic AI (Claude, VS Code) for the extraction code. Read and run what it writes before opening a PR, and say in the PR which parts it generated.

## Weekly routine

1. Before Tuesday class: update the status of your items and check the **Due Soon** view.
2. When Canvas publishes an assignment: update that deliverable's **Due** date, set **Date Status** to Confirmed, and paste the requirements into the issue.
3. At the start of each phase: move that phase's items from Backlog to Todo.
