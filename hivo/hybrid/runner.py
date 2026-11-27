"""Asymmetric Cloud Thinking Orchestrator + Local Light Worker runner over hivo.tools."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import difflib
from pathlib import Path
import time
from typing import Any, Callable, Mapping

from hivo.providers import (
    EndpointConfig,
    ModelClient,
    ModelResponse,
    ProviderError,
    TokenUsage,
    create_client,
)
from hivo.tools import (
    HookRegistry,
    PlanState,
    ToolBinding,
    ToolContext,
    ToolProfile,
    ToolSpec,
    create_tool_binding,
)
from hivo.tools.base import atomic_write_bytes, resolve_workspace_path

from .prompts import (
    build_orchestrator_system_prompt,
    build_worker_system_prompt,
    format_worker_task_prompt,
)

EventCallback = Callable[[str, dict[str, Any]], None]

_MUTATING_WORKER_TOOLS = frozenset({
    "edit_file",
    "edit_search_replace",
    "edit_unified_diff",
    "edit_line_range",
    "write_file",
    "delete_file",
})


@dataclass(frozen=True)
class HybridRunConfig:
    """Configuration for a Cloud Thinking Orchestrator + Local Light Worker run."""

    orchestrator: EndpointConfig
    worker: EndpointConfig
    orchestrator_profile: ToolProfile | None = None
    worker_profile: ToolProfile | None = None
    include_run_command: bool = True
    allowed_commands: tuple[str, ...] | None = None
    protected_paths: tuple[str, ...] = ()
    extra_orchestrator_tools: tuple[ToolSpec, ...] = ()
    orchestrator_max_read_lines: int = 200
    orchestrator_max_output_chars: int = 16_000
    max_orchestrator_turns: int = 16
    max_worker_turns: int = 6
    max_worker_dispatches: int = 6
    max_consecutive_worker_errors: int = 2
    worker_max_read_lines: int = 180
    max_history_chars: int = 20_000
    worker_max_history_chars: int = 10_000
    max_worker_diff_chars: int = 2_400
    max_elapsed_sec: float = 300.0
    auto_checkpoint_worker: bool = True
    dotenv_path: str | None = None


@dataclass(frozen=True)
class WorkerRunReport:
    """Summary of one bounded local worker invocation."""

    dispatch_index: int
    task: str
    target_files: tuple[str, ...]
    status: str
    modified_files: tuple[str, ...]
    diff_summary: str
    error: str | None
    turns: int
    tool_calls: int
    rolled_back: bool
    usage: TokenUsage
    latency_ms: float
    model: str
    unified_diff: str = ""


@dataclass(frozen=True)
class HybridRunResult:
    """Structured outcome and telemetry for one hybrid orchestrator+worker run."""

    status: str
    final_response: str
    modified_files: tuple[str, ...]
    orchestrator_model: str
    orchestrator_provider: str
    worker_model: str
    orchestrator_turns: int
    orchestrator_tool_calls: int
    orchestrator_reasoning_chars: int
    orchestrator_usage: TokenUsage
    worker_runs: tuple[WorkerRunReport, ...]
    worker_usage: TokenUsage
    plan_steps: tuple[dict[str, Any], ...]
    elapsed_ms: float
    error: str | None = None
    trace: tuple[dict[str, Any], ...] = ()


def _compact_history(
    messages: list[dict[str, Any]],
    *,
    max_chars: int,
    keep_recent: int = 4,
) -> list[dict[str, Any]]:
    """Trim bulky tool observations to enforce a hard character ceiling across turns.

    Pass 1 compacts older ``tool`` messages outside ``keep_recent``.
    Pass 2 (only if still over ``max_chars``) caps remaining bulky ``tool`` messages
    proportionally so single-request ITPM limits (e.g., Groq 7K ITPM) are never breached.
    """
    if max_chars <= 0 or len(messages) <= 2:
        return messages
    total = sum(len(str(m.get("content") or "")) for m in messages)
    if total <= max_chars:
        return messages

    compacted = [dict(m) for m in messages]
    protected_tail_start = max(2, len(compacted) - keep_recent)
    for idx in range(2, protected_tail_start):
        if total <= max_chars:
            break
        msg = compacted[idx]
        if msg.get("role") != "tool":
            continue
        content = str(msg.get("content") or "")
        if len(content) <= 220:
            continue
        tool_name = str(msg.get("name") or "tool")
        short = content[:160] + f"\n... [older {tool_name} output compacted from {len(content)} chars] ..."
        total -= len(content) - len(short)
        msg["content"] = short

    if total > max_chars:
        # Pass 2: trim remaining large tool outputs (oldest first) until strictly under max_chars.
        tool_indices = [i for i in range(2, len(compacted)) if compacted[i].get("role") == "tool"]
        for idx in tool_indices:
            if total <= max_chars:
                break
            msg = compacted[idx]
            content = str(msg.get("content") or "")
            is_tail = idx >= len(compacted) - 2
            cap = 1800 if is_tail else 500
            if len(content) <= cap:
                continue
            tool_name = str(msg.get("name") or "tool")
            head = cap // 2
            tail = max(120, cap - head - 80)
            short = (
                content[:head]
                + f"\n... [{tool_name} compacted from {len(content)} chars] ...\n"
                + content[-tail:]
            )
            total -= len(content) - len(short)
            msg["content"] = short

    return compacted


def _compute_snapshot_diff(
    target_snapshot: Mapping[Path, bytes | None],
    workspace_root: Path,
    *,
    max_chars: int = 2_400,
) -> str:
    """Compute a compact unified diff from pre-dispatch snapshot bytes vs. post-dispatch disk bytes."""
    chunks: list[str] = []
    for target_path in sorted(target_snapshot.keys(), key=lambda p: str(p)):
        orig_bytes = target_snapshot[target_path]
        curr_bytes = target_path.read_bytes() if target_path.is_file() else None
        if orig_bytes == curr_bytes:
            continue
        try:
            rel_posix = target_path.relative_to(workspace_root).as_posix()
        except ValueError:
            rel_posix = target_path.name
        before_lines = (
            orig_bytes.decode("utf-8", errors="replace").splitlines(keepends=True)
            if orig_bytes is not None
            else []
        )
        after_lines = (
            curr_bytes.decode("utf-8", errors="replace").splitlines(keepends=True)
            if curr_bytes is not None
            else []
        )
        diff_lines = list(
            difflib.unified_diff(
                before_lines,
                after_lines,
                fromfile=f"a/{rel_posix}" if orig_bytes is not None else "/dev/null",
                tofile=f"b/{rel_posix}" if curr_bytes is not None else "/dev/null",
                n=2,
            )
        )
        if diff_lines:
            chunks.append("".join(diff_lines))

    full_diff = "\n".join(chunks).strip()
    if max_chars > 0 and len(full_diff) > max_chars:
        return (
            full_diff[:max_chars].rstrip()
            + f"\n... [unified_diff truncated from {len(full_diff)} chars]"
        )
    return full_diff


class HybridAgentRunner:
    """Runs a Cloud Thinking Orchestrator paired with a fenced Local Light Worker.

    Uses ``hivo.tools.ToolBinding`` for static spawn-time tool allowlists and
    ``hivo.providers`` for provider-agnostic OpenAI-compatible + Ollama clients.
    """

    def __init__(
        self,
        workspace_root: str | Path,
        config: HybridRunConfig,
        *,
        orchestrator_client: ModelClient | None = None,
        worker_client: ModelClient | None = None,
        hooks: HookRegistry | None = None,
        user_prompter: Callable[[str, list[str]], str] | None = None,
        event_callback: EventCallback | None = None,
        scratch_dir: str | Path | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.config = config
        self.orchestrator_client = orchestrator_client or create_client(
            config.orchestrator,
            dotenv_path=config.dotenv_path,
        )
        self.worker_client = worker_client or create_client(
            config.worker,
            dotenv_path=config.dotenv_path,
        )
        self.hooks = hooks
        self.user_prompter = user_prompter
        self.event_callback = event_callback
        self.scratch_dir = Path(scratch_dir).resolve() if scratch_dir is not None else None

    def _emit(self, trace: list[dict[str, Any]], event: str, **data: Any) -> None:
        entry = {"event": event, **data}
        trace.append(entry)
        if self.event_callback is not None:
            self.event_callback(event, entry)

    def _build_orchestrator_profile(self) -> ToolProfile:
        if self.config.orchestrator_profile is not None:
            return self.config.orchestrator_profile
        return ToolProfile(
            primary_edit_tool="hashline",
            tool_protocol="native",
            max_active_tools=10,
            error_verbosity="detailed",
            model_id=self.config.orchestrator.model,
        )

    def _build_worker_profile(self) -> ToolProfile:
        if self.config.worker_profile is not None:
            return self.config.worker_profile
        return ToolProfile(
            primary_edit_tool="hashline",
            tool_protocol="native",
            max_active_tools=3,  # Keep 2B worker lean: edit_file, read_file, write_file (no search/code_intel bloat)
            error_verbosity="detailed",
            model_id=self.config.worker.model,
        )

    def run(self, task: str) -> HybridRunResult:
        """Execute ``task`` through the hybrid cloud-orchestrator + local-worker loop."""
        start = time.perf_counter()
        deadline = (
            time.monotonic() + self.config.max_elapsed_sec
            if self.config.max_elapsed_sec > 0
            else None
        )
        trace: list[dict[str, Any]] = []
        plan = PlanState()
        worker_reports: list[WorkerRunReport] = []
        worker_usage_total = TokenUsage()
        orch_usage_total = TokenUsage()
        orch_turns = 0
        orch_tool_calls = 0
        orch_reasoning_chars = 0
        all_modified: list[str] = []

        orch_binding_holder: dict[str, ToolBinding] = {}
        worker_profile = self._build_worker_profile()
        orch_profile = self._build_orchestrator_profile()

        def dispatch_worker_callback(packet: dict[str, Any]) -> dict[str, Any]:
            nonlocal worker_usage_total
            dispatch_idx = len(worker_reports) + 1
            if dispatch_idx > self.config.max_worker_dispatches:
                return {
                    "status": "failed",
                    "modified_files": [],
                    "diff_summary": "",
                    "error": f"Exceeded max_worker_dispatches ({self.config.max_worker_dispatches}).",
                }
            report = self._run_worker(
                dispatch_index=dispatch_idx,
                orch_binding=orch_binding_holder["binding"],
                packet=packet,
                worker_profile=worker_profile,
                deadline=deadline,
                trace=trace,
            )
            worker_reports.append(report)
            worker_usage_total = worker_usage_total + report.usage
            if report.status == "done":
                for rel in report.modified_files:
                    if rel not in all_modified:
                        all_modified.append(rel)
            return {
                "status": report.status,
                "modified_files": list(report.modified_files),
                "diff_summary": report.diff_summary,
                "unified_diff": report.unified_diff,
                "error": report.error,
            }

        orch_ctx = ToolContext(
            workspace_root=self.workspace_root,
            protected_paths=self.config.protected_paths,
            allowed_commands=self.config.allowed_commands,
            max_read_lines=max(20, int(self.config.orchestrator_max_read_lines)),
            max_output_chars=max(1024, int(self.config.orchestrator_max_output_chars)),
            hooks=self.hooks,
            plan_store=plan,
            worker_dispatcher=dispatch_worker_callback,
            user_prompter=self.user_prompter,
            scratch_dir=self.scratch_dir,
        )
        orch_binding = create_tool_binding(
            "orchestrator",
            context=orch_ctx,
            profile=orch_profile,
            include_run_command=self.config.include_run_command,
        )
        # Omit ask_user in non-interactive runs to save orchestrator schema tokens and avoid dead calls.
        specs = list(orch_binding.specs)
        if self.user_prompter is None:
            specs = [spec for spec in specs if spec.name != "ask_user"]
        if self.config.extra_orchestrator_tools:
            existing_names = {spec.name for spec in specs}
            for extra_spec in self.config.extra_orchestrator_tools:
                if extra_spec.name not in existing_names:
                    specs.append(extra_spec)
                    existing_names.add(extra_spec.name)
        orch_binding = replace(orch_binding, specs=tuple(specs))
        orch_binding_holder["binding"] = orch_binding
        rendered_orch = orch_binding.render_tools()
        orch_wire = self.config.orchestrator.provider_type

        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": build_orchestrator_system_prompt(
                    include_run_command=self.config.include_run_command
                ),
            },
            {"role": "user", "content": task.strip()},
        ]

        self._emit(
            trace,
            "run_started",
            orchestrator_model=self.config.orchestrator.model,
            orchestrator_provider=self.config.orchestrator.base_url,
            worker_model=self.config.worker.model,
            orchestrator_tools=[spec.name for spec in orch_binding.specs],
        )

        final_response = ""
        status = "max_turns"
        error_msg: str | None = None

        for turn in range(1, self.config.max_orchestrator_turns + 1):
            if deadline is not None and time.monotonic() >= deadline:
                status = "budget_exceeded"
                error_msg = f"Run exceeded max_elapsed_sec ({self.config.max_elapsed_sec}s)."
                break

            orch_turns = turn
            call_messages = _compact_history(
                messages,
                max_chars=self.config.max_history_chars,
                keep_recent=4,
            )
            try:
                resp = self.orchestrator_client.chat(
                    call_messages,
                    tools=rendered_orch["tools"] or None,
                    deadline_monotonic=deadline,
                )
            except ProviderError as exc:
                status = "provider_error"
                error_msg = str(exc)
                self._emit(trace, "orchestrator_provider_error", turn=turn, error=error_msg)
                break

            orch_usage_total = orch_usage_total + resp.usage
            orch_reasoning_chars += resp.reasoning_chars
            self._emit(
                trace,
                "orchestrator_turn",
                turn=turn,
                tool_calls=len(resp.tool_calls),
                content_chars=len(resp.content),
                reasoning_chars=resp.reasoning_chars,
                latency_ms=round(resp.latency_ms, 1),
            )

            messages.append(resp.to_assistant_message(wire_format=orch_wire))

            raw_output: Any = (
                {"tool_calls": list(resp.tool_calls)}
                if orch_binding.adapter.protocol == "native"
                else resp.content
            )
            executed = orch_binding.execute_response(raw_output)
            if not executed:
                final_response = resp.content
                status = "completed"
                break

            for idx, (parsed_call, envelope, observation) in enumerate(executed):
                orch_tool_calls += 1
                call_id = parsed_call.call_id or f"orch_call_{turn}_{idx + 1}"
                self._emit(
                    trace,
                    "orchestrator_tool",
                    turn=turn,
                    tool=parsed_call.name,
                    ok=bool(envelope.get("ok")),
                    error_code=envelope.get("error_code"),
                )
                if orch_binding.adapter.protocol == "native":
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": parsed_call.name or "unknown",
                        "content": observation,
                    })
                else:
                    messages.append({"role": "user", "content": observation})

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        self._emit(
            trace,
            "run_finished",
            status=status,
            orchestrator_turns=orch_turns,
            worker_dispatches=len(worker_reports),
            elapsed_ms=round(elapsed_ms, 1),
        )
        return HybridRunResult(
            status=status,
            final_response=final_response,
            modified_files=tuple(all_modified),
            orchestrator_model=self.config.orchestrator.model,
            orchestrator_provider=self.config.orchestrator.base_url,
            worker_model=self.config.worker.model,
            orchestrator_turns=orch_turns,
            orchestrator_tool_calls=orch_tool_calls,
            orchestrator_reasoning_chars=orch_reasoning_chars,
            orchestrator_usage=orch_usage_total,
            worker_runs=tuple(worker_reports),
            worker_usage=worker_usage_total,
            plan_steps=tuple(dict(s) for s in plan.steps),
            elapsed_ms=elapsed_ms,
            error=error_msg,
            trace=tuple(trace),
        )

    def _run_worker(
        self,
        *,
        dispatch_index: int,
        orch_binding: ToolBinding,
        packet: Mapping[str, Any],
        worker_profile: ToolProfile,
        deadline: float | None,
        trace: list[dict[str, Any]],
    ) -> WorkerRunReport:
        t0 = time.perf_counter()
        target_files = tuple(str(p) for p in (packet.get("target_files") or ()))
        checkpoint_id = f"worker_dispatch_{dispatch_index}"

        worker_binding = orch_binding.spawn_worker_binding(
            packet,
            worker_profile=worker_profile,
            max_read_lines=self.config.worker_max_read_lines,
        )

        # Snapshot only the fenced target_files (O(targets) instead of O(entire repo))
        # for fast atomic rollback and exact post-dispatch unified_diff computation.
        target_snapshot: dict[Path, bytes | None] = {}
        for rel_target in worker_binding.context.allowed_paths or ():
            resolved_target, _, path_err = resolve_workspace_path(
                rel_target,
                worker_binding.context,
                check_allowed=True,
                allow_root=False,
            )
            if path_err is not None or resolved_target is None:
                continue
            if resolved_target.is_file():
                target_snapshot[resolved_target] = resolved_target.read_bytes()
            elif not resolved_target.exists():
                target_snapshot[resolved_target] = None

        rendered_worker = worker_binding.render_tools()
        worker_wire = self.config.worker.provider_type

        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": build_worker_system_prompt(
                    protocol=worker_binding.adapter.protocol,
                    protocol_instructions=str(rendered_worker.get("prompt_instructions") or ""),
                ),
            },
            {"role": "user", "content": format_worker_task_prompt(packet)},
        ]

        self._emit(
            trace,
            "worker_started",
            dispatch_index=dispatch_index,
            target_files=list(target_files),
            worker_tools=[spec.name for spec in worker_binding.specs],
            protocol=worker_binding.adapter.protocol,
        )

        usage_total = TokenUsage()
        turns = 0
        tool_calls = 0
        modified: list[str] = []
        file_syntax_state: dict[str, tuple[bool, str | None]] = {}
        final_summary = ""
        worker_status = "max_turns"
        worker_error: str | None = None
        last_error_code: str | None = None
        consecutive_errors = 0
        max_consec = max(1, int(self.config.max_consecutive_worker_errors))

        for turn in range(1, self.config.max_worker_turns + 1):
            if deadline is not None and time.monotonic() >= deadline:
                worker_status = "failed"
                worker_error = "Run deadline exceeded during worker execution."
                break

            turns = turn
            use_tools = rendered_worker["tools"] or None
            use_schema = (
                rendered_worker.get("json_schema")
                if worker_binding.adapter.protocol == "grammar_json"
                else None
            )
            worker_call_messages = _compact_history(
                messages,
                max_chars=self.config.worker_max_history_chars,
                keep_recent=4,
            )
            try:
                resp = self.worker_client.chat(
                    worker_call_messages,
                    tools=use_tools,
                    response_format=use_schema,
                    think=False,  # Explicit quick win: never burn 2B tokens on hidden thinking.
                    deadline_monotonic=deadline,
                )
            except ProviderError as exc:
                worker_status = "provider_error"
                worker_error = str(exc)
                self._emit(
                    trace,
                    "worker_provider_error",
                    dispatch_index=dispatch_index,
                    turn=turn,
                    error=worker_error,
                )
                break

            usage_total = usage_total + resp.usage
            self._emit(
                trace,
                "worker_turn",
                dispatch_index=dispatch_index,
                turn=turn,
                tool_calls=len(resp.tool_calls),
                content_chars=len(resp.content),
                latency_ms=round(resp.latency_ms, 1),
            )

            messages.append(resp.to_assistant_message(wire_format=worker_wire))

            raw_output: Any = (
                {"tool_calls": list(resp.tool_calls)}
                if worker_binding.adapter.protocol == "native"
                else resp.content
            )
            executed = worker_binding.execute_response(raw_output)
            if not executed:
                final_summary = resp.content.strip()
                worker_status = "done"
                break

            for idx, (parsed_call, envelope, observation) in enumerate(executed):
                tool_calls += 1
                call_id = parsed_call.call_id or f"worker_call_{dispatch_index}_{turn}_{idx + 1}"
                self._emit(
                    trace,
                    "worker_tool",
                    dispatch_index=dispatch_index,
                    turn=turn,
                    tool=parsed_call.name,
                    ok=bool(envelope.get("ok")),
                    error_code=envelope.get("error_code"),
                )
                if parsed_call.name in _MUTATING_WORKER_TOOLS and envelope.get("ok"):
                    data = envelope.get("data") or {}
                    rel_path = str(data.get("path") or "")
                    if rel_path:
                        if rel_path not in modified:
                            modified.append(rel_path)
                        if "syntax_ok" in data:
                            file_syntax_state[rel_path] = (
                                bool(data.get("syntax_ok")),
                                data.get("syntax_error"),
                            )
                        elif parsed_call.name == "delete_file":
                            file_syntax_state.pop(rel_path, None)

                if worker_binding.adapter.protocol == "native":
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": parsed_call.name or "unknown",
                        "content": observation,
                    })
                else:
                    messages.append({"role": "user", "content": observation})

                if not envelope.get("ok"):
                    err_code = str(envelope.get("error_code") or "TOOL_ERROR")
                    if err_code == last_error_code:
                        consecutive_errors += 1
                    else:
                        last_error_code = err_code
                        consecutive_errors = 1
                else:
                    last_error_code = None
                    consecutive_errors = 0

            if consecutive_errors >= max_consec and last_error_code is not None:
                worker_status = "failed"
                worker_error = (
                    f"Worker aborted early after {consecutive_errors} consecutive "
                    f"{last_error_code} tool errors."
                )
                self._emit(
                    trace,
                    "worker_repeated_error_abort",
                    dispatch_index=dispatch_index,
                    turn=turn,
                    error_code=last_error_code,
                    consecutive_errors=consecutive_errors,
                )
                break

        broken_files = [
            f"{path} ({err or 'syntax error'})"
            for path, (is_ok, err) in file_syntax_state.items()
            if not is_ok
        ]
        if broken_files:
            worker_status = "failed"
            worker_error = "Worker left broken syntax in: " + "; ".join(broken_files)
        elif worker_status == "max_turns":
            worker_error = f"Worker reached max_worker_turns ({self.config.max_worker_turns}) without finishing."

        rolled_back = False
        if worker_status != "done" and self.config.auto_checkpoint_worker and target_snapshot:
            rollback_ok = True
            for target_path, orig_bytes in target_snapshot.items():
                try:
                    if orig_bytes is None:
                        if target_path.is_file():
                            target_path.unlink()
                    else:
                        atomic_write_bytes(target_path, orig_bytes)
                except OSError:
                    rollback_ok = False
            rolled_back = rollback_ok
            if rolled_back:
                modified = []
            self._emit(
                trace,
                "worker_rollback",
                dispatch_index=dispatch_index,
                checkpoint_id=checkpoint_id,
                rolled_back=rolled_back,
            )

        unified_diff = (
            _compute_snapshot_diff(
                target_snapshot,
                self.workspace_root,
                max_chars=self.config.max_worker_diff_chars,
            )
            if worker_status == "done" and not rolled_back and target_snapshot
            else ""
        )

        latency_ms = (time.perf_counter() - t0) * 1000.0
        self._emit(
            trace,
            "worker_finished",
            dispatch_index=dispatch_index,
            status=worker_status,
            modified_files=modified,
            rolled_back=rolled_back,
            diff_chars=len(unified_diff),
            turns=turns,
            latency_ms=round(latency_ms, 1),
        )
        return WorkerRunReport(
            dispatch_index=dispatch_index,
            task=str(packet.get("task", "")),
            target_files=target_files,
            status=worker_status,
            modified_files=tuple(modified),
            diff_summary=final_summary or (f"Updated {', '.join(modified)}" if modified else ""),
            error=worker_error,
            turns=turns,
            tool_calls=tool_calls,
            rolled_back=rolled_back,
            usage=usage_total,
            latency_ms=latency_ms,
            model=self.config.worker.model,
            unified_diff=unified_diff,
        )
