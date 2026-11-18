#!/usr/bin/env python3
"""Install Prove It without replacing existing agent instructions or hooks.

No dependencies are downloaded, no sandbox permissions are changed, and no
repository is committed/pushed. Review this script before enabling a hook.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
from pathlib import Path
import shlex
import shutil
import sys

SOURCE = Path(__file__).resolve().parents[1]
START = "<!-- prove-it:begin -->"
END = "<!-- prove-it:end -->"


def ps_quote(text):
    return "'" + str(text).replace("'", "''") + "'"


def backup(path):
    if path.exists():
        dest = path.with_name(path.name + ".backup-" + dt.datetime.now().strftime("%Y%m%d%H%M%S%f"))
        shutil.copy2(path, dest)
        return str(dest)
    return None


def instruction_block(skill_path):
    return f'''{START}
## Runtime evidence before completion
For implementation, bug-fix, UI, simulation, API, CLI, or agent-workflow tasks,
load the `prove-it` skill at `{skill_path.as_posix()}/SKILL.md` before changing code.
Before implementation, create/resume a dependency-aware plan and durable TODO
list. Choose serial steps or real subagents according to available tools, write
ownership and dependencies. Never invent delegation. Require an integration task;
IMPLEMENTED is not VERIFIED. Use the bundled step tracker and current evidence
before closing each item. Create/activate the task in `.runtime-proof/`; use actual
browser/terminal/native tools, not text claims. Keep the contract proportional
to the task, cover every requested behavior, and use meaningful unit tests as
supporting evidence rather than a substitute for runtime acceptance.
Run the bundled `scripts/proof.py verify --task <task-directory> --write-report`
before claiming completion. Inspect the captured evidence. Report VERIFIED only
within the checked scope; otherwise report PARTIAL, BLOCKED_UNVERIFIED, or FAILED.
Do not alter the harness, receipts, acceptance thresholds or scope merely to pass.
Do not deactivate the task/hook to avoid a failed gate. Preserve all user safety,
privacy, spending, simulator and research restrictions. A skill grants no tool
permission and does not override system or organization policies.
{END}
'''


def merge_block(existing, block):
    if START in existing:
        if END not in existing: raise ValueError("Malformed existing prove-it instruction block")
        before, rest = existing.split(START, 1)
        _, after = rest.split(END, 1)
        return before.rstrip() + "\n\n" + block + after.lstrip("\r\n")
    return existing.rstrip() + ("\n\n" if existing.strip() else "") + block


def install(agent, scope, project, home, with_hook=False, instructions=False, update=False, dry_run=False):
    if (with_hook or instructions) and project is None:
        raise ValueError("--project is required for repository hooks/instructions, even with a personal skill")
    if scope == "project" and project is None: raise ValueError("Project scope needs --project")
    if with_hook and agent not in {"copilot", "claude"}:
        raise ValueError("No unverified host-specific stop hook is supplied for this agent; use proof.py verify externally")
    root = home if scope == "user" else project
    location = {"copilot": ".copilot/skills" if scope == "user" else ".github/skills",
                "codex": ".agents/skills", "claude": ".claude/skills", "generic": ".agents/skills"}[agent]
    dest = root / location / "prove-it"
    if dest.exists() and dest.resolve() != SOURCE and not update:
        raise ValueError(f"Skill already exists: {dest}. Review it; pass --update for a backed-up replacement")
    script = dest / "scripts" / "proof.py"
    operations = [f"Install skill at {dest}"]
    files = {}
    if instructions:
        filename = {"copilot": ".github/copilot-instructions.md", "codex": "AGENTS.md",
                    "claude": "CLAUDE.md", "generic": "AGENTS.md"}[agent]
        path = project / filename
        existing = path.read_text(encoding="utf-8-sig") if path.exists() else ""
        files[path] = merge_block(existing, instruction_block(dest))
    if with_hook:
        argv = [sys.executable, str(script), "hook", "--host", agent]
        if agent == "copilot":
            path = project / ".github" / "hooks" / "prove-it.json"
            if path.exists() and not update: raise ValueError(f"Hook exists: {path}; use --update after review")
            # Native bash/powershell keys are documented by GitHub; no shell policy bypass.
            config = {"version": 1, "hooks": {"agentStop": [{"type": "command",
                "bash": shlex.join(argv), "powershell": "& " + " ".join(ps_quote(x) for x in argv), "timeoutSec": 120}]}}
        else:
            path = project / ".claude" / "settings.local.json"
            config = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
            hook_map = config.setdefault("hooks", {})
            entries = hook_map.setdefault("Stop", [])
            if not isinstance(entries, list): raise ValueError("Existing Stop hooks are not a list")
            # Claude command hooks use the host's command shell; forward slashes work
            # with Git Bash on Windows and with POSIX shells on Linux/macOS.
            cmd = " ".join(shlex.quote(str(x).replace("\\", "/")) for x in argv)
            new_entry = {"hooks": [{"type": "command", "command": cmd, "timeout": 120}]}
            if new_entry not in entries: entries.append(new_entry)
        files[path] = json.dumps(config, indent=2) + "\n"
    for path in files: operations.append(f"Merge/write {path} (backup existing file)")
    if project:
        ignore = project / ".gitignore"
        content = ignore.read_text(encoding="utf-8-sig") if ignore.exists() else ""
        if "/.runtime-proof/" not in content.splitlines():
            files[ignore] = content.rstrip() + "\n\n# Local runtime evidence can contain private data and large recordings.\n/.runtime-proof/\n"
            operations.append(f"Append evidence exclusion to {ignore}")
    if dry_run: return {"dry_run": True, "operations": operations}
    if dest.resolve() != SOURCE:
        if dest.exists():
            archive_dir = home / ".prove-it-backups"
            archive_dir.mkdir(parents=True, exist_ok=True)
            base = archive_dir / ("prove-it-" + dt.datetime.now().strftime("%Y%m%d%H%M%S%f"))
            shutil.make_archive(str(base), "zip", root_dir=dest.parent, base_dir=dest.name)
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(SOURCE, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"))
    backups = []
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_text(encoding="utf-8-sig") == content: continue
        old = backup(path)
        if old: backups.append(old)
        path.write_text(content, encoding="utf-8")
    return {"installed": str(dest), "operations": operations, "backups": backups,
            "hook_installed": with_hook, "note": "Restart the agent and verify skill/hook discovery. Host integration is not proven by file installation alone."}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--agent", choices=["copilot", "codex", "claude", "generic"], required=True)
    p.add_argument("--scope", choices=["user", "project"], default="user")
    p.add_argument("--project", type=Path)
    p.add_argument("--hooks", action="store_true")
    p.add_argument("--instructions", action="store_true")
    p.add_argument("--update", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    try:
        project = args.project.resolve() if args.project else None
        if project and not project.is_dir(): raise ValueError("Project does not exist")
        result = install(args.agent, args.scope, project, Path.home(), args.hooks,
                         args.instructions, args.update, args.dry_run)
        print(json.dumps(result, indent=2)); return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"Installation not completed: {exc}", file=sys.stderr); return 1


if __name__ == "__main__":
    raise SystemExit(main())
