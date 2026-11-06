# 0002. We use an installed Python package with the existing locked dependencies

Status: Accepted on 2026-11-06
Related specs: docs/specs/mvp.md

## Context
A solo developer has less than two days. The environment already holds Python 3.14 and a locked
dependency set, which also runs the official `retrofit_sim` package. The organizers may re-run
finalists' code on truncated telemetry, so the code must be easy to invoke and audit. The official
package is read-only, and the deliverable is a CSV plus a recorded demo.

## Criteria
1. No setup risk during the challenge.
2. One command for each deliverable, reproducible by a third party.
3. Runtime code that can be audited for causality and permitted inputs.
4. No duplication of official logic, so scores stay comparable.

## Options
| Option | Pro | Con |
| --- | --- | --- |
| A. Installed package, CLI, locked dependencies, static matplotlib report | One new pinned build tool only; one entry point; clean module boundaries | Needs a `pyproject.toml` and editable installs |
| B. Loose scripts in the repo | No packaging step | Weak boundaries, duplicated setup, harder for others to run |
| C. Web app or interactive charts | Richer demo | New dependencies, a server, and time taken from detection |

## Decision
We choose option A because it adds no runtime dependency and gives one audited entry point.

- Python 3.14 with `requirements-lock.txt`: pandas, pyarrow, numpy, scipy, matplotlib. No new
  dependency without a written reason in a new ADR.
- setuptools is pinned in `requirements-lock.txt`. It is the build backend for both packages
  (`setuptools.build_meta`, official requirement `setuptools>=61`) and the only build requirement
  declared. Pinning it makes the build reproducible instead of depending on a download at build time.
- Package `src/retrofit_assistant/` with `pyproject.toml` at the repo root. Versions live only in
  `requirements-lock.txt`.
- Reproducible setup, in this order:
  `python -m pip install -r requirements-lock.txt`
  `python -m pip install -e challenge/RETROFIT_AI_PARTICIPANTS_2026 --no-build-isolation --no-deps`
  `python -m pip install -e . --no-build-isolation --no-deps`
- pytest with `testpaths = ["tests"]`. The official tests run separately, once, at the freeze.
- A smoke gate runs first: UTC-aware parquet loading, and the official scorer returning 78.0 on the
  published B1 validation predictions.
- CLI: `python -m retrofit_assistant predict --data ... --split {train,validation,test} --out ...`
  and `python -m retrofit_assistant report --asset ... --data ... --predictions ... --out build/report/`.
  The spec adds `check-submission`, `compare` and `ablate`.
- Report: static HTML with matplotlib charts embedded as base64, no server, no external JS.
- `retrofit_sim` is reused only by import: `regime_frame`, `b1_threshold`, `CH`, `COUPLED`, `score`
  and `load_predictions`. Nothing under `challenge/` is copied or modified. It stays installed as
  in the AGENTS.md setup and is not declared as a dependency, because it is not on a package index.

## Consequences
- We gain a single reproducible entry point and scores computed by the official code.
- Causal B1 depends on `retrofit_sim` column names. This is safe while the package stays frozen.
- The report is not interactive, and the demo relies on a recorded walkthrough.
- Installing the lock file needs network access once. Editable installs then need none.
- Revisit if the editable install fails, or if the report cannot show the evidence clearly.
