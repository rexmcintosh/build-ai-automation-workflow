# Project conventions for Claude Code

## Branching & commits
- **Never commit to `main`.** Always work on a feature branch named `feat/<short-slug>`, `fix/<short-slug>`, or `chore/<short-slug>`.
- Commit small and often. A commit per logical chunk, conventional-commit style:
  `feat(auth): add github oauth callback`, `fix(api): handle null user`, etc.
- After each commit, push to the remote.

## Pull requests
- When the feature/fix is complete, open a **draft** PR with `gh pr create --draft --fill`.
- A GitHub Action will run the Venice review council. The check is named `venice/review`.
- Read the consolidated review comment. Address blocking items in fixup commits on the same branch.
- Do **not** mark the PR ready and do **not** merge. The human merges.

## Deploys
- Merging to `main` triggers the deploy workflow. Don't try to deploy manually.

## Editing
- Prefer editing existing files over creating new ones.
- No new dependencies without flagging it in the PR description.
- No `console.log`/`print` debug noise left behind.
- Run the project's lint + test scripts before opening the PR. If a test fails, fix it or explain it in the PR — never disable a test silently.

## Secrets
- Never commit `.env`, keys, or tokens. The repo's `.gitignore` already excludes them.
- If a secret is needed at runtime, add a placeholder in `.env.example` and mention it in the PR.
