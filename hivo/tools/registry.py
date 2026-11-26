"""Declarative allowlist registry, role profiles, schema export, and tool dispatcher."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, Mapping, Sequence

from .base import (
    ERR_TOOL_SCHEMA,
    ToolContext,
    ToolSpec,
    err_result,
    format_tool_observation,
    validate_and_prepare_args,
)
from .checkpoint_tool import CHECKPOINT_SPEC
from .code_intel import CODE_INTEL_SPEC
from .edit_strategies import (
    EDIT_LINE_RANGE_SPEC,
    EDIT_SEARCH_REPLACE_SPEC,
    EDIT_STRATEGY_SPECS,
    EDIT_UNIFIED_DIFF_SPEC,
)
from .exec_tool import RUN_COMMAND_SPEC
from .fs_read import LIST_FILES_SPEC, READ_FILE_SPEC, SEARCH_CODE_SPEC
from .fs_write import DELETE_FILE_SPEC, EDIT_FILE_SPEC, WRITE_FILE_SPEC
from .orchestration import ASK_USER_SPEC, DISPATCH_WORKER_SPEC, UPDATE_PLAN_SPEC
from .profile import ToolProfile, compute_tool_schema_hash

if TYPE_CHECKING:
    from .protocol import ParsedToolCall, ToolProtocolAdapter

_ALL_SPECS: tuple[ToolSpec, ...] = (
    READ_FILE_SPEC,
    LIST_FILES_SPEC,
    SEARCH_CODE_SPEC,
    CODE_INTEL_SPEC,
    EDIT_FILE_SPEC,
    EDIT_SEARCH_REPLACE_SPEC,
    EDIT_UNIFIED_DIFF_SPEC,
    EDIT_LINE_RANGE_SPEC,
    WRITE_FILE_SPEC,
    DELETE_FILE_SPEC,
    RUN_COMMAND_SPEC,
    CHECKPOINT_SPEC,
    DISPATCH_WORKER_SPEC,
    UPDATE_PLAN_SPEC,
    ASK_USER_SPEC,
)

ALL_TOOLS: Mapping[str, ToolSpec] = MappingProxyType({spec.name: spec for spec in _ALL_SPECS})
CORE_TOOLS: Mapping[str, ToolSpec] = ALL_TOOLS

ROLE_PROFILES: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "orchestrator": (
        "read_file",
        "list_files",
        "search_code",
        "code_intel",
        "checkpoint",
        "update_plan",
        "dispatch_worker",
        "ask_user",
    ),
    "coder_worker": (
        "read_file",
        "edit_file",
        "write_file",
        "code_intel",
    ),
    "research_worker": (
        "read_file",
        "list_files",
        "search_code",
        "code_intel",
    ),
    "verifier": (
        "read_file",
        "code_intel",
        "run_command",
    ),
})


def build_profile_tools(
    profile: str,
    *,
    allow_delete: bool = False,
    include_run_command: bool = False,
    model_profile: Any | None = None,
) -> tuple[ToolSpec, ...]:
    """Build a static, strict allowlist tuple of ToolSpecs for a role profile."""
    if profile not in ROLE_PROFILES:
        raise ValueError(f"Unknown tool profile {profile!r}; expected one of {sorted(ROLE_PROFILES)}.")

    if profile == "coder_worker" and model_profile is not None:
        primary_key = getattr(model_profile, "primary_edit_tool", "hashline")
        if primary_key not in EDIT_STRATEGY_SPECS:
            raise ValueError(f"Unknown primary_edit_tool {primary_key!r}")
        primary_spec = EDIT_STRATEGY_SPECS[primary_key]
        ordered: list[ToolSpec] = [primary_spec, ALL_TOOLS["read_file"]]
        if primary_spec.name != "write_file":
            ordered.append(ALL_TOOLS["write_file"])
        ordered.append(ALL_TOOLS["code_intel"])

        fallback_key = getattr(model_profile, "fallback_edit_tool", None)
        if fallback_key is not None:
            if fallback_key not in EDIT_STRATEGY_SPECS:
                raise ValueError(f"Unknown fallback_edit_tool {fallback_key!r}")
            fb_spec = EDIT_STRATEGY_SPECS[fallback_key]
            if fb_spec not in ordered:
                ordered.append(fb_spec)
        if allow_delete:
            ordered.append(ALL_TOOLS["delete_file"])
        cap = max(1, int(getattr(model_profile, "max_active_tools", len(ordered))))
        specs = tuple(ordered[:cap])
    else:
        names = list(ROLE_PROFILES[profile])
        if profile == "coder_worker" and allow_delete and "delete_file" not in names:
            names.append("delete_file")
        if profile == "orchestrator" and include_run_command and "run_command" not in names:
            names.append("run_command")
        specs = tuple(ALL_TOOLS[name] for name in names)
        if model_profile is not None:
            cap = max(1, int(getattr(model_profile, "max_active_tools", len(specs))))
            specs = specs[:cap]

    if profile == "coder_worker":
        for spec in specs:
            if spec.model_tier != "slm_safe":
                raise AssertionError(f"Profile 'coder_worker' may only contain slm_safe tools, found {spec.name!r}.")
    elif profile == "research_worker":
        for spec in specs:
            if spec.effect != "read":
                raise AssertionError(f"Profile 'research_worker' may only contain read tools, found {spec.name!r}.")
    elif profile == "verifier":
        for spec in specs:
            if spec.effect == "write":
                raise AssertionError(f"Profile 'verifier' may not contain write tools, found {spec.name!r}.")

    return specs


def export_native_tools(specs: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    """Export ``ToolSpec`` entries as OpenAI-compatible function-calling schemas."""
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        }
        for spec in specs
    ]


def serialize_native_tools(specs: Sequence[ToolSpec]) -> str:
    """Deterministically serialize exported native tool schemas (KV-cache friendly)."""
    return json.dumps(export_native_tools(specs), ensure_ascii=False, sort_keys=True)


# Backwards-compatible aliases from v0.3
export_openai_tools = export_native_tools
serialize_openai_tools = serialize_native_tools


def execute_tool(
    name: str,
    raw_args: Any,
    ctx: ToolContext,
    *,
    allowed_specs: Sequence[ToolSpec] | None = None,
) -> dict[str, Any]:
    """Validate permissions, arguments, and pre-tool hooks, then invoke a tool unit safely."""
    if allowed_specs is not None:
        allowed_map = {spec.name: spec for spec in allowed_specs}
        if name not in allowed_map:
            return err_result(
                f"Tool '{name}' is not enabled for this agent profile.",
                error_code=ERR_TOOL_SCHEMA,
                hint=f"Available tools for this profile: {sorted(allowed_map)}.",
            )
        spec = allowed_map[name]
    else:
        spec = ALL_TOOLS.get(name)
        if spec is None:
            return err_result(
                f"Unknown tool '{name}'.",
                error_code=ERR_TOOL_SCHEMA,
                hint=f"Available tools: {sorted(ALL_TOOLS)}.",
            )

    prepared, arg_err = validate_and_prepare_args(spec, raw_args)
    if arg_err is not None or prepared is None:
        return arg_err  # type: ignore[return-value]

    if ctx.hooks is not None and hasattr(ctx.hooks, "run_pre_tool"):
        blocked = ctx.hooks.run_pre_tool(name, prepared, ctx)
        if blocked is not None:
            return blocked

    try:
        return spec.handler(prepared, ctx)
    except Exception as exc:  # pragma: no cover - defensive boundary
        return err_result(
            f"Tool '{name}' failed unexpectedly ({type(exc).__name__}: {exc}).",
            hint="Verify your arguments and retry.",
        )


@dataclass(frozen=True)
class ToolBinding:
    """Spawn-time static tool binding tying role allowlist, ToolContext, ToolProtocolAdapter, and ToolProfile."""

    role: str
    specs: tuple[ToolSpec, ...]
    context: ToolContext
    adapter: ToolProtocolAdapter
    profile: ToolProfile | None = None

    def render_tools(self) -> dict[str, Any]:
        return self.adapter.render_tools(self.specs)

    def schema_hash(self) -> str:
        return compute_tool_schema_hash(self.specs)

    def execute_call(
        self,
        name: str,
        raw_args: Any,
        *,
        wrap_untrusted: bool = True,
    ) -> tuple[dict[str, Any], str]:
        envelope = execute_tool(name, raw_args, self.context, allowed_specs=self.specs)
        verbosity = self.profile.error_verbosity if self.profile is not None else "detailed"
        observation = format_tool_observation(
            name or "<unknown>",
            envelope,
            error_verbosity=verbosity,
            wrap_untrusted=wrap_untrusted,
        )
        return envelope, observation

    def execute_response(
        self,
        raw_output: Any,
        *,
        wrap_untrusted: bool = True,
    ) -> list[tuple[ParsedToolCall, dict[str, Any], str]]:
        calls = self.adapter.parse_response(raw_output)
        verbosity = self.profile.error_verbosity if self.profile is not None else "detailed"
        results: list[tuple[ParsedToolCall, dict[str, Any], str]] = []
        for call in calls:
            envelope, observation = self.adapter.execute_and_format(
                call,
                self.context,
                allowed_specs=self.specs,
                wrap_untrusted=wrap_untrusted,
                error_verbosity=verbosity,
            )
            results.append((call, envelope, observation))
        return results

    def spawn_worker_binding(
        self,
        packet: Mapping[str, Any],
        *,
        worker_profile: ToolProfile | None = None,
        max_read_lines: int = 180,
    ) -> ToolBinding:
        """Create a fenced ``coder_worker`` ToolBinding from a ``dispatch_worker`` packet."""
        raw_targets = packet.get("target_files") or []
        if not isinstance(raw_targets, (list, tuple)):
            raise ValueError("packet['target_files'] must be a sequence of relative paths.")
        norm_targets = tuple(
            str(p).strip().replace("\\", "/").lstrip("./")
            for p in raw_targets
            if str(p).strip()
        )
        worker_ctx = replace(
            self.context,
            allowed_paths=norm_targets,
            max_read_lines=min(self.context.max_read_lines, max(1, int(max_read_lines))),
            error_verbosity=(
                worker_profile.error_verbosity
                if worker_profile is not None
                else self.context.error_verbosity
            ),
            allowed_commands=(),
            plan_store=None,
            worker_dispatcher=None,
            user_prompter=None,
        )
        return create_tool_binding(
            "coder_worker",
            context=worker_ctx,
            profile=worker_profile,
            allow_delete=bool(packet.get("allow_delete", False)),
        )


def create_tool_binding(
    role: str,
    *,
    context: ToolContext,
    profile: ToolProfile | None = None,
    protocol: Literal["native", "grammar_json", "xml_tags"] | None = None,
    allow_delete: bool = False,
    include_run_command: bool = False,
) -> ToolBinding:
    """Assemble a static spawn-time ToolBinding for an agent role."""
    from .protocol import ToolProtocolAdapter

    specs = build_profile_tools(
        role,
        allow_delete=allow_delete,
        include_run_command=include_run_command,
        model_profile=profile,
    )
    effective_protocol = protocol or (profile.tool_protocol if profile is not None else "native")
    adapter = ToolProtocolAdapter(effective_protocol)
    return ToolBinding(
        role=role,
        specs=specs,
        context=context,
        adapter=adapter,
        profile=profile,
    )
