"""3-mode tool serialization and response parsing adapter."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Literal, Mapping, Sequence

from .base import ERR_TOOL_SCHEMA, ToolContext, ToolSpec, err_result, format_tool_observation
from .registry import execute_tool, export_native_tools

_TOOL_CALL_TAG_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


@dataclass(frozen=True)
class ParsedToolCall:
    """Normalized tool call proposal parsed from any model output format."""

    name: str
    arguments: Any
    call_id: str = ""
    parse_error: str | None = None


def build_grammar_json_schema(specs: Sequence[ToolSpec]) -> dict[str, Any]:
    """Build a strict JSON Schema constraining a response to one active tool call."""
    variants = []
    for spec in specs:
        variants.append({
            "type": "object",
            "properties": {
                "tool": {"type": "string", "const": spec.name},
                "arguments": spec.parameters,
            },
            "required": ["tool", "arguments"],
            "additionalProperties": False,
        })
    return {"type": "object", "oneOf": variants}


def _gbnf_escape_key(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _gbnf_value_rule(
    schema: Mapping[str, Any],
    rule_prefix: str,
    extra_rules: list[str],
) -> str:
    enum_vals = schema.get("enum")
    if isinstance(enum_vals, list) and enum_vals:
        alts: list[str] = []
        for item in enum_vals:
            if isinstance(item, str):
                alts.append(f'"\\"{_gbnf_escape_key(item)}\\""')
            elif isinstance(item, bool):
                alts.append('"true"' if item else '"false"')
            elif isinstance(item, (int, float)):
                alts.append(f'"{item}"')
        if alts:
            enum_rule = f"{rule_prefix}_enum"
            extra_rules.append(f"{enum_rule} ::= ( {' | '.join(alts)} ) ws")
            return enum_rule

    expected_type = schema.get("type")
    if expected_type == "string":
        return "string"
    if expected_type == "integer":
        return "integer"
    if expected_type == "number":
        return "number"
    if expected_type == "boolean":
        return "boolean"
    if expected_type == "array":
        items = schema.get("items")
        if isinstance(items, Mapping):
            item_rule = _gbnf_value_rule(items, f"{rule_prefix}_item", extra_rules)
            arr_rule = f"{rule_prefix}_arr"
            extra_rules.append(f'{arr_rule} ::= "[" ws ( {item_rule} ( "," ws {item_rule} )* )? ws "]"')
            return arr_rule
        return "array"
    if expected_type == "object":
        props = schema.get("properties")
        if isinstance(props, Mapping) and props:
            obj_rule = f"{rule_prefix}_obj"
            _emit_object_rule(obj_rule, schema, extra_rules)
            return obj_rule
        return "object"
    return "value"


def _emit_object_rule(
    rule_name: str,
    obj_schema: Mapping[str, Any],
    extra_rules: list[str],
) -> None:
    props = obj_schema.get("properties")
    if not isinstance(props, Mapping) or not props:
        extra_rules.append(f'{rule_name} ::= "{{" ws "}}"')
        return

    req_list = [str(k) for k in (obj_schema.get("required") or []) if k in props]
    req_set = set(req_list)
    opt_list = [str(k) for k in props if k not in req_set]
    ordered_keys = req_list + opt_list

    for pos, key in enumerate(ordered_keys):
        prop_schema = props[key]
        val_rule = (
            _gbnf_value_rule(prop_schema, f"{rule_name}_p{pos}", extra_rules)
            if isinstance(prop_schema, Mapping)
            else "value"
        )
        escaped_key = _gbnf_escape_key(key)
        extra_rules.append(f'{rule_name}_kv{pos} ::= "\\"{escaped_key}\\":" ws {val_rule}')

    if opt_list:
        opt_indices = list(range(len(req_list), len(ordered_keys)))
        for idx_in_opt in range(len(opt_indices) - 1, -1, -1):
            kv_idx = opt_indices[idx_in_opt]
            opt_rule = f"{rule_name}_opt{idx_in_opt}"
            if idx_in_opt == len(opt_indices) - 1:
                extra_rules.append(f"{opt_rule} ::= {rule_name}_kv{kv_idx}")
            else:
                next_opt = f"{rule_name}_opt{idx_in_opt + 1}"
                extra_rules.append(
                    f'{opt_rule} ::= {rule_name}_kv{kv_idx} ( "," ws {next_opt} )? | {next_opt}'
                )

    if req_list:
        req_seq = ' "," ws '.join(f"{rule_name}_kv{i}" for i in range(len(req_list)))
        opt_tail = f' ( "," ws {rule_name}_opt0 )?' if opt_list else ""
        extra_rules.append(f'{rule_name} ::= "{{" ws {req_seq}{opt_tail} ws "}}"')
    else:
        extra_rules.append(f'{rule_name} ::= "{{" ws ( {rule_name}_opt0 )? ws "}}"')


def build_gbnf_grammar(specs: Sequence[ToolSpec]) -> str:
    """Build a llama.cpp-compatible GBNF grammar constraining JSON tool calls and exact parameter schemas."""
    if not specs:
        return 'root ::= "{}"\n'
    tool_alts: list[str] = []
    rule_defs: list[str] = []
    for idx, spec in enumerate(specs):
        rule_name = f"call_{idx}"
        tool_alts.append(rule_name)
        args_rule = f"args_{idx}"
        escaped_tool = _gbnf_escape_key(spec.name)
        rule_defs.append(
            f'{rule_name} ::= "{{" ws "\\"tool\\":" ws "\\"{escaped_tool}\\"," ws "\\"arguments\\":" ws {args_rule} ws "}}"'
        )
        _emit_object_rule(args_rule, spec.parameters, rule_defs)

    lines = [
        f"root ::= {' | '.join(tool_alts)}",
        *rule_defs,
        'object ::= "{" ws ( pair ( "," ws pair )* )? ws "}"',
        'pair ::= string ":" ws value',
        'value ::= object | array | string | number | boolean | "null" ws',
        'array ::= "[" ws ( value ( "," ws value )* )? ws "]"',
        'string ::= "\\"" ( [^"\\\\\\x7F\\x00-\\x1F] | "\\\\" (["\\\\bfnrt/] | "u" [0-9a-fA-F]{4}) )* "\\"" ws',
        'integer ::= "-"? ([0-9] | [1-9] [0-9]*) ws',
        'number ::= ("-"? ([0-9] | [1-9] [0-9]*)) ("." [0-9]+)? ([eE] [-+]? [0-9]+)? ws',
        'boolean ::= ("true" | "false") ws',
        "ws ::= [ \\t\\n\\r]*",
    ]
    return "\n".join(lines) + "\n"


def _render_xml_instructions(specs: Sequence[ToolSpec]) -> str:
    lines = ["<tools>"]
    for spec in specs:
        params_json = json.dumps(spec.parameters, ensure_ascii=False, sort_keys=True)
        lines.append(f'  <tool name="{spec.name}">')
        lines.append(f"    <description>{spec.description}</description>")
        lines.append(f"    <parameters>{params_json}</parameters>")
        lines.append("  </tool>")
    lines.append("</tools>")
    lines.append('Emit each tool call wrapped in <tool_call>{"name": "<tool>", "arguments": {...}}</tool_call>.')
    return "\n".join(lines)


class ToolProtocolAdapter:
    """Adapter decoupling tool presentation/parsing from underlying tool execution."""

    def __init__(self, protocol: Literal["native", "grammar_json", "xml_tags"] = "native") -> None:
        if protocol not in {"native", "grammar_json", "xml_tags"}:
            raise ValueError(f"Unsupported tool protocol {protocol!r}")
        self.protocol = protocol

    def render_tools(self, specs: Sequence[ToolSpec]) -> dict[str, Any]:
        if self.protocol == "native":
            return {
                "protocol": "native",
                "tools": export_native_tools(specs),
                "prompt_instructions": "",
                "grammar": None,
                "json_schema": None,
            }
        if self.protocol == "grammar_json":
            schema = build_grammar_json_schema(specs)
            grammar = build_gbnf_grammar(specs)
            return {
                "protocol": "grammar_json",
                "tools": [],
                "prompt_instructions": 'Respond with a JSON object matching {"tool": "<name>", "arguments": {...}}.',
                "grammar": grammar,
                "json_schema": schema,
            }
        return {
            "protocol": "xml_tags",
            "tools": [],
            "prompt_instructions": _render_xml_instructions(specs),
            "grammar": None,
            "json_schema": None,
        }

    def parse_response(self, raw_output: Any) -> list[ParsedToolCall]:
        if self.protocol == "native":
            return self._parse_native(raw_output)
        if self.protocol == "grammar_json":
            return self._parse_grammar_json(raw_output)
        return self._parse_xml_tags(raw_output)

    @staticmethod
    def _parse_native(raw_output: Any) -> list[ParsedToolCall]:
        if isinstance(raw_output, dict) and "tool_calls" in raw_output:
            items = raw_output.get("tool_calls") or []
        elif isinstance(raw_output, list):
            items = raw_output
        elif isinstance(raw_output, dict) and ("function" in raw_output or "name" in raw_output):
            items = [raw_output]
        else:
            return []

        calls: list[ParsedToolCall] = []
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                calls.append(ParsedToolCall(name="", arguments={}, parse_error=f"tool_calls[{idx}] must be an object"))
                continue
            call_id = str(item.get("id") or "")
            fn = item.get("function") if isinstance(item.get("function"), dict) else item
            name = str(fn.get("name") or "")
            raw_args = fn.get("arguments", {})
            if isinstance(raw_args, str):
                try:
                    parsed_args = json.loads(raw_args) if raw_args.strip() else {}
                except json.JSONDecodeError as exc:
                    calls.append(
                        ParsedToolCall(
                            name=name,
                            arguments=raw_args,
                            call_id=call_id,
                            parse_error=f"Invalid JSON arguments for '{name}': {exc}",
                        )
                    )
                    continue
            else:
                parsed_args = raw_args
            calls.append(ParsedToolCall(name=name, arguments=parsed_args, call_id=call_id))
        return calls

    @staticmethod
    def _parse_grammar_json(raw_output: Any) -> list[ParsedToolCall]:
        if isinstance(raw_output, (dict, list)):
            obj = raw_output
        elif isinstance(raw_output, str):
            text = raw_output.strip()
            if not text:
                return []
            fence = _CODE_FENCE_RE.match(text)
            if fence:
                text = fence.group(1).strip()
            try:
                obj = json.loads(text)
            except json.JSONDecodeError as exc:
                return [ParsedToolCall(name="", arguments={}, parse_error=f"Invalid JSON payload: {exc}")]
        else:
            return [ParsedToolCall(name="", arguments={}, parse_error="Expected JSON string, dict, or list")]

        if isinstance(obj, list):
            calls: list[ParsedToolCall] = []
            for idx, item in enumerate(obj):
                if not isinstance(item, dict):
                    calls.append(
                        ParsedToolCall(
                            name="",
                            arguments={},
                            parse_error=f"Grammar JSON array[{idx}] must be an object",
                        )
                    )
                    continue
                name = item.get("tool") if "tool" in item else item.get("name")
                if not isinstance(name, str) or not name.strip():
                    calls.append(
                        ParsedToolCall(
                            name="",
                            arguments={},
                            parse_error=f"Missing string 'tool' field in JSON object at index {idx}",
                        )
                    )
                    continue
                calls.append(ParsedToolCall(name=name.strip(), arguments=item.get("arguments", {})))
            return calls

        if not isinstance(obj, dict):
            return [ParsedToolCall(name="", arguments={}, parse_error="Grammar JSON root must be an object or array")]
        name = obj.get("tool") if "tool" in obj else obj.get("name")
        if not isinstance(name, str) or not name.strip():
            return [ParsedToolCall(name="", arguments={}, parse_error="Missing string 'tool' field in JSON object")]
        return [ParsedToolCall(name=name.strip(), arguments=obj.get("arguments", {}))]

    @staticmethod
    def _parse_xml_tags(raw_output: Any) -> list[ParsedToolCall]:
        if not isinstance(raw_output, str):
            return []
        calls: list[ParsedToolCall] = []
        for match in _TOOL_CALL_TAG_RE.finditer(raw_output):
            inner = match.group(1).strip()
            try:
                obj = json.loads(inner)
            except json.JSONDecodeError as exc:
                calls.append(ParsedToolCall(name="", arguments={}, parse_error=f"Malformed JSON in <tool_call>: {exc}"))
                continue
            if not isinstance(obj, dict):
                calls.append(ParsedToolCall(name="", arguments={}, parse_error="<tool_call> body must be a JSON object"))
                continue
            name = obj.get("name") if "name" in obj else obj.get("tool")
            if not isinstance(name, str) or not name.strip():
                calls.append(ParsedToolCall(name="", arguments={}, parse_error="<tool_call> missing string 'name'"))
                continue
            calls.append(ParsedToolCall(name=name.strip(), arguments=obj.get("arguments", {})))
        return calls

    def execute_parsed_call(
        self,
        call: ParsedToolCall,
        ctx: ToolContext,
        *,
        allowed_specs: Sequence[ToolSpec] | None = None,
    ) -> dict[str, Any]:
        if call.parse_error:
            return err_result(
                f"Malformed tool call: {call.parse_error}.",
                error_code=ERR_TOOL_SCHEMA,
                hint="Emit valid JSON matching the active tool protocol and parameter schema.",
            )
        return execute_tool(call.name, call.arguments, ctx, allowed_specs=allowed_specs)

    def execute_and_format(
        self,
        call: ParsedToolCall,
        ctx: ToolContext,
        *,
        allowed_specs: Sequence[ToolSpec] | None = None,
        wrap_untrusted: bool = True,
        error_verbosity: str = "detailed",
    ) -> tuple[dict[str, Any], str]:
        """Execute a parsed tool call and format its envelope for model observation."""
        envelope = self.execute_parsed_call(call, ctx, allowed_specs=allowed_specs)
        observation = format_tool_observation(
            call.name or "<malformed>",
            envelope,
            error_verbosity=error_verbosity,
            wrap_untrusted=wrap_untrusted,
        )
        return envelope, observation
