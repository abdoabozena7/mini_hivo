import copy
import json
from pathlib import Path
import sys


sys.path.insert(0, r"D:\projects\Ai\mini_hivo")
import mini


capture_path = Path(sys.argv[1])
force_builder_thinking = "--thinking-builder" in sys.argv[2:]
explain_locked_tools = "--explain-locked-tools" in sys.argv[2:]
sys.argv = ["mini.py", *(arg for arg in sys.argv[2:] if arg not in {
    "--thinking-builder", "--explain-locked-tools",
})]
original = mini.ask_ollama


def observe(messages, tools=None, role="Builder", **kwargs):
    if role == "Builder" and force_builder_thinking:
        kwargs["think"] = True
    if role == "Builder" and explain_locked_tools and mini.RUN.get("project_mode") == mini.NEW_PROJECT:
        tools = copy.deepcopy(tools)
        for definition in tools or []:
            if definition["function"]["name"] == "context_sufficiency_check":
                definition["function"]["description"] += (
                    " In a new project, the explicit creation requirements are the authoritative contract. "
                    "This check reports missing project-specific information, not unfinished implementation work. "
                    "The runtime temporarily hides write_file, edit_file, and edit_file_range until a sufficient "
                    "decision; those tools become available afterward. If the creation task is fully specified, "
                    "mark sufficient even when no source files exist yet. Do not request a future output file, "
                    "a write capability, or general programming knowledge as repository evidence."
                )
    response = original(messages, tools=tools, role=role, **kwargs)
    if role == "Builder":
        capture_path.parent.mkdir(parents=True, exist_ok=True)
        with capture_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({
                "role": role,
                "messages": messages,
                "tools": tools,
                "response": response,
            }, ensure_ascii=False) + "\n")
    return response


mini.ask_ollama = observe
mini.main()
