# Host preflight memory diagnosis — provisional investigation

## A. Identification

- Date: 2026-11-21, Africa/Cairo. Status: diagnosis established for the observed failures; reliable live startup remains unverified. This is not a completed numbered engineering update.
- Branch: `rodina/dev-turn-2026-11-20`; HEAD/base: `ef08b09708a295d5765d4c207141aa8a11d85f72`.
- Scope: existing startup records, read-only Windows/Ollama observations, five selected offline controls and a fake-canary replay. No new inference, production correction, threshold change or M1 work.
- The existing uncommitted M0 change in `mini.py` predates this investigation. Tested source hashes are in the [measurement derivative](../evidence/host-preflight-memory-20261121/measurements.json). Containing commit/PR: none; local uncommitted documentation.

## B. Original problem

The user requested diagnosis of `CRITICAL_MEMORY_HEADROOM` before starting M1. A successful direct Ollama response establishes that the model can answer; it does not establish that enough physical RAM remains to operate Mini Hivo safely.

| Historical record | Available physical RAM | Earliest stopping boundary | Completed canaries |
|---|---:|---|---:|
| `d0d149c666f849f7a2262abe79cf77c3`, 01:09:33 UTC | 444,014,592 bytes = 423.45 MiB | `static_resources` | 0/3 |
| `a0d453fbbb8d423f9dd9ae7118b6d970`, 01:10:33–01:10:49 UTC | 7,626,084,352 bytes = 7.102 GiB before; 435,351,552 bytes = 415.18 MiB after call 1 | `resource_monitoring` | 1/3 |

The second attempt lost approximately 6.697 GiB of available RAM over 15.7 seconds. Original marker files were read and copied into a fresh private evidence directory; no actual failing startup was rerun. An earlier project-1 marker reports `OLLAMA_UNAVAILABLE`; it is a separate failure, not the cause of these two memory stops.

## C. Why diagnosis was necessary

Repeated unload/reload attempts can repeat the same pressure without fixing it. The startup gate must distinguish host qualification from successful text generation. The immediate objective is safe startup, not a forced PASS.

## D. Root cause and exact execution path

1. `mini.py::main` (line 30164) parses arguments, checks dependencies, validates the model and selects a workspace. Line 30194 calls `run_host_preflight`; a failed result prints `terminal: HOST_PREFLIGHT_FAILED` and exits 2 before task creation or the interactive request loop. `--no-bootstrap` disables automatic dependency installation, not preflight.
2. `hivo/host_preflight.py::run_host_preflight` (line 450) samples `before_canary` through `sample_resources` / `_safe_resource_snapshot`. `_resource_blocker` (line 432) rejects available physical RAM **strictly below 536,870,912 bytes (512 MiB)**. Attempt 1 stops here, before canaries.
3. After endpoint/catalogue validation, the controller executes three synchronous, sequential canaries via `_default_canary_call` (line 366). For `gemma4:e4b`, each `/api/chat` request has one short message, `stream=false`, temperature 0, seed 0, `num_ctx=512`, and `num_predict=32`. It does not accumulate conversation history or request separate instances. Timeout is 180 seconds per call; cooldown is 2 seconds between successful calls and before the final sample.
4. Each response is validated before an `after_call_N` resource sample. The first response in attempt 2 succeeded, but its post-call memory sample failed. Calls 2 and 3 were never made. These observations do not show pressure from three accumulated calls.
5. Windows measurement is `GlobalMemoryStatusEx`, `MEMORYSTATUSEX.ullAvailPhys`, implemented in `_memory_snapshot` (line 68). The field and threshold use bytes; the structure uses 64-bit memory fields. Microsoft defines this available value as reusable physical memory including standby, free and zero lists. It is not a measurement of only completely unused RAM. [Microsoft field definitions](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/ns-sysinfoapi-memorystatusex).

The source comment calls the constants conservative safety limits, not a hardware compatibility claim. No measured/model-specific rationale for precisely 512 MiB was found in the inspected source/history. This floor is only about 3.2% of the measured 15.69 GiB physical RAM; the evidence does not justify calling it overly conservative or lowering it.

### Fresh read-only corroboration

| Observation, Cairo time | Physical RAM available | Windows committed memory | Ollama state |
|---|---:|---:|---|
| 03:14:03 | 444 MiB | 97% of ~23.0 GiB commit limit | One model, one runner |
| 03:14:57 | 399 MiB | 97% | Same resident model/runner |
| 03:16:23 | 7,096 MiB = 6.93 GiB | 66% | Empty `/api/ps`; zero runners |

The model's recorded expiry was 03:15:49. It unloaded naturally between observations; this investigation did not stop, load or refresh it with inference. The rebound of about 6.54 GiB between the latter samples strongly corroborates model residency as the dominant pressure. These samples do not assign every byte of system-wide change exclusively to Ollama.

