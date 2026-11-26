# R_UPDATE_012 — Experiment 23: Official `SWE-bench Verified` Docker Evaluation of Hybrid Cloud + 4 GB Local Worker Architecture

## A. Update Identification

- **Update ID:** R_UPDATE_012
- **Date and timezone:** 2026-11-26; Africa/Cairo (UTC+02:00)
- **Title:** Experiment 23 — Official `SWE-bench Verified` Docker runner and 3-task (`seed=42`) live evaluation
- **Status and verified scope:** Completed for the 3-task (`seed=42`) official `SWE-bench Verified` Docker evaluation slice (`1/3` resolved overall; `1/2` resolved among non-quota-blocked tasks with valid baselines; **`django__django-16527` RESOLVED `F2P=1/1, P2P=6/6`**) and offline regression checks. Small-sample ($N=3$) checkpoint — no general benchmark solve rate is claimed.
- **Branch:** `feat/experiment23-hybrid-swebench`
- **Actual base revision:** `886ea71a317af373bde7e4e0c3be9b8180288540` (`feat/hybrid-providers`, stacked on PR #5 `feat/hivo-tools` `047179f6a71a6e51c781a4b880a5381518af32e5`).
- **Tested source revision/hashes:** Parent `886ea71` plus `scripts/run_swebench_hybrid.py` (LF-normalized SHA-256 `0a761af9d3ed62d8a62a743796b3dee8aafe304a38efd2c9f19d17faa402e2ba`), curated Experiment 23 report/results/provenance/patches under `reports/experiment23/`, and `reports/INDEX.md`.
- **Containing commit / PR:** Recorded in Git history and upstream PR metadata on `abdoabozena7/mini_hivo` upon publication.
- **Related issue/experiment:** [Experiment 23](../reports/experiment23/experiment23-report.md); stacked directly on [R_UPDATE_011.md](R_UPDATE_011.md) (`feat/hybrid-providers`) and [R_UPDATE_010.md](R_UPDATE_010.md) (`feat/hivo-tools`).
- **Scope:** Adds a reusable, zero-leakage official `SWE-bench Verified` Docker benchmark harness (`scripts/run_swebench_hybrid.py`) and records Experiment 23 (`reports/experiment23/` + `reports/INDEX.md`) documenting architectural changes since Experiment 22 and live Docker-verified results. Zero changes to `mini.py` or `hivo/`.

## B. Original Problem

- **Original request to Mini Hivo:** Run a harder, widely recognized coding benchmark (`SWE-bench Verified`) against the new hybrid Cloud Thinking Orchestrator (`qwen/qwen3.8-27b`) + 4 GB VRAM Local Worker (`qwen3.5:2b-q4_K_M`) architecture, evaluate patches cleanly in official Docker containers, and document Experiment 23 following the repository's existing experiment schema.
- **Expected behavior:** Reproducible (`seed=42`) task selection, zero leakage of gold patches or hidden `test_patch`, disk-safe 1-image-at-a-time Docker handling on a constrained Windows `C:` drive, independent baseline + candidate Docker oracle checks, and structured reports matching `reports/experiment22/`.
- **Observed behavior (before this update):** Only single-file toy E2E verification existed (`scripts/probe_hybrid_models.py`); no `SWE-bench Verified` Docker runner or Experiment 23 report existed, and real multi-thousand-file repositories had not been exercised end-to-end on the hybrid architecture.
- **Execution evidence:** Confirmed `reports/INDEX.md` ended at Experiment 22 and `scripts/` contained no SWE-bench harness.
- **Failure boundary:** Real multi-file repo benchmark reliability of the hybrid architecture was unmeasured.
- **Reproduction before the change:** `scripts/run_swebench_hybrid.py` and `reports/experiment23/` did not exist on `886ea71`.

## C. Why the Update Was Necessary

Single-file toy checks confirm API plumbing but cannot expose real-repository localization, large-repo context growth, Windows Docker extraction hazards, or 2B worker edit accuracy on genuine open-source codebases. Evaluating on official `SWE-bench Verified` Docker containers establishes honest, reproducible baseline evidence for the hybrid architecture introduced in `R_UPDATE_010` and `R_UPDATE_011`.

## D. Root Cause Analysis

Diagnostic failures encountered and resolved during Experiment 23 execution:

| Finding | Classification | Supporting evidence | Remaining uncertainty |
|---|---|---|---|
| Official SWE-bench Docker images install conda at `/opt/miniconda3`, not `/opt/conda` | Proven cause (caught on initial `oracle_eval.log`) | Fixed via universal `/opt/miniconda3` + `/opt/conda` detection and pre-solve `[ENV OK]` container verification in `scripts/run_swebench_hybrid.py` | Non-conda SWE-bench images (non-Python repos) would need language-specific activation |
| `docker cp` failed on Windows NTFS without symlink privilege (`WinError 1314`) on Django docs symlinks, and naive `lstrip("./")` stripped `.git` to `git/` | Proven cause (observed in `django__django-16527` extraction & diff inspection) | Fixed via streaming `tarfile` extraction with prefix stripping (`./`), `core.symlinks=false` link stubs, and explicit `.git` existence assertion | Verified on Django, Pytest, and Requests images |
| Local `qwen3.5:2b-q4_K_M` replaced `self.records = []` with a blank line on `pytest-dev__pytest-10051` while `dispatch_worker` did not include a computed unified diff | Proven observation | [pytest-dev__pytest-10051.diff](../reports/experiment23/patches/pytest-dev__pytest-10051.diff) | Returning computed unified diff from `dispatch_worker` is deferred to a follow-up PR |
| Groq free-tier daily TPD (`200,000`) exhausted during Task 3 (`198,265 / 200,000`) | External quota boundary | Logged HTTP `429` on Turn 2 of `psf__requests-1724` | Larger slices require higher-quota endpoints via `EndpointConfig` swap |

## E. What Changed

| File / symbol | Before behavior | Implementation change | After behavior | Evidence / test |
|---|---|---|---|---|
| [scripts/run_swebench_hybrid.py](../scripts/run_swebench_hybrid.py) | Absent | Added official `SWE-bench Verified` runner with HF Datasets Server fetching, streaming Windows-safe `.git`/symlink extraction, `/opt/miniconda3` check, sandboxed `run_repo_tests` tool, fresh-container baseline + candidate Docker oracle evaluation, and 1-image-at-a-time cleanup | Reproducible, zero-leakage SWE-bench Docker evaluation | Live 3-task run (Section G) |
| [reports/experiment23/PROTOCOL.md](../reports/experiment23/PROTOCOL.md) | Absent | Added Experiment 23 protocol documenting system delta since Experiment 22, fixed `seed=42` inputs, procedure, and acceptance criteria | Matches `reports/experiment22/PROTOCOL.md` schema | Direct review |
| [reports/experiment23/experiment23-report.md](../reports/experiment23/experiment23-report.md) | Absent | Added concise Experiment 23 report with architecture delta summary, GTX 1650 VRAM measurements, 3-task Docker oracle outcomes, diagnostic catches, and limitations | Transparent, reproducible small-sample ($N=3$) benchmark record | [experiment23-results.json](../reports/experiment23/experiment23-results.json) |
| [reports/experiment23/experiment23-results.json](../reports/experiment23/experiment23-results.json) & [experiment23-provenance.json](../reports/experiment23/experiment23-provenance.json) | Absent | Added sanitized machine-readable verdicts, token/latency metrics, offline regression gate counts, and LF-normalized SHA-256 provenance | Matches Experiment 22 JSON schema with zero secrets or personal paths | JSON validity verified |
| [reports/experiment23/patches/](../reports/experiment23/patches/) | Absent | Added curated candidate diffs (`django__django-16527.diff`, `pytest-dev__pytest-10051.diff`) | Directly inspectable ground-truth artifacts | Verified against official Docker oracles |
| [reports/INDEX.md](../reports/INDEX.md) | Ended at Experiment 22 | Appended Experiment 23 row linking report, JSON, protocol, provenance, runner, and patches | Keeps master index synchronized | Direct review |

## F. How the Fix Works

For each selected `SWE-bench Verified` instance, `scripts/run_swebench_hybrid.py`:
1. Pulls the single official image (`swebench/sweb.eval.x86_64.<owner>_1776_<repo>-<id>:latest`) and asserts `/opt/miniconda3` `testbed` activation before spending LLM tokens.
2. Streams `/testbed` into a disposable workspace via `docker cp ... -` + `tarfile` preserving `.git` and converting POSIX symlinks into Git-compatible `core.symlinks=false` text stubs, setting `core.filemode=false` and `core.autocrlf=false`.
3. Runs `HybridAgentRunner` exposing only `problem_statement`, workspace files, read-only `git`, and a sandboxed `run_repo_tests` tool (which syncs only the agent's current `git diff` into an isolated container without ever applying hidden `test_patch`).
4. Runs **two fresh Docker oracle containers**: a Baseline check (`test_patch` only) to verify non-tautological failure, followed by a Candidate check (`model_patch` + `test_patch`) parsing exact `FAIL_TO_PASS` and `PASS_TO_PASS` outcomes, then immediately deletes the task image (`docker rmi -f`).

## G. Functional Verification

| Scenario / test | Verification class | Scripted/mocked boundaries versus real components | Expected behavior and oracle | Actual observed artifact/state | Result | Evidence |
|---|---|---|---|---|---|---|
| `django__django-16527` (`django/django`, `15m–1h`) | Live-model E2E (official Docker oracle) | **Zero mocks:** real Groq `qwen/qwen3.8-27b`, real local Ollama `qwen3.5:2b-q4_K_M`, real Django repo, real official Linux Docker container (`runtests.py`) | Baseline `F2P=0/1, P2P=6/6`; candidate `model_patch` applies cleanly and achieves `F2P=1/1, P2P=6/6` | Baseline `F2P=0/1, P2P=6/6`; candidate `patch_applied=True`, **`F2P=1/1`, `P2P=6/6` (`resolved=True`)**, `549`-byte patch written in 1 worker dispatch (`3` turns, `0` rollbacks) | Pass | [experiment23-results.json](../reports/experiment23/experiment23-results.json), [django__django-16527.diff](../reports/experiment23/patches/django__django-16527.diff) |
| `pytest-dev__pytest-10051` (`pytest-dev/pytest`, `15m–1h`) | Live-model E2E (official Docker oracle) | **Zero mocks:** real Groq `qwen/qwen3.8-27b`, real local Ollama `qwen3.5:2b-q4_K_M`, real Pytest repo, real official Docker container (`pytest -rA`) | Baseline `F2P=0/1, P2P=15/15`; candidate resolves `F2P=1/1, P2P=15/15` | Baseline `F2P=0/1, P2P=15/15`; candidate `patch_applied=True`, `F2P=0/1`, `P2P=9/15` (`resolved=False`); 2B worker blanked line 345 instead of inserting `self.records.clear()` | Fail (recorded honestly) | [experiment23-results.json](../reports/experiment23/experiment23-results.json), [pytest-dev__pytest-10051.diff](../reports/experiment23/patches/pytest-dev__pytest-10051.diff) |
| `psf__requests-1724` (`psf/requests`, `<15m`) | Live-model E2E (official Docker oracle) | **Zero mocks** | Complete solve & Docker oracle eval | Blocked on Turn 2 by Groq daily TPD (`198,265/200,000`); `patch_bytes=0`; baseline showed `F2P=6/6, P2P=77/79` | Blocked / Fail | [experiment23-results.json](../reports/experiment23/experiment23-results.json) |

- **Live-model completion:** **Verified with fresh approved live official Docker runs ($N=3$, `seed=42`)**: **`1/3` resolved overall (`1/2` on non-quota-blocked tasks with valid failing baselines)**.

## H. Additional Successful Tests

| Suite / verification class | Fresh or historical; source revision | Exact command | Tests run | Passed | Failed / errors | Skipped | Exit / result | Relevance | Evidence |
|---|---|---|---:|---:|---|---:|---|---|---|
| Provider & hybrid suite | Fresh (2026-11-26); `886ea71` | `python -m unittest tests/test_providers.py tests/test_hybrid_runner.py -v` | 16 | 16 | 0 / 0 | 0 | Exit 0 (`0.410s`) | Confirms hybrid runner stability before Experiment 23 | [experiment23-results.json](../reports/experiment23/experiment23-results.json) |
| Tools regression | Fresh (2026-11-26); `886ea71` | `python -m unittest discover -s tests -p "test_tools_*.py"` | 37 | 35 | 0 / 0 | 2 | Exit 0 (`2.963s`) | Confirms zero regressions in `hivo/tools/` | [experiment23-results.json](../reports/experiment23/experiment23-results.json) |
| Core offline regressions | Fresh (2026-11-26); `886ea71` | `test_verification_outcome_integrity.py` & `test_execution_contracts.py` | 31 & 36 | 31 & 36 | 0 / 0 | 0 | Exit 0 | Confirms zero collateral impact on legacy modules | [experiment23-results.json](../reports/experiment23/experiment23-results.json) |

## I. Regression and Compatibility Impact

- **Potentially affected functionality/dependencies:** None — adds `scripts/run_swebench_hybrid.py`, `reports/experiment23/`, `updates/R_UPDATE_012.md`, and one row in `reports/INDEX.md`.
- **Preserved behavior:** All historical reports (Experiments 1–22) and `mini.py` remain untouched.

## J. Overall Impact

Establishes the repository's first reproducible, official Docker-verified `SWE-bench Verified` baseline for the hybrid cloud-orchestrator + 4 GB local-worker architecture (`1/3` resolved overall, `1/2` non-quota-blocked with valid baselines, proving that a 1.6 GB 2B local model on a 4 GB GTX 1650 can write and pass a real Django bugfix patch under cloud thinking orchestration), while documenting exact failure mechanics and quota bottlenecks for subsequent optimization.

## K. Remaining Limitations

- Small sample size ($N=3$, `seed=42`) constrained by Groq free-tier daily quota (`200K` TPD).
- `pytest-dev__pytest-10051` exposed 2B edit fragility without immediate diff visibility in `dispatch_worker`.
- `psf__requests-1724` was quota-blocked and exhibited a non-standard `F2P=6/6` pre-patch baseline.

## L. Evidence and Reproduction

| Relative evidence link | Fresh / historical / sanitized derivative | Source/run identity | What it proves | What it does not prove |
|---|---|---|---|---|
| [reports/experiment23/experiment23-report.md](../reports/experiment23/experiment23-report.md) | Fresh curated report | `feat/experiment23-hybrid-swebench` (2026-11-26) | Full architecture delta since Experiment 22 and honest $N=3$ verdicts | Large-scale solve rate |
| [reports/experiment23/experiment23-results.json](../reports/experiment23/experiment23-results.json) | Fresh sanitized JSON | `feat/experiment23-hybrid-swebench` (2026-11-26) | Exact baseline/candidate Docker oracle counts, token usage, and VRAM telemetry | Unverified non-Groq endpoints |
| [reports/experiment23/patches/django__django-16527.diff](../reports/experiment23/patches/django__django-16527.diff) | Fresh curated patch | `django__django-16527` live run | Exact 1-line patch written by `qwen3.5:2b-q4_K_M` that passed `F2P=1/1, P2P=6/6` | Universal multi-file patching reliability |

```powershell
# Reproduce Experiment 23 slice (requires Docker Desktop, Ollama qwen3.5:2b-q4_K_M, and cloud API key in .env)
python -u scripts/run_swebench_hybrid.py --provider groq --worker-model qwen3.5:2b-q4_K_M --instances pytest-dev__pytest-10051 django__django-16527 psf__requests-1724 --max-orch-turns 14 --max-worker-turns 5 --max-elapsed-sec 480
```

- **Original preservation:** Raw Docker evaluation logs, full workspace traces, and aborted diagnostic runs remain preserved locally under gitignored `output/swebench_hybrid/`.
- **Sanitization:** No API keys, Groq organization IDs, or personal absolute paths appear in published files.

## M. Summary for the Team

**Proposed PR title:** `docs(experiment23): add SWE-bench Verified Docker harness and hybrid cloud+local evaluation report`

**Why needed:** Establish an independent, official Docker-verified `SWE-bench Verified` checkpoint (Experiment 23) for the new asymmetric hybrid architecture (`hivo/tools/` + `hivo/providers/` + `hivo/hybrid/`), summarizing every architectural shift since Experiment 22.

**What changed / what was fixed:**
- Added reusable zero-leakage official `SWE-bench Verified` Docker runner (`scripts/run_swebench_hybrid.py`) with Windows symlink-safe `.git`-preserving `tarfile` extraction, universal `/opt/miniconda3` detection, sandboxed `run_repo_tests`, independent baseline + candidate Docker oracle checks, and 1-image-at-a-time cleanup.
- Added Experiment 23 documentation matching the Experiment 22 schema: `reports/experiment23/PROTOCOL.md`, `experiment23-report.md`, `experiment23-results.json`, `experiment23-provenance.json`, curated candidate diffs (`patches/`), `reports/INDEX.md` entry, and `updates/R_UPDATE_012.md`.

**Functional verification:**
- Official `SWE-bench Verified` Docker evaluation (`seed=42`, $N=3$, Groq `qwen/qwen3.8-27b` + local `qwen3.5:2b-q4_K_M` on GTX 1650 4 GB VRAM): **`1/3` resolved overall (`1/2` on non-quota-blocked tasks with valid baselines)** — **`django__django-16527` RESOLVED (`F2P=1/1, P2P=6/6`)**, `pytest-dev__pytest-10051` NOT RESOLVED (`F2P=0/1, P2P=9/15`), `psf__requests-1724` quota-blocked on Turn 2 (`198,265/200,000` TPD).

**Additional successful tests:** Offline regression gate on parent `886ea71` passed (`16/16` hybrid/provider, `37` tools w/ 2 Windows symlink skips, `31/31` verification integrity, `36/36` execution contracts).

**Remaining issues:** Small sample ($N=3$), Groq free-tier 200K TPD ceiling, and lack of automatic unified diff return in `dispatch_worker` (exposed by `pytest-dev__pytest-10051`).

**Publication state:** Committed on `feat/experiment23-hybrid-swebench` (stacked on `feat/hybrid-providers`), pushed to `origin` (`kareem232003/mini_hivo`), and opened as an upstream PR against `abdoabozena7/mini_hivo:main` per explicit user authorization.
