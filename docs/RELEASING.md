# Releasing

The whole procedure for a release, on one page (the owner, 2026-11-28, "Streamline the release
procedure"). A normal release takes about an hour. The owner is asked once.

## The owner's part

- **One go**, on a card at the start: merge, tag and ship vX.Y.Z, with the code now and the map
  later (a release held only for `lua/` or `valhalla/vendor/`), or with the map, or hold. That
  answer covers the merge to main, the tag and the agent's deploy. It lapses if a reviewer calls a hold or a fix changes what the release does; then ask
  again.
- **One pasted line** only when the beta agent holds the release: the `ship-held` line its report
  gives (below). Map swaps and anything with sudo stay his.

## The steps

1. **Start.** `python3 scripts/bump_version.py X.Y.Z` on the release branch. If main has commits
   the branch lacks, merge main in. Open the release pull request into main as a draft now: CI
   runs on the release branch from here, and each push replaces the run still going. Post the go
   card.
2. **Review, while CI runs.** Eight reviewer agents, one per lens: correctness, ops, spec,
   scope, tests, a11y, simplicity and docs consistency (docs/releases/README.md), patches
   included (the owner, 2026-11-28: "One reviewer per lens is better. The cost isn't huge").
   The tests and a11y reviewers run `npm run build` and the browser check when `frontend/src`
   changed. A fix is re-checked by the reviewer that asked for it, on the fix's diff only. Give
   the reviewers the known-deferred list so they don't report it again.
3. **Local checks before each push:** `ruff check src tests scripts mcp`, `ruff format --check src
   tests scripts mcp`, `npm test` and `npm run build` in `frontend/` if it changed, and pytest for
   the areas touched. The full suites, browser and a11y included, are CI's run on the release
   branch; don't repeat them locally.
4. **Notes, before the last push:** `docs/releases/vX.Y.Z.md` for riders (short, pictures first),
   the full notes in the pull request's description, the about pages at `DOCS_RELEASE=X.Y.Z`. A
   deploy step the beta needs goes in the pull request too, never in docs/OPERATIONS.md.
5. **Merge, once CI is green and the go is in.** If the go said code first, add the `code-first`
   label to the pull request. Then fast-forward main to the commit CI passed, by its id:
   `git push origin <tested sha>:main`. It refuses if main has moved: merge main into the
   branch, let CI pass, push again. The Release workflow then builds the image and makes the tag
   by itself (`.github/workflows/release.yml`); nothing waits for approval in GitHub. It runs only
   on the push that bumps the version, so if that run fails, run it by hand (Actions, Release,
   Run workflow, on main).
6. **Beta.** The agent deploys the tag on its next pass (about 10 minutes) and the release notes
   post to Discord by themselves. If it holds the tag, its report names the one line to send the
   owner: `auto-release.sh ship-held vX.Y.Z` with `--map RUN_URL`, `--no-map` or `--accept` as it
   says. No dry run first: ship-held makes every check before it changes anything.
7. **After.** Make the next release branch from main; open pull requests target it.

## Commands the owner runs

A reviewer agent checks a command block written for this release before the owner gets it. A
script in the repository run with its documented arguments (`ship-held`, `rollback`,
`import-result.sh`) is already reviewed and tested, so it goes as it is. Each line is its own
copyable box.

## What stays, and why

- The owner's go before main: a tag is never moved, and a tag deploys to the beta he rides on.
- The agent's database snapshot before a migration, with automatic rollback: protects beta's data.
- The image provenance check: only an image the Release workflow built from the tagged commit runs.
- `test` and `a11y` green on the exact tree: it is the one full test of the release.
- One reviewer on every pull request into the release branch.
