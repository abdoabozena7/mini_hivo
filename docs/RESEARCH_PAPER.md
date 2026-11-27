# Certify Before You Compose: Assume-Guarantee Interface Certificates, Dual-Boundary Hardware-Aware Decoding, and Visual-Execution Oracles for Local Weak-Model Software Swarms

> [!WARNING]
> **HISTORICAL ARCHIVE — RETIRED v1 (DO NOT USE):** Mini Hivo is **v2 only**. This paper documents the retired **v1 single-local-model system** (`mini.py` / `gemma4:e4b`), preserved strictly as historical record. Active Mini Hivo development is exclusively **v2** — see [`../README.md`](../README.md), [`PROJECT_STATUS.md`](PROJECT_STATUS.md), [`ORCHESTRATION_ARCHITECTURE.md`](ORCHESTRATION_ARCHITECTURE.md), and [`BENCHMARKING_ARCHITECTURE.md`](BENCHMARKING_ARCHITECTURE.md).

**System Under Study:** Mini Hivo — Architecture-First Local Weak-Model Swarm & Recursive Coding Engine (`mini.py` final regression-verified `source_sha256: 03ebfa8af7cd1ff01e0ab70ef9b476c7a1f5ff83eac380d30a6e423d8cd62b61`; live `threejs v8` trial `source_sha256: 3bf32fbdab883b9f17ab1baaf73abe28d02383e335ae15a8b18acc89e0a97492`)
**Primary Pinned Subject Model:** `gemma4:e4b` (Q4_K_M quantized 4B local open-weight model via Ollama under `SingleModelPolicy`, zero frontier/cloud fallback; comparative protocol probe on `qwen2.5-coder:3b`)
**Companion Architectural Records:** [Graduation North Star](PROJECT_GOAL.md) · [14-Role Swarm Charter](AGENT_ARCHITECTURE.md) · [Before You Split Formulation](RESEARCH_DIRECTION.md) · [Baseline Checkpoint (`R_UPDATE_008`)](../updates/R_UPDATE_008.md)

---

## Abstract

Small quantized open-weight language models (`3B–4B` parameters running locally on `6 GB` consumer laptop GPUs) offer strict data sovereignty and zero marginal API cost, yet systematically collapse on multi-file and interactive software engineering tasks. Counterintuitively, wrapping weak local models in conventional multi-agent loops frequently *degrades* end-to-end completion relative to single-agent baselines due to inter-agent specification drift, sibling file trampling, and compounding error cascades [1, 2]. We show that weak-model software swarms fail at **five coupled boundaries** that prior literature treated in isolation: *(i)* compositional ownership and interface verification [3, 4], *(ii)* bounded context projection under tool-call truncation [7], *(iii)* operating-system/GPU KV-cache residency cliffs, *(iv)* role- and epoch-conditioned token sampling [9, 10, 11, 12], and *(v)* perceptual/DOM execution workmanship [15, 16].

We introduce **AGISS (Assume-Guarantee Interface-Certified Swarm Synthesis)**, a zero-cloud-fallback controller architecture implemented inside Mini Hivo. First, AGISS enforces clause-scoped disjoint child file ownership ($O_i \cap O_j = \emptyset$) across a three-tier producer-to-consumer topological partial order and extracts deterministic $O(|f|)$ **Assume-Guarantee Interface Certificates** $\mathcal{C}(f) = (G_f, A_f)$ with zero model calls across Python AST, HTML, ES-module JavaScript, and CSS surfaces (`hivo/assume_guarantee.py`). Second, AGISS pairs **Anchor-Pinned Tool-First Context Compaction** (`hivo/context.py`) — provably eliminating *Specification Amnesia* after truncated tool calls — with a **Dual-Boundary Hardware-Context Law** and **Role-Conditioned `min_p` Decoding Schedule** (`hivo/hyperparams.py`) calibrated to an empirically measured **24.5x WDDM GPU KV-cache throughput cliff** (`98.5 tok/s -> 4.0 tok/s`). Third, AGISS replaces prose self-certification with headless Chromium WebGL perceptual and layout oracles (`blank_initial_canvas` pre-start inner-playfield luminance $\sigma_Y \ge 0.75$ and `hud_layout_overlap` pairwise DOM bounding-box intersection). Evaluated live on a single consumer laptop GPU (`NVIDIA GeForce RTX 3060 Laptop GPU`, `6 GB` VRAM) with all 17 controller roles pinned to `gemma4:e4b`, AGISS lifts 3-file recursive Python package synthesis from **`0/5` (`0%`)** in `R_UPDATE_008` to **`2/2` consecutive verified `4/4`-node passes** (`198.46s` and task-agnostic `211.89s`, `repairer_calls = 0`), while accelerating human-ready 3D Three.js WebGL game synthesis by **`35.3%`** (`284.67s -> 184.04s`), reducing model calls by **`42.9%`** (`14 -> 8`) and output tokens by **`44.7%`** (`13,687 -> 7,574`), and eliminating both blank initial canvases (`initialFrameBlank: True -> False`, $\sigma_Y = 40.189$) and HUD corner collisions (`hudOverlapCount = 0`).

---

## 1. Introduction & Motivation: The Capability-Coordination Paradox on Consumer Hardware

Deploying autonomous software engineering agents on commodity personal hardware (`4B` quantized models within `6 GB` laptop VRAM and `15–16 GB` system RAM) exposes a sharp **Capability-Coordination Paradox**. A single-shot weak model lacks the effective working memory to hold a multi-module specification, repository state, tool schemas, and runtime diagnostics simultaneously; yet decomposing tasks across multiple weak agents without formal compositional invariants amplifies failure rates. Empirical studies of multi-agent LLM systems demonstrate that unconstrained conversational swarms suffer from 14 recurring failure modes spanning specification loss, inter-agent misalignment, and premature verification [1], and across 180 agent configurations, unvalidated multi-agent topologies amplify single-step error probabilities super-linearly compared to centralized verification architectures [2].

Equally damaging is **Oracle Illusion** at the verification boundary. LLM-as-a-Judge reviewers, unit tests synthesized by the same model without external grounding, and process-exit-zero checks routinely certify broken artifacts as `PASS`:
1. **Perceptual Blankness Under Clean Console State:** In `R_UPDATE_008` (`run_id: 20261122T035103-a23aed75`), `gemma4:e4b` produced a syntactically valid `17,568`-byte Three.js r160 game (`"Neon Starfighter 3D"`) that passed WebGL context creation and five programmatic `window.AGENT_GAME` transitions, yet deferred `renderer.render(scene, camera)` until after `start()`. To a human opening the page, the viewport displayed a solid `#050816` blank rectangle behind a `PAUSED` badge ($\sigma_Y = 0.0$).
2. **Spatial HUD Collision Under Valid DOM Structure:** Weak models instructed to build rich sci-fi HUDs place five or more independent `position: absolute` panels into four viewport corners, causing severe text/button occlusion (`#score-display` overlapping `#crystals-display`, or `#hud-crystals` occluding `#start-button`) while every DOM query selector succeeds.
3. **Cross-Sibling Scope Trampling & Interface Hallucination:** In `R_UPDATE_008`'s five live multi-file recursive Python runs (`20261122T041420-a8b08862` through `20261122T045001-11fb390d`), `0/5` reached `[ROOT VERIFIED] PASS`. Either Child 1 (`metrics.py`) stole ownership of `test_metrics.py` because root creation targets were broadcast across children, or Child 2 (`cli.py`) repeatedly attempted unauthorized edits on Child 1's committed files (`WORKER_NO_MUTATION_PROGRESS`), or modular Three.js children hallucinated non-existent relative imports (`./Starfield.js`), core symbols under addon paths (`three/addons/helpers/GridHelper.js`), and mismatched DOM IDs (`#score` vs. `#hud-score`).

### The Five Coupled Failure Boundaries

Our central thesis is that reliable local weak-model software synthesis cannot be achieved by tuning prompts or scaling agent count alone because failures propagate across **five tightly coupled systems boundaries**:

```text
+-----------------------------------------------------------------------------------+
|                        USER SPECIFICATION (Immutable REQ-* Ledger)                |
+-----------------------------------------+-----------------------------------------+
                                          |
  [Boundary 1: Compositional Contracts]   v   (hivo/assume_guarantee.py)
  Disjoint Ownership (O_i cap O_j = empty) + Zero-Model Certificates C(f) = (G_f, A_f)
                                          |
  [Boundary 2: Context Projection]        v   (hivo/context.py, evidence_licensed_gate)
  Anchor-Pinned Tool-First Compaction (protected_anchor = 1) + Before-You-Split Gate
                                          |
  [Boundary 3: OS/GPU KV Residency]       v   (mini.py::ask_ollama, /api/ps eviction)
  Dual-Boundary Law (L_in + L_out <= N_ctx) below WDDM 6GB VRAM Cliff (N_ctx <= 10240)
                                          |
  [Boundary 4: Token Sampling Dynamics]   v   (hivo/hyperparams.py)
  Analytical (T=0.05) vs Cold Epoch-0 Synthesis (T=0.08, min_p=0.08) vs Escape (+7919)
                                          |
  [Boundary 5: Perceptual/DOM Oracles]    v   (hivo/quality_rubric.py, verification.py)
  Pre-Start Luminance (sigma_Y >= 0.75) + Pairwise HUD Anti-Overlap + Subprocess/WebGL
+-----------------------------------------------------------------------------------+
```

Violating any single boundary cascades into the others. For example, setting `Builder` Epoch-0 temperature too warm ($T_0 = 0.15$ in `threejs v6`) inflates draft length to `23.8 KB` (`34,656` output tokens); oversized `write_file` tool calls hit completion-token truncation (`Boundary 4 -> Boundary 3`), which triggers context compaction that—if unanchored—erases the root specification at `projected[1]` (`Boundary 2`), causing the model to overwrite the application with a `"Welcome!"` stub that fails browser verification (`Boundary 5`). AGISS resolves this cascade holistically without ever falling back to an external frontier model.

### Summary of Contributions