Close-in-time Mini Hivo API and Windows CIM measurements were approximately 435–452 MiB available, all below the same floor. Thus there is no demonstrated unit, struct or free-versus-available monitoring defect explaining the failure. Commit pressure and paging activity independently corroborate scarcity. This is a real safety stop under the implemented policy, not proof that an out-of-memory crash had already occurred.

### Model residency and instance accounting

- `/api/ps` reported exactly one `gemma4:e4b`, `size_vram=0`, runner `llamacpp`; observed runner arguments included `-np 1`. An Ollama desktop app, server daemon and one model runner are distinct processes, not three model instances.
- Runner working set at 03:14:03 was 7,268,192,256 bytes (~6.77 GiB); private committed allocation was 8,261,312,512 bytes (~7.69 GiB). Private bytes are not an additional physical allocation to add to working set. The GUI app used about 0.85 GiB working set. Other desktop/browser applications also consumed RAM; process working sets cannot be summed as unique guaranteed savings because shared pages overlap.
- Local model manifest layers total about 6.13 GiB: main weights ~5.116 GiB, projector ~0.923 GiB and draft ~0.092 GiB. Runner arguments referenced all three. Runtime buffers/cache add costs; disk sizes are not exact resident allocations. `/api/ps.size` (~1.79 GiB) is not the observed total process footprint and does not override OS counters.
- Requested canary context was 512, but the observed loaded runner had context 2048. This discrepancy is retained as a limitation: current logs do not establish why that runner used 2048. It is not sufficient evidence of a Mini Hivo defect. Current server/app logs were empty; older rotated logs were not treated as records of this load.
- Preflight has no explicit model-residency inventory or load-budget prediction. Its global physical-RAM reading includes resident model costs implicitly; subtracting those costs again would be wrong. It samples between calls, not continuously during loading, so the transient peak is unknown.
- No explicit preflight `keep_alive` is sent; Ollama documents default five-minute residency. Normal Mini Hivo `ask_ollama` uses `keep_alive="10m"` and role contexts up to 12,288. A startup pass with the tiny canary would not prove safe headroom for those larger tasks. [Ollama FAQ](https://docs.ollama.com/faq).

## E. What changed

Only this provisional note, a sanitized measurement derivative, and fresh ignored diagnostic outputs were added. Production code, tests, thresholds, model configuration, prior startup evidence, M0 and R_UPDATE_004 were left unchanged. No dependencies were installed.

## F. Correction decision and safe pressure reduction

**No production fix is justified by the observed evidence.** The exact earliest boundary is genuine insufficient available physical RAM, initially or after the first successful model load/canary. A hypothetical diagnostic enhancement could report commit pressure, residency and runner footprint alongside before/after RAM, but that requires separate implementation approval and is not a fix claimed here.

Safe actions for the user:

1. Save work and close unused browser windows and other memory-heavy desktop applications. Recheck after loading, not merely while the model is absent: 7.10 GiB of cold headroom already proved insufficient on this run.
2. Keep one Ollama server, one active client and no simultaneous `ollama run` while Mini Hivo starts. The observed runner already has one parallel slot, so reducing parallelism is not an established remedy here.
3. If desired, gracefully quit the Ollama tray app and then use one foreground `ollama serve` terminal. Do not start a second server while the current one owns port 11434. Removing the GUI may recover some memory but is not a guaranteed solution.
4. `ollama stop gemma4:e4b` can unload an idle model; reloading needs the memory again. Unloading and repeatedly retrying is not a durable solution. Ollama documents the manual stop operation and model residency in its [FAQ](https://docs.ollama.com/faq).
5. The pagefile was already automatically managed (~7,496 MiB allocated), with ~32.6 GiB free on the system drive. Preserve automatic management. More swap does not replace the physical-RAM headroom check.
6. If ordinary application closure cannot provide stable loaded headroom, stop startup attempts and review additional physical RAM or a separately approved model/profile choice. Keep the safety limits unchanged. Neither a specific RAM upgrade target nor a reliable minimum cold free-RAM number was established by these samples.

## G. Functional verification boundary

No new live-model end-to-end run was performed; safe live startup remains unverified. Real read-only Windows/Ollama observations establish host pressure and natural recovery. A controlled replay injected the original second-attempt snapshots and a fake successful response into the real preflight controller: it produced the same reason/stage, completed exactly one fake canary and made no second call. All four assertions passed. This proves the deterministic gate response to those inputs, not independent live-model reliability or measurement accuracy by itself.

## H. Additional offline checks

Command actually executed from the repository root:

```powershell
.\.venv\Scripts\python.exe -B -X utf8 output/host-preflight-memory/20261121-inspection-001/offline_checks.py
```

Five selected existing unit/integration controls passed, zero failures/errors/skips, exit 0: three sequential successes; exact tiny payload; pre-canary memory rejection; unknown GPU warning; and main stopping before task creation after preflight failure. Provider/model calls were mocked or forbidden. The printed `OLLAMA_UNAVAILABLE` in the mocked-main test is synthetic, not another real startup attempt. Do not sum the replay assertions as additional tests. The harness creates outputs exclusively; reusing the same directory is intentionally refused. Logs/results and source hashes are retained privately, with results copied into the sanitized derivative.

## I. Regression and compatibility

No runtime implementation change; broad regression not run. The five controls cover the relevant existing gate behavior only. Unknown GPU telemetry was a warning, not the failure. No claim is made that other M0 findings or full agent execution are resolved. No external service or Git remote was modified.

## J. Impact

The diagnosis explains why a successful direct model response and sufficient cold RAM do not guarantee safe Mini Hivo startup. It avoids weakening a working safety boundary. It does not claim a repaired environment or a completed application task.

## K. Remaining limitations

- No continuous per-process telemetry during the original load, current load logs or exact transient peak; attribution is strongly corroborated, not byte-for-byte allocation accounting.
- 512 requested versus 2048 effective context remains unexplained. Allocation by projector, draft model, cache and other buffers is not independently isolated.
- Larger role contexts and full live task memory are unverified. No repeated expensive inference, benchmark or fresh startup was authorized or run.
- This environment currently has a CPU-resident model footprint and competing applications. Reliable startup after reducing pressure still needs one deliberate user-operated attempt.

## L. Evidence, integrity and manual startup

- [Sanitized measurements and original-byte SHA-256 values](../evidence/host-preflight-memory-20261121/measurements.json).
- Private originals/copies and diagnostics: `output/host-preflight-memory/20261121-inspection-001/`, ignored from Git. Original startup markers remain in their existing project folders. No user workspace contents or private process command lines were copied into the derivative.
- The derivative contains selected memory/model facts and test results; it is not byte-identical to raw originals. Raw source hashes refer to original bytes. No staged Git-blob hash claim is made: nothing was staged or published.
- Integrity check compares captured hashes of `mini.py`, `hivo/host_preflight.py`, M0 notes and R_UPDATE_004, plus original/copy startup-marker hashes. Documentation checks verify local links and A–M sections.

The isolated checkout environment was observed as Python 3.14.8 with Rich 14.3.4, prompt_toolkit 3.0.53 and Playwright 1.65.2 installed. No reinstall is required for those dependencies; installed package metadata alone does not certify a browser runtime.

After saving work and reducing pressure, the user can run these from PowerShell (not executed by this investigation):

```powershell
# From the project root. Read-only endpoint/model checks; no model loading.
$env:OLLAMA_BASE_URL = 'http://127.0.0.1:11434'
Invoke-RestMethod "$env:OLLAMA_BASE_URL/api/version"
ollama list
ollama ps
.\.venv\Scripts\python.exe -B -X utf8 -c "from hivo.host_preflight import _memory_snapshot; s=_memory_snapshot(); print('Available GiB:', round(s['available_system_ram_bytes']/2**30, 2))"

# This next step DOES run up to three real canaries. Run only when ready.
# Use a fresh folder so previous startup markers are preserved.
$runWorkspace = Join-Path $env:TEMP ('MiniHivo-local-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $runWorkspace | Out-Null
.\.venv\Scripts\python.exe -B -X utf8 .\mini.py --no-bootstrap --model gemma4:e4b --workspace $runWorkspace
```

If the version endpoint is unavailable, start `ollama serve` in a separate terminal only after confirming another Ollama server is not running. No need for a preliminary `ollama run`. Successful preflight should print PASS and reach `You>`. Type `exit`/`quit` at that prompt to exit. During an ongoing operation, Ctrl+C interrupts it; preserve resulting markers. A failure prints `HOST_PREFLIGHT_FAILED`, exits 2 and saves `$runWorkspace\.agent_host_preflight.json`; stop and inspect rather than repeatedly retrying. Temporary-folder artifacts may be cleaned by Windows later; retain desired evidence in a durable location yourself. Generated task files use the explicitly selected workspace.

The manual memory read is not a pass/fail guarantee: headroom must survive loading, and 512 MiB is only the stop floor. Dependency/setup errors and endpoint/model failures are startup issues; neither is proof of a child/parent agent defect. Agent investigation resumes only after host qualification and user confirmation of working startup.

## M. Team summary

Proposed future documentation-only title: **Document real Windows memory pressure during Ollama preflight**. No PR is created or requested here. The current gate correctly stops on observed sub-512-MiB headroom; one loaded runner and natural unloading/recovery support genuine resource pressure. Five offline controls and the fake historical replay passed. No live startup success, production fix or M1 completion is claimed. All additions remain local and uncommitted; no commit, push, merge, reset, deletion or remote modification was performed.
