# GitHub PR Tool

Fetch and merge GitHub pull requests into your local branch. Perfect for:
- Trying upstream PRs before they're merged
- Incorporating features from open PRs into your fork
- Testing PR compatibility locally

## Prerequisites

- `gh` CLI authenticated (`gh auth login`)
- Git repository with remotes configured

## Commands

### Preview a PR
```bash
gh pr view <pr-number> --repo <owner/repo>
```
Shows PR title, author, status, files changed, CI status, and recent comments.

### Fetch PR branch locally
```bash
gh pr checkout <pr-number> --repo <owner/repo>
```
Checks out the PR head into a local branch.

### Merge PR into current branch
```bash
# Fetch the PR branch first, then merge into your working branch
gh pr checkout <pr-number> --repo <owner/repo>
git checkout <your-branch>
git merge pr-branch-name
```
Fetches and merges the PR. Optionally run install after merge.

### Full test cycle
```bash
# Fetch, merge, install dependencies, and run build + tests
gh pr checkout <pr-number> --repo <owner/repo>
git checkout <your-branch>
git merge pr-branch-name
npm install  # or pip install, etc.
npm run build && npm test
```

## Notes

- PRs are fetched from the `upstream` remote by default
- Use `--repo <owner/repo>` to specify a different repository
- Merge conflicts must be resolved manually
- Auto-detects package manager (npm/pnpm/yarn/bun) for install steps