1. **Zero-Model Assume-Guarantee Swarm Synthesis (`§3.1–§3.2`):** We formalize clause-scoped disjoint child ownership partitioning, three-tier producer-to-consumer scheduling, and linear-time static certificate extraction/verification (`hivo/assume_guarantee.py`), converting cross-file integration failures into deterministic one-line Agent-Computer Interface (ACI) counterexamples before consumer execution, at write time, and at parent preflight.
2. **Anchor-Pinned Context Compaction (`§3.3`):** We identify *Truncated-Tool-Call Specification Amnesia* in live `4B`-model traces and prove an anchor-preservation invariant (`hivo/context.py`) that prioritizes transient tool-argument eviction over root user intent.
3. **Dual-Boundary WDDM VRAM-Cliff & Role-Conditioned `min_p` Laws (`§4`):** We characterize an exact `24.5x` GPU-to-CPU throughput collapse on `6 GB` WDDM hardware (`Table 1`), derive a dual-boundary `num_ctx` controller with pre-run peer VRAM eviction, and validate a Cold-Synthesis / Warm-Escape `min_p` schedule (`Table 2`) that cuts Three.js output tokens by `78.1%`.
4. **Perceptual & Geometric Browser Workmanship Oracles (`§5`):** We introduce pre-start inner-playfield luminance standard deviation ($\sigma_Y$) and DOM bounding-box anti-overlap checks, uncovering the weak-model *early-return-before-render* anti-pattern and the *5-into-4 Corner Pigeonhole Collision*.
5. **Authentic Live Weak-Model Evaluation (`§6`):** Every claim is backed by preserved, hash-verified live `gemma4:e4b` and `qwen2.5-coder:3b` telemetry, including full negative/intermediate progressions (`py v1..v9`, `threejs v1..v8`) and deterministic offline regression suites.

---

## 2. Related Work

### 2.1 Multi-Agent Failure Taxonomies & Scaling Laws

Cemri et al. [1] introduce **MAST**, categorizing 14 failure modes across multi-agent LLM traces into system design/specification flaws, inter-agent misalignment (e.g., ignoring sibling state or repeating refuted actions), and incomplete verification. Kim et al. [2] evaluate 180 agent-system configurations in *Towards a Science of Scaling Agent Systems*, demonstrating that independent multi-agent topologies amplify single-agent errors unless governed by centralized validation bottlenecks, and that coordination overhead frequently outweighs parallelism gains on tightly coupled tasks. AGISS operationalizes both findings for `4B` local models: siblings never converse via free-form chat, mutation authority is strictly partitioned, and parent/child transitions pass through zero-model structural and runtime gates.

### 2.2 Formal Compositional Contracts & Agent-Computer Interfaces

In formal methods, de Alfaro and Henzinger's **Interface Automata** [3] capture component compatibility optimistically via input assumptions and output guarantees: two interfaces compose legally iff environment/producer guarantees discharge every consumer assumption without reachable error states. Sun et al. (**Clover** [4]) formulate closed-loop verifiable code generation via consistency checking across code, docstrings, and formal annotations, though relying on heavy theorem-proving or LLM-assisted equivalence checks for single-unit synthesis. Role-structured multi-agent frameworks such as **MetaGPT** [5] (Standardized Operating Procedures) and **ChatDev** [6] (communicative waterfall phases) structure agent workflows through natural-language artifacts, which remain vulnerable to symbol/DOM drift under `4B` models. **SWE-agent** [7] demonstrates that concise, deterministic **Agent-Computer Interfaces (ACIs)**—syntax-gated edits and bounded diagnostics—dramatically outperform raw shell access. **ADaPT** [8] decomposes tasks recursively *as needed* upon execution failure; Mini Hivo's *Before You Split* Evidence-Licensed Gate (`hivo/evidence_licensed_gate.py`) refines as-needed decomposition by requiring one bounded same-authority correction on attributable tool/protocol errors before licensing `TASK_TOO_BROAD` splits.

### 2.3 Adaptive Decoding & Sampling Dynamics

Standard `top_p` (nucleus) sampling degrades at elevated temperatures when flat logit tails admit low-probability noise tokens, whereas greedy/near-zero decoding traps small models in repetitive repair loops. Nguyen et al. [9] (**Min-p Sampling**, ICLR 2025 Oral) truncate tokens below $p_{\min} \cdot p_{\max}$, scaling the truncation threshold dynamically with top-token confidence. For code generation, Zhu et al. (**AdapT** [10]) and Zhang et al. (**EDT** [11]) show that high-confidence syntax tokens benefit from cold temperatures while uncertain branching tokens benefit from warmer exploration. Conversely, Renze and Guven [12] show that across structured reasoning benchmarks, low sampling temperatures preserve analytical reliability and prevent unforced logical drift. AGISS unifies these insights at the *orchestrator role-and-stagnation level* (`hivo/hyperparams.py`), separating cold analytical classification ($T = 0.05$) and cold Epoch-0 code synthesis ($T_0 = 0.08, \text{min\_p} = 0.08$) from stagnation-triggered `min_p` escape with prime-stride seed rotation.

### 2.4 Visual/Frontend Execution Oracles & Iterative Grounding

Iterative self-correction loops such as **Reflexion** [13] and **Self-Debug** [14] rely on external execution signals; without faithful runtime feedback, self-reflection degenerates into confident hallucination. For frontend synthesis, **Design2Code** [15] establishes that evaluating generated web interfaces requires rendered visual fidelity rather than token similarity, while **ArtifactsBench** [16] demonstrates a persistent *visual-interactive gap* in which statically plausible web artifacts fail dynamic layout, state-transition, and perceptual usability checks. AGISS bridges this gap without requiring a costly multimodal frontier VLM judge by embedding sub-second, deterministic Playwright pixel-luminance ($\sigma_Y$), CSS bounding-box overlap, and `window.AGENT_GAME` state-machine oracles directly inside the local verification loop.

---

## 3. Formal Architecture of AGISS (`hivo/assume_guarantee.py`, `hivo/evidence_licensed_gate.py`, `hivo/context.py`)

Let $\mathcal{M}$ denote a single pinned local language model invoked across all roles under `SingleModelPolicy`, and let $\mathcal{W}$ denote a transactional workspace over relative POSIX paths $\mathcal{P}$. When a parent node decomposes a multi-file creation or modification contract into $k$ child specifications $\langle c_1, \dots, c_k \rangle$, AGISS governs decomposition, execution, context projection, and integration through the pipeline below:

```text
Parent Split Proposal <c_1, ..., c_k> + Declared Paths D
   |
   v  [1. partition_disjoint_child_ownership]  (0 LLM calls)
Disjoint Ownership O_1..O_k (O_i cap O_j = empty) + Tier DAG (Tier 0 -> Tier 1 -> Tier 2)
   |
   v  [For each child c_i in topological order]
   +-- Inject format_sibling_guarantees_context({C(f) : f in R_i}) (<= 1,200 chars)
   +-- Execute Leaf Worker with Anchor-Pinned Context (protected_anchor = 1)
   |     +-- On write_file/edit_file(f): extract C(f)=(G_f, A_f) + ACI Counterexample Check
   |     +-- On schema/range/syntax fault: Evidence-Licensed Same-Authority Correction (<=1)
   +-- Verify owned deliverable(s) + Commit Transaction + Seal C(f) for downstream consumers
   |
   v  [2. run_integration_preflight]  (0 LLM calls)
verify_compositional_certificates({C(f) : f in W}) -> Parent Acceptance Oracle -> ROOT VERIFIED
```

### 3.1 Definition 1: Disjoint Ownership Partition & Topological Tiering

In `R_UPDATE_008`, greenfield decomposition suffered from **Blanket Scope Broadcast**: `_source_creation_requirements()` extracted all prompt-declared files $D = \{\texttt{metrics.py}, \texttt{cli.py}, \texttt{test\_metrics.py}\}$ and appended $D$ to every child's `allowed_mutation_paths`. Consequently, Child 1 ("Implement `summarize_latencies` in `metrics.py`") also wrote and committed `test_metrics.py`; when Child 2 (`cli.py`) or Child 3 (`test_metrics.py`) attempted edits, verified-file protections blocked them (`WORKER_NO_MUTATION_PROGRESS`).

**Definition 1 (Disjoint Ownership & Tiered Dependency DAG).** Given candidate children $C = \{c_1, \dots, c_k\}$ and declared workspace paths $D$, `partition_disjoint_child_ownership(C, D)` computes a tuple $(\{O_i\}_{i=1}^k, \{R_i\}_{i=1}^k, E_{\prec})$ satisfying:

1. **Clause-Scoped Mutation vs. Consumer Intent Scoring ($\iota$):** Every path mention $p$ at character span $[s, e)$ in $c_i.\text{goal}$ is scored by analyzing its sentence-bounded clause prefix (`_SENTENCE_BOUNDARY_RE`) and immediate inter-mention prefix:
   $$\iota(c_i, p) = \begin{cases} 1 \quad (\text{CONSUMER}) & \text{if negated } (\texttt{\_NEGATION\_RE}) \text{ or governed by } \texttt{\_CONSUMER\_CONTEXT\_RE}, \\ 2 \quad (\text{SHARED\_SCOPE}) & \text{if } p \in c_i.\text{scope\_hint} \setminus \text{goal}(c_i) \text{ with } |c_i.\text{scope\_hint}| > 1, \\ 3 \quad (\text{NARROW\_SCOPE}) & \text{if unverb-qualified in goal or singleton } c_i.\text{scope\_hint} = [p], \\ 4 \quad (\text{PRIMARY\_MUTATION}) & \text{if governed by } \texttt{\_PRIMARY\_MUTATION\_VERB\_RE} \text{ or destination } \texttt{\_DESTINATION\_IN\_RE}. \end{cases}$$
   Crucially, in a clause such as *"Write unit tests for `metrics.py` in `test_metrics.py`"*, proximity comparison between `_PRIMARY_MUTATION_VERB_RE` (*"Write"*) and `_CONSUMER_CONTEXT_RE` (*"tests for"*) assigns $\iota(\texttt{metrics.py}) = 1$ (`CONSUMER`) while destination preposition matching (`_DESTINATION_IN_RE` on test path `test_metrics.py`) assigns $\iota(\texttt{test\_metrics.py}) = 4$ (`PRIMARY_MUTATION`). Furthermore, whenever $c_i$ possesses a Tier-2 test primary target, all non-test mentions in $c_i$ are demoted to $\iota = 1$.

2. **Producer-to-Consumer Topological Tiers ($\tau$):** Every candidate path $p \in \mathcal{P}$ is mapped deterministically via `_classify_path_tier` into three strict partial-order tiers:
   $$\tau(p) = \begin{cases} 0 \quad (\texttt{TIER\_FOUNDATION\_PRODUCER}) & \text{core Python modules (e.g., } \texttt{metrics.py}\text{), CSS/configs, or HTML shells with external JS}, \\ 1 \quad (\texttt{TIER\_CONSUMER\_ENTRYPOINT}) & \text{Python CLI entrypoints (}\texttt{cli.py}, \texttt{main.py}\text{), external } \texttt{.js/.mjs}\text{, or standalone HTML}, \\ 2 \quad (\texttt{TIER\_VERIFICATION\_SUITE}) & \text{test modules matching } \texttt{test\_*.py}, \texttt{*\_test.py}, \texttt{*.spec.js}, \text{ or } \texttt{tests/*}. \end{cases}$$

3. **Strict Disjointness & Coverage:** Each path $p \in D \cup \bigcup_i \text{mentions}(c_i)$ is assigned to the unique winning owner
   $$w^*(p) = \arg\max_{i \in \text{contenders}(p)} \bigl(\iota(c_i, p),\ \mathbb{I}[\tau(c_i) = \tau(p)],\ -\tau(c_i),\ -i\bigr),$$
   yielding pairwise disjoint writable sets $O_i \cap O_j = \emptyset\ (\forall i \neq j)$ and complete declared coverage $D \subseteq \bigcup_{i=1}^k O_i$. Simultaneously, deferred test-suite assertions are stripped from non-test producer `done_when` clauses, and `_new_project_draft_policy` permits `coherent_rewrite` during child repair *iff* $O_i \neq \emptyset$ and none of $O_i$ existed prior to $c_i$'s transaction—preserving verified sibling immutability (`metrics.py` remains strictly read-only during `cli.py` repair).

4. **Cycle-Free Directed Dependency Graph ($E_{\prec}$):** Priority-weighted candidate edges $(c_p \to c_u)$ are emitted from explicit `depends_on` (`priority = 100`), cross-tier sibling mentions (`90` if $\tau(p) < \tau(u)$, `70` if $\tau(p) = \tau(u)$), HTML/CSS-to-JS structural bindings (`88`), producer-to-CLI/test structural bindings (`85`), and non-blanket scope hints (`60–65`). Adding edges in descending priority order while rejecting any edge where `_would_create_cycle(adj, p, u)` holds guarantees a strict DAG $(C, E_{\prec})$ and populates each consumer's read-only sibling view $R_u$.

### 3.2 Definition 2: Zero-Model Assume-Guarantee Interface Certificates

Inspired by Interface Automata [3], AGISS replaces prose sibling summaries with static, hash-anchored interface certificates computed in $O(|f|)$ time and zero LLM calls.

**Definition 2 (File Interface Certificate & Compositional Compatibility).** For any workspace file $f = (p, \text{bytes})$, `extract_file_certificate(p, content)` parses $f$ using language-native deterministic analyzers—Python `ast.parse`, stateful `_HTMLCertificateParser`, string/comment-preserving ES-module/CommonJS scanner `_extract_js_certificate`, and `@keyframes`-aware CSS selector scanner `_extract_css_certificate`—producing:
$$\mathcal{C}(f) = \bigl(p,\ \ell_f,\ \text{valid}_f,\ G_f,\ A_f,\ h_{\text{content}}(f),\ h_{\text{cert}}(f)\bigr),$$
where:
- **Guarantees $G_f$** export public surface symbols: Python public functions (with positional/keyword parameter names and `defaults_count`), public classes/methods, `UPPER_CASE` / `__all__` constants, and `argparse` `--flags`; HTML `dom_ids`, `canvas_ids`, `button_ids`, `data-*` attributes, `<script type="importmap">` specifier keys, and balanced `<body>`/`</html>` closure; JavaScript ESM/CJS `exports`, `window.AGENT_GAME` methods, and dynamically synthesized `created_dom_ids`; CSS `#id` and `.class` selectors.
- **Assumptions $A_f$** record external obligations: Python relative and sibling module symbol imports; JavaScript `relative_imports`, bare `package_imports`, and `queried_dom_ids` (`getElementById`, `querySelector`); HTML local `module_scripts` and `stylesheets`.

Given a workspace certificate map $\mathfrak{C} = \{p \mapsto \mathcal{C}(f_p)\}$ and known workspace files $\mathcal{F}$, `verify_compositional_certificates` evaluates the global compatibility predicate:
$$\text{Compat}(\mathfrak{C}, \mathcal{F}) \iff \forall p \in \mathfrak{C},\ \forall (q, s, \kappa) \in A_p:\ \bigl(q \in \mathcal{F}\bigr) \land \bigl(s \in \text{Exported}_{\kappa}(G_q)\bigr) \land \neg\text{CoreAddonMisimport}(p, q, s).$$

Specifically, AGISS detects eight compositional violation codes (`hivo/assume_guarantee.py`) and synthesizes exact one-line ACI repair counterexamples (`repair_counterexamples`), summarized in `Table 1A`:

**Table 1A: Deterministic Assume-Guarantee Compositional Violation Codes (`hivo/assume_guarantee.py`)**

| Violation Code | Consumer $p \to$ Producer $q$ | Static Satisfaction Condition Checked | Synthesized 1-Line ACI Counterexample |
|---|---|---|---|
| `MISSING_RELATIVE_MODULE` | `.js`/`.mjs` $\to$ `./mod.js` | $\text{resolve}(p, \text{src}) \in \mathcal{F}$ | `game.js imports './Starfield.js', but no such module exists in workspace files: [...]` |
| `MISSING_JS_EXPORT` | `.js` $\to$ sibling `.js` | $\forall s \in \text{names} \setminus \{*\},\ s \in G_q.\text{exports}$ | `main.js imports 'createShip' from 'ship.js', but ship.js only exports: ['Ship']` |
| `THREE_CORE_MISIMPORTED_FROM_ADDONS` | `.js` $\to$ `three/addons/*` | $\text{names} \cap \texttt{\_THREE\_CORE\_NOT\_ADDONS} = \emptyset$ (`34` r160 core symbols) | `game.js imports Three.js core symbol 'GridHelper' from 'three/addons/...', use: import { GridHelper } from 'three'` |
| `MISSING_IMPORTMAP_SPECIFIER` | `.js` $\to$ entry `.html` | Bare specifier matches exact key or prefix `/` in $G_{\text{html}}.\text{importmap\_keys}$ | `game.js imports bare specifier 'three', but index.html <script type="importmap"> only maps: [...]` |
| `MISSING_DOM_ID` | `.js` $\to$ entry `.html` + JS | $\text{queried\_dom\_ids} \subseteq G_{\text{html}}.\text{dom\_ids} \cup \bigcup G_{\text{js}}.\text{created\_dom\_ids}$ | `game.js assumes DOM '#score', but index.html only defines IDs: ['#canvas-container', '#hud-score']` |
| `MISSING_PYTHON_SYMBOL` | `.py` $\to$ sibling `.py` | Imported symbol $\in G_q.\text{functions} \cup G_q.\text{classes} \cup G_q.\text{constants}$ | `cli.py imports 'compute_mean' from 'metrics.py', but metrics.py only defines: ['summarize_latencies']` |
| `MISSING_HTML_SCRIPT` | `.html` $\to$ local `.js` | $\forall \text{src} \in A_{\text{html}}.\text{module\_scripts},\ \text{resolve}(p, \text{src}) \in \mathcal{F}$ | `index.html loads script './game.js' (resolved to 'game.js'), which is missing from workspace files` |
| `MISSING_HTML_STYLESHEET` | `.html` $\to$ local `.css` | $\forall \text{href} \in A_{\text{html}}.\text{stylesheets},\ \text{resolve}(p, \text{href}) \in \mathcal{F}$ | `index.html links stylesheet './style.css', which is missing from workspace files` |

```text
Algorithm 1: Three-Stage AGISS Certificate Enforcement & Evidence-Licensed Execution
------------------------------------------------------------------------------------
Input:  Decomposed child c_i with owned set O_i, read-only set R_i, upstream certs C_pre
Output: Verified child receipt + updated certificate store C_post, or bounded stop

1: Context Injection (Pre-Execution):
     Render S_ctx <- format_sibling_guarantees_context({C_pre[p] : p in R_i}, O_i, R_i, max=1200)
     Compile Worker Node Packet with S_ctx ("OWNED WRITABLE" vs "READ-ONLY VERIFIED SIBLINGS")
2: Write-Time ACI Gate (During Builder / Repairer Tool Loop):
     Upon legal mutation of p in O_i:
       C_cand[p] <- extract_file_certificate(p, read_utf8(p))
       V <- verify_compositional_certificates(C_pre U C_cand, workspace_files, check_html_assets=False)
       if not V.passed then append V.repair_counterexamples[:3] to immediate tool receipt
3: Before-You-Split Licensing (On Leaf Failure Episode E):
     cls <- classify_failure_episode(E)                      // hivo/evidence_licensed_gate.py
     if cls in {PERMISSION_OR_SCOPE_DENIAL, RESOURCE_OR_BUDGET_LIMIT} then STOP_IMMEDIATELY
     if cls in {SCHEMA_CONTRACT, STALE_RANGE, SYNTAX_REJECTED, BROWSER_RUNTIME} and retries == 0 then
       Execute 1 Same-Authority Correction under unchanged O_i and RunBudget
4: Parent Integration Preflight (Post-Children):
     V_root <- verify_compositional_certificates({extract_file_certificate(f) : f in W}, W)
     Require V_root.passed == True before parent acceptance verification and promotion
```

### 3.3 Theorem / Invariant 1: Truncated-Tool-Call Specification-Amnesia Prevention (`hivo/context.py`)

Live weak-model telemetry in `threejs v2` (`run_id: 20261122T142356-03704885`) and `threejs v4` (`run_id: 20261122T144656-0d47c2d2`) exposed a subtle interaction between output-token limits and bounded context projection. In `v4`, `Builder` emitted a `19.7 KB` `write_file("index.html", ...)` JSON tool call that either truncated at `done_reason = "length"` or was followed by `read_file("index.html")`. When total message characters exceeded `max_chars`, naive oldest-first content compaction iterated from `index = 1` (`projected[1]`, the root user task specification!) and replaced `projected[1]["content"]` with `[HIVO HISTORY OMITTED: non-source metadata only...]`. On the very next turn, `gemma4:e4b` suffered complete **Specification Amnesia**—explicitly reasoning *"The history markers are not useful source material"* in `v2` or overwriting the 3D game in `v4` with a 200-byte `"Welcome!"` HTML stub (triggering four consecutive `missing_canvas` failures in `v4`).

**Theorem / Invariant 1 (Anchor-Pinned Tool-First Compaction).** Let $M = \langle m_0, m_1, \dots, m_{n-1} \rangle$ be a conversation history where $m_0$ is the system prompt, $m_1$ (`role == "user"`) is the authoritative task specification (`protected_anchor = 1`), and $\text{size}(M) = \sum_{j=0}^{n-1} \bigl(|m_j.\text{content}| + |\text{json}(m_j.\text{tool\_calls})|\bigr)$. For any budget $B_{\text{chars}} > |m_0| + |m_1|$, `compact_messages(M, max_chars=B_chars, keep_recent=r)` (`hivo/context.py`) enforces a five-stage priority eviction order:
1. Evict string arguments $> 700$ chars inside `m_j["tool_calls"]` for $j \in [1, n - r)$ (replacing oversized historical `write_file` code strings with `""` while preserving valid tool JSON schema, never inserting copyable placeholder prose into code arguments);
2. Compact `m_j["content"]` ($> 300$ chars) for $j \in [1, n - r) \setminus \{1\}$;
3. Evict string arguments $> 700$ chars inside `m_j["tool_calls"]` across all $j \in [1, n)$ (reclaiming `18–20 KB` truncated `write_file` payloads immediately);
4. Compact intermediate `m_j["content"]` ($> 120$ chars) for $j \in [2, n - 1)$, followed by head-tail slicing ($2/3$ head + $1/3$ tail) of the latest tool result $m_{n-1}$ if $|m_{n-1}.\text{content}| > 300$;
5. Guard `if index == protected_anchor: continue` across every content-compaction pass.

*Proof Sketch.* Because `protected_anchor = 1` is skipped in Stages 2, 4, and 5, and user specification messages carry no `tool_calls` array (`Stage 1, 3` no-ops on $m_1$), $m_1.\text{content}$ is byte-identical in `compact_messages(M, B_chars)` for all $n \ge 2$ and all transient tool-payload sizes. Across `threejs v5..v8` (`11–16` model calls, drafts up to `23.8 KB`), zero Specification Amnesia episodes occurred after enforcing Invariant 1. $\square$

```text
Algorithm 2: Anchor-Pinned Tool-First Context Compaction (hivo/context.py::compact_messages)
--------------------------------------------------------------------------------------------
Input:  Message sequence M = <m_0, m_1, ..., m_{n-1}>, character budget B_chars, keep_recent r
Output: Projected sequence P with projected_size(P) <= B_chars and P[1] == M[1]

1: P <- deepcopy(M)
2: anchor <- 1 if (|P| > 1 and P[1].role == "user") else None
3: cutoff <- max(1, |P| - r)
4: if projected_size(P) > B_chars then                         // Stage 1: old tool_calls args
5:   for j = 1 to cutoff - 1 do
6:     replace string args (> 700 chars) in P[j].tool_calls with "" ; break if size <= B_chars
7: for j = 1 to cutoff - 1 do                                  // Stage 2: old non-anchor prose
8:   if projected_size(P) <= B_chars then break
9:   if j != anchor and |P[j].content| > 300 then P[j].content <- compact_marker(P[j].content)
10: if projected_size(P) > B_chars then                        // Stage 3: recent tool_calls args
11:   for j = 1 to |P| - 1 do
12:     replace string args (> 700 chars) in P[j].tool_calls with "" ; break if size <= B_chars
13: if projected_size(P) > B_chars then                        // Stage 4: intermediate prose + tail
14:   for j = 1 to max(1, |P| - 2) do
15:     if j != anchor and |P[j].content| > 120 then P[j].content <- compact_marker(P[j].content)
16:   if projected_size(P) > B_chars and |P[-1].content| > 300 then
17:     P[-1].content <- head_two_thirds(P[-1].content) + "\n...\n" + tail_one_third(P[-1].content)
18: return P                                                   // Invariant: P[anchor] untouched
```

---

## 4. Dual-Boundary Hardware-Context Law & Role-Conditioned `min_p` Decoding (`hivo/hyperparams.py`)

### 4.1 Empirical Law 1: WDDM GPU KV-Cache Phase Transition & Concurrent VRAM Eviction

Prior agent architectures treat context length `num_ctx` as a smooth latency trade-off. On consumer Windows laptops governed by WDDM (`NVIDIA GeForce RTX 3060 Laptop GPU`, `6,144 MB` dedicated VRAM, `15.2 GB` host RAM, Ollama running `gemma4:e4b` Q4_K_M), we measured exact model residency (`ollama ps`) and steady-state generation throughput across `num_ctx` and concurrent model residency (`Table 1`).

**Table 1: Measured WDDM GPU KV-Cache Residency Cliff & Peer-Eviction Collapse (`gemma4:e4b` Q4_K_M, RTX 3060 Laptop 6 GB VRAM)**

| `num_ctx` ($N_{\text{ctx}}$) | Co-Resident Ollama Peer in VRAM | Total Footprint (`MB`) | GPU VRAMAllocated (`MB`) | GPU Residency (`%`) | Eval Throughput (`tok/s`) | Regime Classification |
|---:|---|---:|---:|---:|---:|---|
| `4,096` | None (idle peers evicted) | `3,084` | `3,084` | `100.0%` | `75.3 – 98.5` | Full-VRAM Optimal |
| `6,144` | None (idle peers evicted) | `3,086` | `3,086` | `100.0%` | `75.7 – 97.9` | Full-VRAM Optimal |
| `8,192` | None (idle peers evicted) | `3,088` | `3,088` | `100.0%` | `75.4` | Full-VRAM Optimal |
| **`10,240`** | **None (idle peers evicted)** | **`3,090`** | **`3,090`** | **`100.0%`** | **`75.9`** | **Exact 100%-GPU Ceiling** |
| `11,264` | None (idle peers evicted) | `9,045` (`+5,955` cliff) | `3,010` | `33.3%` | `64.1` | Partial CPU/RAM Spill |
| `12,288` | None (idle peers evicted) | `9,046` | `3,010` | `33.3%` | `62.8` | Partial CPU/RAM Spill (High-Headroom Synthesis) |
| `16,384` | None (idle peers evicted) | `9,070` | `2,971` | `32.8%` | `59.3` | Partial CPU/RAM Spill |
| **`8,192`** | **Un-evicted `qwen2.5-coder:3b` (`2,299 MB`)** | **`9,020`** | **`0`** | **`0.0%`** | **`4.0`** | **Full CPU Spill (`24.5x` Collapse!)** |

Two hardware laws emerge immediately from `Table 1`:
1. **Non-Linear Allocation Cliff at $N_{\text{ctx}} \in (10240, 11264]$:** Crossing `10,240` tokens triggers an abrupt **`+5,955 MB`** host-memory expansion (`3,090 MB -> 9,045 MB`) as Ollama/GGML spills `66.7%` of model/KV layers across PCIe into system RAM.
2. **Catastrophic Co-Residency Eviction (`24.5x` Slowdown):** When a secondary model (`qwen2.5-coder:3b`, `2,299 MB`) remains warm in `6 GB` VRAM from an earlier probe, loading `gemma4:e4b` at `num_ctx = 8192` fails to fit in the remaining `~3.8 GB` VRAM, forcing a **`0%` GPU / `100%` CPU** allocation that collapses generation from `98.5 tok/s` to **`4.0 tok/s`** (`py agiss v2` `20261122T115130-55e22179` exhausted `540.09s` in just `15` model calls before eviction!).

### 4.2 Empirical Law 2: Dual-Boundary KV Feasibility & Zero-Reload Budgeting

Why not lock $N_{\text{ctx}} = 6144$ universally? Because Ollama allocates a **single shared KV ring** covering both prompt tokens $L_{\text{in}}$ and generated completion tokens $L_{\text{out}}$:
$$L_{\text{in}} + L_{\text{out}} \le N_{\text{ctx}} \quad \implies \quad L_{\text{out}}^{\max} = N_{\text{ctx}} - L_{\text{in}}.$$
In `threejs v1` (`run_id: 20261122T141405-62906c41`), clamping $N_{\text{ctx}} = 6144$ while $L_{\text{in}} = 4,314$ left only $L_{\text{out}}^{\max} = 1,830$ completion tokens (`~6.5 KB`), truncating `18 KB` Three.js single-file `write_file` JSON calls mid-string and causing `CONTEXT_INSUFFICIENT`. Moreover, alternating `num_ctx` across adjacent roles (e.g., `4096` for `Coordinator` vs. `10240` for `Builder`) forces Ollama to reallocate the runner KV cache (`load_duration` spike) on every role switch.

AGISS enforces **Dual-Boundary KV Feasibility** through two coordinated mechanisms in `mini.py`:
1. **Pre-Preflight Idle-Peer VRAM Eviction:** At startup (`mini.py` line `32336`), Mini Hivo queries Ollama `/api/ps` and issues `{"model": m, "keep_alive": 0}` for every loaded model $m \neq \text{MODEL}$, guaranteeing clean `6 GB` VRAM ownership prior to canary/task execution.
2. **Piecewise Hardware-Aware `num_ctx` Selection (`ask_ollama`):** Given estimated prompt tokens $\hat{L}_{\text{in}}$ and role completion cap $N_{\text{predict}}$ (`6,144` for greenfield `Builder` with `write_file`, `4,096` for standard `Builder`, `3,072` for `Repairer`, `1,024–1,536` for analytical roles):
   $$N_{\text{ctx}}(\hat{L}_{\text{in}}, N_{\text{predict}}) = \begin{cases} 10,240 & \text{if } \hat{L}_{\text{in}} + N_{\text{predict}} \le 10,240 \land \hat{L}_{\text{in}} \le 8,192 \quad (\text{100\% GPU ceiling, 0 KV reload}), \\ 12,288 & \text{if } 10,240 < \hat{L}_{\text{in}} + N_{\text{predict}} \le 12,288 \quad (\text{single-file } N_{\text{predict}}=6144 \text{ headroom}), \\ \text{policy}(r) & \text{otherwise.} \end{cases}$$
   For multi-file decomposed children ($N_{\text{predict}} = 4096, \hat{L}_{\text{in}} \le 4000$), $\hat{L}_{\text{in}} + N_{\text{predict}} \le 10,240$ holds throughout execution, sustaining **`100.0%` GPU residency (`75.9–98.5 tok/s`)**; for monolithic `18 KB` Three.js synthesis ($N_{\text{predict}} = 6144, \hat{L}_{\text{in}} \approx 4300$), stepping cleanly to `12,288` sustains `62.8 tok/s` without mid-JSON truncation.

```text
  Throughput (tok/s) & WDDM GPU Residency vs. Shared KV Ring (L_in + L_out <= N_ctx)
  100 tok/s +-------------------------*========*========*========*  100% GPU VRAM (3.09 GB)
            |                         | 4096    6144    8192   10240 <-- Exact 100%-GPU Ceiling
   64 tok/s |                         |                           \
            |   [ Truncation Zone ]   |                            *====*====*  33% GPU (9.05 GB)
            |   if N_ctx = 6144 &     |                          11264 12288 16384
            |   L_in=4314 -> L_out    |
    4 tok/s |   capped at 1830 tok!   |                 [x] 8192 + Co-Resident Peer (2.30 GB)
    0 tok/s +-------------------------+------------------>  0% GPU / 100% CPU Spill (24.5x drop!)
```

### 4.3 Empirical Law 3: Cold Epoch-0 Synthesis vs. Warm Stagnation Escape (`hivo/hyperparams.py`)

Grounded in Min-p confidence scaling [9], code-generation adaptive temperature [10, 11], and low-temperature analytical stability [12], `resolve_decoding_options` (`--decoding-policy adaptive`) maps role $r$, retry epoch $e \ge 0$, and stagnation counter $s \ge 0$ ($\text{steps} = e + s$, prime stride $\Delta_{\text{seed}} = 7919$) to Ollama sampling options (`Table 2`).

**Table 2: Role- and Epoch-Conditioned Adaptive Decoding Schedule (`hivo/hyperparams.py`)**

| Decoding Regime | Condition (`role`, `structured`, `epoch` $e$, `stagnant` $s$) | Temperature $T$ | `min_p` | `top_p` | `repeat_penalty` / `repeat_last_n` | Seed Schedule |
|---|---|---:|---:|---:|---|---|
| **Analytical / Structured** | `structured=True` or $r \in \text{ANALYTICAL\_ROLES}$ ($e=0, s=0$) | `0.05` | `0.05` | `0.85` | `1.00` / `64` | $s_0$ |
| **Analytical Retry** | `structured=True` or $r \in \text{ANALYTICAL\_ROLES}$ ($e+s \ge 1$) | $\min(0.20,\ 0.05 + 0.05(e+s))$ | `0.05` | `0.85` | `1.00` / `64` | $(s_0 + 7919(e+s)) \bmod 2^{31}$ |
| **Cold Epoch-0 Synthesis** | `Builder` initial synthesis ($e=0, s=0$, unstructured) | **`0.08`** | **`0.08`** | **`0.90`** | `1.00` / `64` | $s_0$ |
| **Warm Recovery / Escape** | $r = \text{Repairer}$ or `Builder` with $e \ge 1 \lor s \ge 1$ | $\min(0.48,\ 0.20 + 0.08e + 0.08s)$ | $\min(0.16,\ 0.07 + 0.025(e+s))$ | `0.94` | `1.00`/`64` ($s=0$); $\min(1.15, 1.06+0.03(s-1))$ / `192` ($s \ge 1$) | $(s_0 + 7919\max(1, e+s)) \bmod 2^{31}$ |
| **Fixed Baseline (`fixed`)** | `--decoding-policy fixed` | `base_temperature` (`0.10`) | *(omitted)* | *(omitted)* | *(omitted)* | $s_0$ |

**Live Ablation Discovery (`threejs v6` vs. `v8`):** An intermediate hypothesis tested a warmer Epoch-0 `Builder` prior ($T_0 = 0.15, \text{min\_p} = 0.06, \text{top\_p} = 0.92$) in `threejs v6` (`run_id: 20261122T150726-38e4aa08`). On `4B` quantized weights over a `5,000+`-token HTML+JS generation horizon, even $T_0 = 0.15$ compounded tail-token variance: `gemma4:e4b` generated verbose `23.8 KB` drafts (`34,656` total output tokens), hallucinated non-existent Three.js r160 methods (`Sphere.distanceTo`, `player.distanceTo`) triggering browser `page_errors`, and exhausted the `660s` wall-clock budget. Lowering Epoch-0 `Builder` to **Cold Synthesis** ($T_0 = 0.08, \text{min\_p} = 0.08, \text{top\_p} = 0.90$) while reserving $T \in [0.20, 0.48]$ + prime seed stride $+7919$ strictly for `Repairer` and stagnant retries (`e >= 1` or `s >= 1`) eliminated all Turn-1 JavaScript runtime errors and reduced total output tokens by **`78.1%`** (`34,656 -> 7,574` in `v8`)!

```text
Algorithm 3: Dual-Boundary Context & Role-Conditioned min_p Controller (ask_ollama + hyperparams)
-------------------------------------------------------------------------------------------------
Input:  Role r, messages M, tools T, structured flag F, policy pi, epoch e, stagnant s, seed s_0
Output: Provider options {num_ctx, num_predict, temperature, min_p, top_p, repeat_penalty, seed}

1: Startup Once: for each peer m != MODEL in GET /api/ps do POST /api/generate {m, keep_alive: 0}
2: P <- compact_messages(M, max_chars = floor(1.5 * policy_ctx(r)), keep_recent = 4)
3: L_hat <- estimate_context_tokens(P)
4: N_pred <- 6144 if (r == "Builder" and "write_file" in T and NEW_PROJECT) else role_predict(r)
5: if pi == "adaptive" and policy_ctx(r) >= 8192 then
6:   if L_hat + N_pred <= 10240 and L_hat <= 8192 then N_ctx <- 10240     // 100% GPU VRAM
7:   else if L_hat + N_pred <= 12288 then N_ctx <- 12288                  // 6144-pred headroom
8: if pi == "fixed" then return {num_ctx: N_ctx, num_predict: N_pred, temperature: T_base, seed: s_0}
9: steps <- e + s
10: if F or r in ANALYTICAL_ROLES then
11:   T <- min(0.20, 0.05 + 0.05 * steps) if steps >= 1 else 0.05
12:   return {num_ctx: N_ctx, num_predict: N_pred, T: T, min_p: 0.05, top_p: 0.85,
              repeat_penalty: 1.0, repeat_last_n: 64, seed: (s_0 + 7919 * steps) mod 2^31}
13: if r in RECOVERY_ROLES or steps >= 1 then                             // Warm Escape Regime
14:   T <- min(0.48, 0.20 + 0.08 * e + 0.08 * s) ; mp <- min(0.16, 0.07 + 0.025 * steps)
15:   rp <- min(1.15, 1.06 + 0.03 * (s - 1)) if s >= 1 else 1.0 ; rln <- 192 if s >= 1 else 64
16:   return {num_ctx: N_ctx, num_predict: N_pred, T: T, min_p: mp, top_p: 0.94,
              repeat_penalty: rp, repeat_last_n: rln, seed: (s_0 + 7919 * max(1, steps)) mod 2^31}
17: return {num_ctx: N_ctx, num_predict: N_pred, T: 0.08, min_p: 0.08, top_p: 0.90,
            repeat_penalty: 1.0, repeat_last_n: 64, seed: s_0}            // Cold Synthesis
```

---

## 5. Perceptual & Behavioral Workmanship Oracles (`hivo/quality_rubric.py`, `hivo/verification.py`)

To close the visual-interactive evaluation gap [15, 16] without invoking slow or hallucination-prone VLM judges, AGISS instruments `browser_snapshot` and `evaluate_web_snapshot` with three deterministic browser workmanship gates.

### 5.1 Pre-Start Center-Playfield Luminance Oracle (`blank_initial_canvas`)

In weak-model 3D games, a pervasive anti-pattern is placing `if (status !== 'playing') return;` *above* `renderer.render(scene, camera)` inside `animate()`, or deferring `requestAnimationFrame(animate)` until `start()`. Because DOM overlays (`<h1>Neon Starfighter 3D</h1>`, `<button>START</button>`) still render crisp text along the viewport perimeter, full-page pixel variance can be non-zero even when the `<canvas>` itself is unrendered!

AGISS isolates the **inner playfield** *before* `window.AGENT_GAME.start()` is invoked (`mini.py` lines `17598–17622`):
1. Capture a pre-interaction viewport JPEG ($1440 \times 900$) and downsample onto an offscreen $48 \times 32$ 2D canvas.
2. Crop the central $36 \times 20$ playfield window ($x \in [6, 42), y \in [6, 26)$, $N = 720$ macro-pixels), excluding top/bottom/corner HUD chrome.
3. Compute ITU-R BT.601 luma $Y_p = 0.299 R_p + 0.587 G_p + 0.114 B_p$ and population standard deviation:
   $$\sigma_Y = \sqrt{\max\!\left(0,\ \frac{1}{N}\sum_{p=1}^{N} Y_p^2 - \left(\frac{1}{N}\sum_{p=1}^{N} Y_p\right)^2\right)}, \qquad \text{initialFrameBlank} \iff (\sigma_Y < 0.75).$$
Empirically, unrendered solid-backdrop canvases (`R_UPDATE_008` `v9`, plus early-return drafts in `threejs v4`, `v5`, `v6`) yield **$\sigma_Y = 0.000 < 0.75 \implies \texttt{FAIL (blank\_initial\_canvas)}$**, whereas live pre-start 3D scenes rendering starfields, perspective `GridHelper`, lit starfighter geometry, and rotating crystals yield **$\sigma_Y \in [4.841,\ 65.243] \implies \texttt{PASS}$** (`40.189` and `48.578` in `threejs v8`) — a clean $>6\times$ margin above threshold.

### 5.2 DOM Bounding-Box HUD Anti-Overlap Oracle (`hud_layout_overlap`) & Flexbox Pigeonhole Principle

`BROWSER_CANVAS_QUALITY_JS` (`hivo/quality_rubric.py`) collects all visible positioned HUD blocks (`position: fixed | absolute`, $20\text{ px} \le w < 0.92 W_{\text{vp}}$, $14\text{ px} \le h < 0.85 H_{\text{vp}}$) and interactive controls (`<button>`, `<input>`, `[role="button"]`), and evaluates pairwise axis-aligned bounding-box intersections for non-nested elements $a \neq b$:
$$I_x(a,b) = \min(r_a, r_b) - \max(l_a, l_b), \quad I_y(a,b) = \min(b_a, b_b) - \max(t_a, t_b),$$
$$\text{Overlap}(a,b) \iff \bigl(I_x(a,b) > 6\text{ px}\bigr) \land \bigl(I_y(a,b) > 6\text{ px}\bigr) \land \bigl(I_x(a,b) \cdot I_y(a,b) \ge 48\text{ px}^2\bigr).$$

Across `threejs v4..v7`, this oracle exposed a structural **Corner Pigeonhole Collision**: prompts requesting five distinct HUD groups (*Title/Status*, *Score*, *Crystals*, *Controls Legend*, *Start/Reset Buttons*) caused `gemma4:e4b` to assign `position: absolute` corner coordinates (`top: 20px; left: 20px`, etc.). By the Pigeonhole Principle ($5 \text{ widgets} > 4 \text{ viewport corners}$), at least two widgets collided (`#hud-crystals-panel vs #hud-status` in `v4`/`v5`; `#crystals-display vs #status-badge` in `v6`; `#hud-score vs #hud-controls` and `#crystals-container vs #status-badge` in `v7`). Updating the `threejs_3d` finishing rubric (`< 1,300` chars) to prescribe a top/bottom Flexbox bar (`display: flex; justify-content: space-between`) eliminated corner collisions on Turn 1 (`hudOverlapCount = 0` in `v8`).

```text
  [A] Naive 4-Corner Absolute Layout (v4..v7: FAIL)     [B] AGISS Flexbox Bar + Inner Luminance (v8: PASS)
  +-----------------------------------------------+     +-----------------------------------------------+
  | [#title + #status]    [#score] OVERLAPS       |     | [Title | Status | Score | Crystals] (FlexBar) |
  |                       [#crystals] (I >= 48px2)|     |   +---------------------------------------+   |
  |                                               |     |   | 36x20 Inner Playfield Crop (N = 720)  |   |
  |        Blank #050816 if early-return          |     |   | Starfield + GridHelper + Starfighter  |   |
  |        before renderer.render (sigma_Y = 0.0) |     |   | Pre-Start sigma_Y = 40.19 >= 0.75 OK! |   |
  |                                               |     |   +---------------------------------------+   |
  | [#controls-legend]           [#start][#reset] |     | [WASD/Arrows Legend    |    START | RESET ]   |
  +-----------------------------------------------+     +-----------------------------------------------+
```

### 5.3 Word-Boundary Profile Hygiene, JSON-String Bridge Coercion & Six-Angle QA

Live runs uncovered two verifier-contamination bugs that previously masqueraded as model incapacity:
- **Substring Profile Contamination (`hivo/verification.py`):** Plain substring checks matched `"touch"` inside `"untouched"` (falsely requiring mobile `touch_control` D-pads on desktop games) and matched `"win"`/`"goal"` inside `"window.AGENT_GAME"` or contract JSON keys `"goal":` (falsely requiring `goal_win_state` on endless arcade survival games). Replacing substring checks with word-boundary regular expressions (`\b(?:touch|mobile|responsive controls)\b` and `\b(?:win|won|goal|finish)\b` over semantic text) eliminated false-positive interaction failures.
- **`JSON.stringify` Bridge Coercion (`mini.py::_coerce_game_state_dict`):** In `threejs v3` (`20261122T143139-8e9a4a98`), `gemma4:e4b` implemented `AGENT_GAME.getState()` returning `JSON.stringify({...})`, crashing Python dictionary `.get()` (`'str' object has no attribute 'get'`). `_coerce_game_state_dict` parses JSON-serialized state strings through `_acyclic_browser_value` seamlessly.
- **Six-Angle Adversarial QA (`build_six_angle_qa_checklist`):** Injects a compact ($\le 600$ chars) checklist into `Falsifier` covering *Functionality*, *Preservation*, *Interface/DOM Binding*, *Error/Input Resilience*, *Visual/HUD Non-Overlap & Initial Render*, and *State Reset & Single-RAF Hygiene*.

---

## 6. End-to-End Live Experimental Evaluation

### 6.1 Experimental Setup & Scientific Attribution Discipline

All live experiments were executed on a single consumer Windows machine (`NVIDIA GeForce RTX 3060 Laptop GPU` `6 GB` VRAM, WDDM driver, `15.2 GB` RAM, local Ollama) with **zero mocks**, real subprocess/Node syntax gates, real headless Playwright Chromium WebGL (`1440x900` desktop + `390x844` mobile probes where applicable), and `SingleModelPolicy` pinning every one of Mini Hivo's 17 roles to a single local model (`gemma4:e4b`, plus comparative trials on `qwen2.5-coder:3b`). In strict adherence to repository reporting rules, every failed, budget-exhausted, and diagnostic trial is preserved in full without selective omission.

### 6.2 Headline Comparison: `R_UPDATE_008` Baseline vs. `AGISS`

`Table 3` compares the published `R_UPDATE_008` baseline (`commit 3b2d8b5`) against AGISS (`mini.py` final `source_sha256: 03ebfa8af7cd1ff01e0ab70ef9b476c7a1f5ff83eac380d30a6e423d8cd62b61`, live `threejs v8` `source_sha256: 3bf32fbdab883b9f17ab1baaf73abe28d02383e335ae15a8b18acc89e0a97492`) on both multi-file recursive Python synthesis (`Swarm Telemetry Analyzer`: `metrics.py` + `cli.py` + `test_metrics.py`) and standalone 3D WebGL game synthesis (`Neon Starfighter 3D`: `index.html` using `three@0.160.0`).

**Table 3: End-to-End Live `gemma4:e4b` Performance — `R_UPDATE_008` vs. `AGISS`**

| Benchmark & Metric | `R_UPDATE_008` Baseline (`gemma4:e4b`) | `AGISS` (`gemma4:e4b`) | Measured Delta / Outcome Improvement |
|---|---|---|---|
| **A. Multi-File Recursive Python (`metrics.py` + `cli.py` + `test_metrics.py`)** | | | |
| Verified Root Pass Rate | **`0 / 5` (`0.0%`)** (`a8b08862`..`11fb390d`) | **`2 / 2` (`100.0%`)** consecutive post-convergence (`py v8`, `py v9`) | **`0% -> 100%` (`[ROOT VERIFIED] PASS`)** |
| Task-Tree Completion (`done_nodes / total_nodes`) | Max `1 / 4` (`Child 2` blocked by sibling lock) | **`4 / 4` (`Child 1`, `Child 2`, `Child 3`, `ROOT`)** | Complete 3-tier DAG + Root integration |
| Model Calls (`py v8` / task-agnostic `py v9`) | `45 – 95` (all failed/exhausted) | **`38`** (`py v8`) / **`49`** (`py v9`) | Converges well within 65-call budget |
| Tool Calls (`py v8` / `py v9`) | `31 – 79` | **`23`** (`py v8`) / **`33`** (`py v9`) | Zero unauthorized cross-sibling writes |
| Input / Output Tokens (`py v8` / `py v9`) | `174,021–493,459` in / `6,663–24,155` out | **`126,220 / 9,818`** (`v8`); **`159,905 / 10,879`** (`v9`) | Up to **`-67.6%`** lower peak input tokens |
| `repairer_calls` (`py v8` & `py v9`) | `0 – 1` (failed repair) | **`0`** (`0` in `v8`, `0` in `v9`) | First-pass sibling compatibility via $\mathcal{C}(f)$ |
| Wall-Clock Elapsed Seconds | `177.29s – 537.68s` (all `exit_code = 1`) | **`198.46s`** (`py v8`) / **`211.89s`** (`py v9`) (`exit_code = 0`) | **`-56.9%`** faster than `R_UPDATE_008` `v5` (`465.64s`) |
| **B. Human-Ready 3D WebGL Game (`Neon Starfighter 3D` in `index.html`)** | | | |
| Run ID & Exit Status | `20261122T035103-a23aed75` (`exit 0`) | **`20261122T153409-45b4cd0f` (`exit 0`)** | Verified E2E + Perceptual/HUD Oracles |
| Wall-Clock Elapsed Seconds | `284.67s` | **`184.04s`** | **`-35.3%` faster (`-100.63s`)** |
| Model Calls / Tool Calls | `14` model / `9` tool | **`8` model / `4` tool** | **`-42.9%` model calls / `-55.6%` tool calls** |
| Reported Input / Output Tokens | `45,137` in / `13,687` out | **`32,138` in / `7,574` out** | **`-28.8%` input / `-44.7%` output tokens** |
| Pre-Start 3D Scene Render (`initialFrameBlank`, $\sigma_Y$) | **Blank `#050816`** ($\sigma_Y = 0.0$, `True`) | **Live 3D Scene** ($\sigma_Y = 40.189\text{ / }48.578$, `False`) | Eliminates paused blank-canvas defect |
| HUD Anti-Overlap (`hudOverlapCount`) | Unchecked | **`0` overlaps** (`18,751` B deliverable) | Zero button/score/badge collisions |

Independent external Playwright human-button auditing of `threejs v8`'s persisted `18,751`-byte `index.html` (`sha256: f6673118af7169b0400430f824d8d8e6e41a1d840e0e2a0b23f0a8dde58f1665`) at `1440x900` confirmed three clean human states with zero console/page/network errors: *(1) Initial Load before clicking Start* (`status="paused"`, live rendered starfield, cyan/slate `GridHelper`, cyan starfighter, golden crystals, non-overlapping Flexbox HUD), *(2) Active Gameplay* (real `START` click + held keyboard flight + crystal collection updating HUD score/crystal counters and respawning crystals), and *(3) Clean Reset* (real `RESET` click restoring origin coordinates and `score = 0` with a single `requestAnimationFrame` loop).

### 6.3 Complete Multi-File Recursive Python Progression & `qwen2.5-coder:3b` Findings

`Table 4` documents the complete unedited multi-file recursive Python trajectory from `R_UPDATE_008` (`0/5`) through AGISS `py v1..v9` and the `qwen2.5-coder:3b` cross-model probe. Importantly, after `py v8` (`20261122T140443-fb94f671`) achieved `[ROOT VERIFIED] PASS` in `198.46s`, we audited all hints to ensure zero task-specific prompt leakage, generalized the CLI JSON/argument recovery hint (`3790e4fd...`), and immediately re-ran a fresh workspace (`py v9`, `20261122T140910-1b993032`), which again passed `4/4` nodes cleanly with `repairer_calls = 0` (`211.89s`).

**Table 4: Complete Multi-File Recursive Python Progression (`metrics.py` + `cli.py` + `test_metrics.py`)**

| Cohort / Trial | Run ID (`source_sha256` prefix) | Model | Calls (M / T) | Tokens (In / Out) | Time (`s`) | Nodes (`done/total`) | Outcome & Exact Boundary / Architectural Fix Validated |
|---|---|---|---:|---:|---:|---:|---|
| `R_UPDATE_008` `v1..v5` (5 runs) | `a8b08862` .. `11fb390d` (`8fe5905c`) | `gemma4:e4b` | `45–95` / `31–79` | `174k–493k` / `6.7k–24.2k` | `177.3–537.7` | Max `1/4` (`0/5` pass) | **Baseline `0/5`:** Blanket creation paths let Child 1 steal `test_metrics.py`; Child 2 hit `WORKER_NO_MUTATION_PROGRESS` on Child 1's files |
| `agiss-pre` `v2` | `20261122T115130-55e22179` (`b5fb5b63`) | `gemma4:e4b` | `15` / `7` | `37,033` / `4,364` | `540.09` | `0/4` (`budget`) | Uncovered **`4.0 tok/s` CPU spill** caused by co-resident peer model in `6 GB` VRAM (`Table 1`); fixed via `/api/ps` `keep_alive: 0` eviction |
| `qwen3b` `v1` | `20261122T122340-d28245d6` | `qwen2.5-coder:3b` | `6` / `0` | `17,793` / `1,326` | `25.05` | `0/1` (`failed`) | `100.0 tok/s` in VRAM (`2,299 MB`), but emitted tool calls as raw JSON inside `message.content` (`tool_calls = []`) |
| `qwen3b` `v2` | `20261122T122922-93962157` (`1edbe8a2`) | `qwen2.5-coder:3b` | `31` / `26` | `121,443` / `4,897` | `51.76` | `0/1` (`failed`) | Post-reanchor `text_json_tool_adapter_active` unlocked `26` tool calls, exposing `context_sufficiency_check` schema friction on `3B` weights |
| `qwen3b` `v3` | `20261122T123339-621de6ba` | `qwen2.5-coder:3b` | `24` / `15` | `49,811` / `5,651` | `360.07` | `0/5` (`budget`) | Split into 4 children and entered Child 1 `metrics.py` repair, establishing `3B` tool-adapter viability but lower Python edge-case precision than `4B` |
| `py live` `v1` | `20261122T132837-5be1f25e` (`2fa46e27`) | `gemma4:e4b` | `41` / `33` | `151,300` / `7,676` | `144.13` | `0/4` (`failed`) | Disjoint `O_1={metrics.py}` worked (`~98 tok/s`!), but Child 1 ran deferred `test_metrics.py` check before Child 3 existed |
| `py live` `v2` | `20261122T133529-daa531ff` (`2fa46e27`) | `gemma4:e4b` | `10` / `2` | `40,266` / `2,370` | `56.54` | `0/4` (`failed`) | Empty `<end_of_turn>` reply (`content_chars=0`); fixed via seed-rotated `+7919` empty-turn retry |
| `py live` `v3..v5` | `1278875e`, `b1fa72f5`, `f762f576` | `gemma4:e4b` | `15–35` / `9–23` | `49.9k–128.7k` / `3.1k–8.4k` | `61.5–144.7` | `0/4` (`failed`) | `REQUIRED_VERIFICATION_TARGET_UNRESOLVED` on Child 1: `check_call` rejected `3 == 3.0` JSON float equivalence & `[not_applicable]` test routing; fixed in `python_checks.py` & `verification_routing.py` |
| `py live` `v6` | `20261122T135018-3e2ac364` (`d60f5af2`) | `gemma4:e4b` | `54` / `42` | `196,079` / `11,668` | `225.71` | `1/4` (`failed`) | **Child 1 (`metrics.py`) `[VERIFY 1] PASS` -> `[DONE 1]`!** Child 2 (`cli.py`) consumed certificate $\mathcal{C}(\texttt{metrics.py})$, caught `sort_keys=True` in `Falsifier`, stalled in `edit_file` |
| `py live` `v7` | `20261122T135607-7ed7c4f9` (`4f63be66`) | `gemma4:e4b` | `51` / `40` | `181,519` / `18,627` | `322.59` | `1/4` (`failed`) | Child 2 `Repairer` blocked from `coherent_rewrite` on its own unverified `cli.py` draft because sibling `metrics.py` existed; fixed in `_new_project_draft_policy` |
| **`py live` `v8`** | **`20261122T140443-fb94f671` (`43ac9e1b`)** | **`gemma4:e4b`** | **`38` / `23`** | **`126,220` / `9,818`** | **`198.46`** | **`4/4` (`done`)** | **`[VERIFY 1, 2, 3, ROOT] PASS` -> `[ROOT VERIFIED] PASS` (`exit_code = 0`, `repairer_calls = 0`, all 3 deliverables verified)** |
| **`py live` `v9`** | **`20261122T140910-1b993032` (`3790e4fd`)** | **`gemma4:e4b`** | **`49` / `33`** | **`159,905` / `10,879`** | **`211.89`** | **`4/4` (`done`)** | **Task-agnostic confirmation run (`exit_code = 0`, `repairer_calls = 0`, `4/4` nodes verified consecutively)** |

### 6.4 Complete Three.js 3D WebGL Diagnostic & Hyperparameter Progression (`threejs v1..v8`)

`Table 5` traces every live Three.js run under the tightened perceptual (`blank_initial_canvas`) and geometric (`hud_layout_overlap`) workmanship gates, demonstrating how each empirical law in `§3.3–§5` was falsified and validated against real hardware and browser telemetry.

**Table 5: Complete Live `gemma4:e4b` Three.js 3D WebGL Progression (`Neon Starfighter 3D`)**

| Trial | Run ID (`source_sha256` prefix) | Calls (M / T) | Tokens (In / Out) | Time (`s`) | Pre-Start $\sigma_Y$ (`Blank?`) | `hudOverlapCount` (Colliding Selectors) | Outcome & System Law Discovered |
|---|---|---:|---:|---:|---|---|---|
| `v1` | `20261122T141405-62906c41` (`3790e4fd`) | `15` / `11` | `58,374` / `17,281` | `331.75` | *(pre-browser)* | *(pre-browser)* | **Law 2 (`§4.2`):** $N_{\text{ctx}}=6144$ with $L_{\text{in}}=4314$ left $1830$ output tokens, truncating `18 KB` `write_file` JSON -> `CONTEXT_INSUFFICIENT` |
| `v2` | `20261122T142356-03704885` (`c2c18042`) | `10` / `5` | `27,277` / `7,931` | `149.35` | *(pre-browser)* | *(pre-browser)* | **Invariant 1 (`§3.3`):** Compaction overwrote `projected[1]` -> model wrote *"The history markers are not useful source material"* |
| `v3` | `20261122T143139-8e9a4a98` (`84d1383e`) | `11` / `7` | `46,326` / `25,337` | `420.03` | *(bridge err)* | *(bridge err)* | **`§5.3` Bridge Coercion:** `AGENT_GAME.getState()` returned `JSON.stringify(...)`, raising `'str' object has no attribute 'get'`; fixed via `_coerce_game_state_dict` |
| `v4` | `20261122T144656-0d47c2d2` (`e2705787`) | `20` / `14` | `73,394` / `15,246` | `420.03` | `17.713` (`F`), then `0.0` (`T`) | `1` (`#hud-crystals-panel vs #hud-status`; `#score-display vs #crystals-display`) | Caught real HUD overlap + blank paused canvas, then `read_file` overflow compacted `projected[1]` -> `"Welcome!"` overwrite (`missing_canvas`); sealed `protected_anchor = 1` |
| `v5` | `20261122T145725-eb676a65` (`38eee5a0`) | `11` / `7` | `46,506` / `17,947` | `420.04` | `18.013` (`F`), then `0.0` (`T`) | `1` (`#hud-crystals-panel vs #hud-status`), then `0` | Zero Specification Amnesia! Exposed `"untouched"` / `"window"` substring contamination requiring unrequested `touch_control` / `goal_win_state` (`§5.3`) |
| `v6` | `20261122T150726-38e4aa08` (`38eee5a0`) | `16` / `12` | `78,750` / **`34,656`** | `660.05` | `65.243` (`F`), `0.0` (`T`), `4.841` (`F`) | `1` (`#crystals-display vs #status-badge`; `#score-panel vs #controls-legend`) | **Law 3 (`§4.3`):** Warm Epoch-0 `Builder` ($T_0=0.15$) inflated drafts to `23.8 KB` (`34,656` out tokens) and hallucinated `Sphere.distanceTo` / `player.distanceTo` |
| `v7` | `20261122T152037-751884be` (`38eee5a0`) | `14` / `10` | `65,388` / `34,029` | `660.04` | `45.827` (`F`), `20.524` (`F`) | `4` (`#hud-score vs #hud-controls`, ...), then `1` (`#crystals-container vs #status-badge`) | Passed pre-start render ($\sigma_Y > 20$) and all flight/collection/reset mechanics; isolated **5-into-4 Corner Pigeonhole Collision (`§5.2`)** |
| **`v8`** | **`20261122T153409-45b4cd0f` (`3bf32fbd`)** | **`8` / `4`** | **`32,138` / `7,574`** | **`184.04`** | **`40.189` / `48.578` (`False`)** | **`0` (Zero overlaps across Builder & Falsifier)** | **Cold Epoch-0 ($T_0=0.08$) + Flexbox HUD rubric: Turn-1 clean pass (`exit_code = 0`, `-78.1%` out tokens vs `v6`, `-35.3%` time vs `R_UPDATE_008`)** |

### 6.5 Deterministic Offline & Real-Chromium Controlled Verification

Alongside live inference runs, every AGISS mechanism is locked by deterministic offline unit, controlled-functional, and real headless Chromium WebGL suites:
- `tests/test_assume_guarantee.py` (**`22/22` passed**): Clause-level mutation vs. consumer intent scoring, blanket-scope filtering, cycle prevention, Python/HTML/ESM/CSS certificate extraction, `_THREE_CORE_NOT_ADDONS` detection, and `<= 1,200`-char sibling guarantee formatting.
- `tests/test_hyperparams.py` (**`14/14` passed**): Role/epoch/stagnation schedules, `fixed` backward compatibility, prime-stride seed bounds, and `hivo/job_runtime.py` Ollama option whitelist validation.
- `tests/test_threejs_quality_verification.py` (**`23/23` passed**): Domain rubrics (`1,288 < 1,300` chars), word-boundary profile inference, 6-angle QA checklist (`<= 600` chars), and real Chromium WebGL `0x0`, `blank_initial_canvas`, and `hud_layout_overlap` probes.
- `tests/test_agiss_multifile_and_visual_e2e.py` (**`24/24` passed**): End-to-end controlled 3-child recursive Python `[ROOT VERIFIED] PASS`, modular Three.js compositional certificate preflight (`index.html` + `game.js` + `style.css`), and real Chromium visual workmanship gates.

---

## 7. Threats to Validity, Limitations & Future Work

1. **Single-Host WDDM GPU Calibration (External Validity):** `Table 1`'s exact `10,240 -> 11,264` allocation cliff (`3,090 MB -> 9,045 MB`) is specific to `gemma4:e4b` (Q4_K_M) on a `6 GB` NVIDIA RTX 3060 Laptop GPU under Windows WDDM. Larger GPUs (`8–24 GB`), Linux CUDA unified-memory drivers, or Apple Silicon unified memory will exhibit shifted cliff thresholds $N_{\text{VRAM-ceiling}}$, although the Dual-Boundary inequality $L_{\text{in}} + L_{\text{out}} \le N_{\text{ctx}} \le N_{\text{VRAM-ceiling}}$ and peer-eviction necessity hold structurally across shared-KV local runners. Future work should auto-calibrate $N_{\text{VRAM-ceiling}}$ dynamically during host preflight by inspecting Ollama `/api/ps` `size_vram / size` ratios.
2. **Multi-File Three.js Split Scope (Construct & Scope Validity):** While AGISS's multi-file recursive synthesis was validated **live** on 3-file Python (`py v8`, `py v9`: `4/4` nodes verified) and **live** on standalone Three.js 3D WebGL (`threejs v8`), multi-file Three.js decomposition (`index.html` + `game.js` + `style.css`) is currently verified at the **controlled-functional + real-Chromium integration** level (`tests/test_agiss_multifile_and_visual_e2e.py`), not yet as a fresh live multi-child `gemma4:e4b` run. In accordance with repository measurement standards, we keep controlled-functional proof strictly distinct from live-model completion claims.
3. **Static Interface Certificates vs. Behavioral Refinement:** `extract_file_certificate` verifies syntactic and structural symbol/DOM/import contracts in $O(|f|)$ time; it does not statically prove semantic type invariants or temporal protocol ordering (e.g., whether an exported JS function mutates state before rendering). AGISS therefore relies on pairing static certificates with executable subprocess and Playwright behavioral oracles rather than substituting static checks for runtime verification.
4. **Stochastic Variance Across Quantizations & Model Families:** Although Cold Epoch-0 decoding ($T_0 = 0.08, \text{min\_p} = 0.08$) produced consecutive `2/2` multi-file Python passes and Turn-1 Three.js convergence on `gemma4:e4b`, smaller models such as `qwen2.5-coder:3b` still exhibited tool-schema friction on `context_sufficiency_check` (`Table 4`). Broader multi-seed cohorts ($N \ge 10$ per task family) across `3B–8B` open-weight families remain essential future work.

---

## 8. References

1. **Cemri, M., Pan, M. Z., Yang, S., Agrawal, L. A., Chopra, B., Tiwari, R., Keutzer, K., Parameswaran, A., Klein, D., Ramchandran, K., Zaharia, M., Gonzalez, J. E., & Stoica, I.** (2025). *Why Do Multi-Agent LLM Systems Fail?* arXiv preprint `arXiv:2503.13657` (MAST 14-mode failure taxonomy).
2. **Kim, Y., Gu, K., Park, C., Park, C., Schmidgall, S., Heydari, A. A., Yan, Y., Zhang, Z., Zhuang, Y., Malhotra, M., Liang, P. P., Park, H. W., Yang, Y., Xu, X., Du, Y., Patel, S., Althoff, T., McDuff, D., & Liu, X.** (2025). *Towards a Science of Scaling Agent Systems*. arXiv preprint `arXiv:2512.08296`.
3. **de Alfaro, L., & Henzinger, T. A.** (2001). *Interface Automata*. In Proceedings of the 8th European Software Engineering Conference held jointly with 9th ACM SIGSOFT International Symposium on Foundations of Software Engineering (ESEC/FSE 2001), pp. 109–120. `DOI: 10.1145/503271.503226`.
4. **Sun, C., Sheng, Y., Padon, O., & Barrett, C.** (2023). *Clover: Closed-Loop Verifiable Code Generation*. arXiv preprint `arXiv:2310.17807`.
5. **Hong, S., Zhuge, M., Chen, J., Zheng, X., Cheng, Y., Wang, J., Zhang, C., Wang, Z., Yau, S. K. S., Lin, Z., Zhou, L., Ran, C., Xiao, L., Wu, C., & Schmidhuber, J.** (2024). *MetaGPT: Meta Programming for A Multi-Agent Collaborative Framework*. In International Conference on Learning Representations (ICLR 2024). `arXiv:2308.00352`.
6. **Qian, C., Liu, W., Liu, H., Chen, N., Dang, Y., Li, J., Yang, C., Chen, W., Su, Y., Cong, X., Xu, J., Li, D., Liu, Z., & Sun, M.** (2024). *ChatDev: Communicative Agents for Software Development*. In Proceedings of the 62nd Annual Meeting of the Association for Computational Linguistics (ACL 2024). `arXiv:2307.07924`.
7. **Yang, J., Jimenez, C. E., Wettig, A., Lieret, K., Yao, S., Narasimhan, K., & Press, O.** (2024). *SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering*. In Advances in Neural Information Processing Systems (NeurIPS 2024). `arXiv:2405.15793`.
8. **Prasad, A., Koller, A., Hartmann, M., Clark, P., Sabharwal, A., Bansal, M., & Khot, T.** (2024). *ADaPT: As-Needed Decomposition and Planning with Language Models*. In Findings of the Association for Computational Linguistics: NAACL 2024. `arXiv:2311.05772`.
9. **Nguyen, M., Baker, A., Neo, C., Roush, A., Kirsch, A., & Shwartz-Ziv, R.** (2025). *Turning Up the Heat: Min-p Sampling for Creative and Coherent LLM Outputs*. In International Conference on Learning Representations (ICLR 2025, Oral). `arXiv:2407.01082`.
10. **Zhu, Y., Li, J., Li, G., Zhao, Y., Jin, Z., & Mei, H.** (2024). *Hot or Cold? Adaptive Temperature Sampling for Code Generation with Large Language Models*. In Proceedings of the AAAI Conference on Artificial Intelligence (AAAI 2024). `arXiv:2309.02772`.
11. **Zhang, S., Bao, Y., & Huang, S.** (2024). *EDT: Improving Large Language Models' Generation by Entropy-based Dynamic Temperature Sampling*. arXiv preprint `arXiv:2403.14541`.
12. **Renze, M., & Guven, E.** (2024). *The Effect of Sampling Temperature on Problem Solving in Large Language Models*. In Findings of the Association for Computational Linguistics: EMNLP 2024. `arXiv:2402.05201`.
13. **Shinn, N., Cassano, F., Gopinath, A., Narasimhan, K., & Yao, S.** (2023). *Reflexion: Language Agents with Verbal Reinforcement Learning*. In Advances in Neural Information Processing Systems (NeurIPS 2023). `arXiv:2303.11366`.
14. **Chen, X., Lin, M., Schärli, N., & Zhou, D.** (2024). *Teaching Large Language Models to Self-Debug*. In International Conference on Learning Representations (ICLR 2024). `arXiv:2304.05128`.
15. **Si, C., Zhang, Y., Li, R., Yang, Z., Liu, R., & Yang, D.** (2025). *Design2Code: Benchmarking Multimodal Code Generation for Automated Front-End Engineering*. In Proceedings of the 2025 Conference of the Nations of the Americas Chapter of the Association for Computational Linguistics (NAACL 2025). `arXiv:2403.03163`.
16. **Zhang, C., Li, Y., Chen, J., et al.** (2025). *ArtifactsBench: Bridging the Visual-Interactive Gap in LLM Code Generation Evaluation*. arXiv preprint `arXiv:2507.04952`.
