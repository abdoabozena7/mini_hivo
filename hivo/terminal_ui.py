"""Quiet, keyboard-native terminal; session history is never execution authority."""

from __future__ import annotations

import builtins
import io
import json
import os
import re
import sys
import time
import traceback
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.text import Text

if TYPE_CHECKING:
    from .sessions import Session, SessionStore


_COMMANDS = (
    "/new", "/sessions", "/switch", "/resume", "/rename",
    "/history", "/logs", "/help", "/quit",
)
_NEW = object()
_CHOOSE = object()
_STATUSES = {
    "completed": "completed", "done": "completed", "success": "completed",
    "succeeded": "completed", "failed": "failed", "error": "failed",
    "cancelled": "cancelled", "canceled": "cancelled",
    "interrupted": "cancelled", "aborted": "cancelled", "blocked": "blocked",
    "clarification_required": "blocked", "needs_clarification": "blocked",
    "plan_approval_required": "blocked", "plan_rejected": "blocked",
    "too_broad": "failed", "budget_exhausted": "blocked",
}
_ALERT = re.compile(
    r"(?im)^\s*(?:\[[^\]\n]*(?:ERROR|WARNING|WARN|BLOCKED)[^\]\n]*\]"
    r"|(?:error|warning|warn|blocked|failed)\b)"
)
_BIDI_CONTROLS = {"RLE", "LRE", "RLO", "LRO", "PDF", "RLI", "LRI", "FSI", "PDI"}


def _literal(value) -> str:
    """Keep content literal, including a reversible spelling of unsafe controls."""
    result = []
    for character in str(value):
        code = ord(character)
        if character in "\n\t":
            result.append(character)
        elif (
            code < 32 or 127 <= code <= 159 or 0xD800 <= code <= 0xDFFF
            or unicodedata.bidirectional(character) in _BIDI_CONTROLS
        ):
            result.append(
                f"\\x{code:02x}" if code <= 255 else f"\\u{code:04x}"
            )
        else:
            result.append(character)
    return "".join(result)


def _compact(value, limit: int = 180) -> str:
    text = " ".join(_literal(value).split())
    return text if len(text) <= limit else text[:max(0, limit - 3)] + "..."


def _print_line(console: Console, value="", *, style="") -> None:
    console.print(Text(_literal(value), style=style), markup=False, highlight=False)


def _reference(session: Session, sessions: list[Session]) -> str:
    length = min(8, len(session.id))
    while any(
        other.id != session.id and other.id.startswith(session.id[:length])
        for other in sessions
    ):
        length += 1
    return session.id[:length]


def list_sessions(store: SessionStore, *, console: Console | None = None) -> None:
    """List local sessions without model setup, workspace mutation, or execution."""
    console = console if console is not None else Console()
    sessions = store.list()
    if not sessions:
        _print_line(console, "No sessions yet. Start Hivo to create one.")
        return
    _print_line(console, "Sessions", style="bold")
    for session in sessions:
        reference = _reference(session, sessions)
        recency = session.last_active_at[:16].replace("T", " ")
        name = Text(_compact(session.name), style="bold")
        name.truncate(max(8, console.width - len(reference) - len(recency) - 4))
        line = Text(reference, style="cyan")
        line.append("  ")
        line.append(name)
        line.append(f"  {recency}", style="dim")
        console.print(line, markup=False, highlight=False)
        _print_line(console, f"  {session.workspace}", style="dim")


class TerminalApp:
    def __init__(
        self, store: SessionStore, run_request, create_workspace, *,
        console: Console | None = None, verbose: bool = False,
        model: str = "gemma4:e4b",
    ):
        self.store = store
        self.run_request = run_request
        self.create_workspace = create_workspace
        self.console = console if console is not None else Console()
        self.verbose = verbose
        self.model = model
        self._session = None
        self._input = None
        self._running = False
        self._engine_active = False
        self._interaction_depth = 0
        self._status = None
        self._status_started = False
        self._progress_text = "Working"
        self._log = None
        self._log_error = None

    def _line(self, value="", *, style=""):
        _print_line(self.console, value, style=style)

    def _error(self, value):
        self._line(_compact(value, 240), style="red")

    def _storage_error(self, operation, error):
        self._error(f"Storage error: {operation}: {error}")

    def _header(self):
        title = Text("Hivo", style="bold")
        title.append(f"  {_compact(self.model, 40)}", style="dim")
        title.truncate(self.console.width)
        self.console.print(title, markup=False, highlight=False)
        self._line(f"Session: {self._session.name} ({self._session.id[:8]})")
        self._line(f"Workspace: {self._session.workspace}", style="dim")
        self._line("/help commands  /quit exit", style="dim")

    def _bindings(self, *, session_commands=True):
        bindings = KeyBindings()

        @bindings.add("enter")
        def submit(event):
            event.current_buffer.validate_and_handle()

        @bindings.add("escape", "enter")
        def newline(event):
            event.current_buffer.insert_text("\n")

        if not session_commands:
            return bindings

        @bindings.add("c-n")
        def new_session(event):
            event.app.exit(result=_NEW)

        @bindings.add("c-r")
        def choose_session(event):
            event.app.exit(result=_CHOOSE)

        return bindings

    def _input_session(self):
        if self._input is None:
            history = InMemoryHistory()
            for turn in self.store.history(self._session.id, limit=100):
                history.append_string(turn.prompt)
            self._input = PromptSession(
                multiline=True, key_bindings=self._bindings(), history=history,
                completer=WordCompleter(_COMMANDS, sentence=True),
                complete_while_typing=False,
            )
        return self._input

    def run(self, initial_session: Session) -> None:
        if self._running:
            raise RuntimeError("A request is already running.")
        try:
            self._session = self.store.select(initial_session.id)
        except Exception as error:
            self._storage_error("cannot open session", error)
            return
        self._input = None
        self._header()
        try:
            self._history(limit=2)
        except Exception as error:
            self._storage_error("cannot restore session history", error)
            return
        while True:
            try:
                value = self._input_session().prompt(
                    FormattedText([("bold ansicyan", "You> ")]),
                    bottom_toolbar=FormattedText([
                        ("", "Enter send  Alt+Enter newline  Ctrl+N new  Ctrl+R sessions"),
                    ]),
                )
            except EOFError:
                break
            except KeyboardInterrupt:
                self._line("Input cleared. /quit to exit.", style="dim")
                continue
            except Exception as error:
                self._storage_error("cannot read terminal history/input", error)
                break
            if value is _NEW:
                self._handle_command("/new")
            elif value is _CHOOSE:
                self._handle_command("/resume")
            elif isinstance(value, str) and value.strip():
                if value.lstrip().startswith("/"):
                    if self._handle_command(value.strip()):
                        break
                else:
                    try:
                        self._execute_request(value)
                    except KeyboardInterrupt:
                        self._line("Recording interrupted. Inspect /history and /logs.", style="yellow")
        self._line("Goodbye.", style="dim")

    def _handle_command(self, command: str) -> bool:
        if self._running:
            self._line("A request is running. Cancel it before changing sessions.", style="yellow")
            return False
        parts = command.split(maxsplit=1)
        name = parts[0]
        argument = parts[1].strip() if len(parts) > 1 else ""
        if name not in _COMMANDS:
            self._error(f"Unknown command: {name}. Use /help.")
            return False
        if name in {"/sessions", "/history", "/logs", "/help", "/quit"} and argument:
            self._error(f"Usage: {name}")
            return False
        try:
            if name == "/quit":
                return True
            if name == "/help":
                self._help()
            elif name == "/sessions":
                list_sessions(self.store, console=self.console)
            elif name == "/new":
                workspace = Path(self.create_workspace())
                try:
                    session = self.store.create(workspace, argument or None)
                except Exception:
                    self._line(f"Workspace created, but session not saved: {workspace}", style="yellow")
                    raise
                self._select(session.id)
            elif name in {"/switch", "/resume"}:
                if argument:
                    self._select(self.store.resolve(argument).id)
                elif name == "/resume":
                    selected = self._choose_session()
                    if selected is not None:
                        self._select(selected.id)
                else:
                    self._error("Usage: /switch ID-or-name. Use /sessions to list.")
            elif name == "/rename":
                if not argument:
                    self._error("Usage: /rename name")
                else:
                    self._session = self.store.rename(self._session.id, argument)
                    self._line(f"Session renamed: {self._session.name}")
            elif name == "/history":
                self._history(limit=8)
            elif name == "/logs":
                turns = self.store.history(self._session.id, limit=1)
                if not turns:
                    self._line("No request logs yet. Send a request first.", style="dim")
                elif not turns[-1].log_path.is_file():
                    self._error(f"Latest request log is missing: {turns[-1].log_path}")
                else:
                    self._line(f"Log: {turns[-1].log_path}")
        except (KeyboardInterrupt, EOFError):
            self._line("Command interrupted. Use /sessions to check your session.", style="dim")
        except (KeyError, ValueError, FileNotFoundError, NotADirectoryError) as error:
            self._error(f"Cannot {name[1:]}: {error}")
        except Exception as error:
            self._storage_error(f"{name} failed", error)
        return False

    def _help(self):
        for line in (
            "/new [name]             /sessions",
            "/switch ID-or-name      /resume [ID-or-name]",
            "/rename name            /history",
            "/logs                   /quit",
            "Enter send; Alt+Enter newline; Ctrl+C cancel",
            "Ctrl+N new session; Ctrl+R session chooser",
        ):
            self._line(line)

    def _select(self, session_id):
        session = self.store.select(session_id)
        self._session = session
        self._input = None
        self._line(f"Session: {session.name} ({session.id[:8]})", style="bold")
        self._line(f"Workspace: {session.workspace}", style="dim")
        self._history(limit=2)

    def _history(self, *, limit):
        turns = self.store.history(self._session.id, limit=limit)
        if not turns:
            self._line("No requests yet. Enter a task to begin.", style="dim")
            return
        for turn in turns:
            status = "unfinished" if turn.status == "running" else turn.status
            self._line(f"{status}: {_compact(turn.prompt, 100)}")
            if turn.summary:
                self._line(f"  {_compact(turn.summary, 140)}", style="dim")
            if turn.status == "running":
                self._line("  Not replayed. Inspect /logs before retrying.", style="yellow")

    def _choose_session(self):
        sessions = self.store.list()
        if not sessions:
            self._line("No sessions yet. Use /new.", style="dim")
            return None
        index = next(
            (i for i, session in enumerate(sessions) if session.id == self._session.id), 0
        )
        bindings = KeyBindings()

        @bindings.add("up")
        def previous(event):
            nonlocal index
            index = (index - 1) % len(sessions)

        @bindings.add("down")
        def following(event):
            nonlocal index
            index = (index + 1) % len(sessions)

        @bindings.add("enter")
        def select(event):
            event.app.exit(result=sessions[index])

        @bindings.add("escape", eager=True)
        @bindings.add("c-c")
        @bindings.add("c-d")
        def cancel(event):
            event.app.exit(result=None)

        @bindings.add("<any>")
        def ignore_text(event):
            pass

        def label():
            session = sessions[index]
            text = Text(
                f"{index + 1}/{len(sessions)}  {_compact(session.name)} "
                f"({session.id[:8]})"
            )
            text.truncate(max(10, self.console.width - 2))
            return FormattedText([("bold", text.plain + " ")])

        self._line("Sessions: Up/Down select, Enter resume, Esc cancel.", style="dim")
        with self.interaction():
            picker = PromptSession(key_bindings=bindings, erase_when_done=True)
            try:
                selected = picker.prompt(
                    label, bottom_toolbar=lambda: FormattedText([
                        ("", _literal(f"Workspace: {sessions[index].workspace}")),
                    ]),
                )
            except (KeyboardInterrupt, EOFError):
                selected = None
        if selected is None:
            self._line("Session selection cancelled.", style="dim")
        return selected

    def _start_activity(self):
        if self.console.is_interactive:
            self._status = self.console.status(
                Text(_compact(self._progress_text, max(10, self.console.width - 5))),
                spinner="line", spinner_style="cyan", refresh_per_second=6,
            )
            self._resume_activity()

    def _resume_activity(self):
        if (
            self._status is not None and not self._status_started
            and self._engine_active and self._interaction_depth == 0
        ):
            self._status.start()
            self._status_started = True

    def _pause_activity(self):
        if self._status is not None and self._status_started:
            self._status.stop()
            self._status_started = False

    def _stop_activity(self):
        self._pause_activity()
        self._status = None

    @contextmanager
    def interaction(self):
        """Suspend redraw for native dialogs, including nested and failed dialogs."""
        self._interaction_depth += 1
        try:
            self._pause_activity()
            yield
        finally:
            self._interaction_depth -= 1
            self._resume_activity()

    def read_prompt(self, label="You> ") -> str:
        with self.interaction():
            # A separate input session has no slash commands or session shortcuts.
            self._write_log(f"\nQuestion: {label}\n")
            answer = PromptSession(
                multiline=True, key_bindings=self._bindings(session_commands=False),
            ).prompt(FormattedText([("", _literal(label))]))
            self._write_log(f"\nAnswer: {answer}\n")
            return answer

    def _write_log(self, text):
        if self._log is None:
            return
        try:
            self._log.write(_literal(text))
            self._log.flush()
        except (OSError, ValueError, UnicodeError) as error:
            self._log_error = error
            raise

    def _try_log(self, text):
        try:
            self._write_log(text)
        except (OSError, ValueError, UnicodeError):
            pass

    def detail_print(self, *values, sep=" ", end="\n", file=None, flush=False):
        rendered = io.StringIO()
        builtins.print(*values, sep=sep, end=end, file=rendered)
        text = rendered.getvalue()
        self._write_log(text)
        if file is not None and file is not sys.stdout and file is not sys.stderr:
            builtins.print(_literal(text), end="", file=file, flush=flush)
            return
        alert = _ALERT.search(text) is not None or file is sys.stderr
        if not (self.verbose or self._interaction_depth or alert):
            return
        with self.interaction():
            if self.verbose or self._interaction_depth > 1:
                visible = _literal(text)
            else:
                visible = _compact(text, 220) + "\n"
            if file is not None:
                builtins.print(visible, end="", file=file, flush=flush)
            else:
                self.console.print(
                    Text(visible), end="", markup=False, highlight=False,
                )
                if flush:
                    self.console.file.flush()

    def progress(self, text, *, role=None, task=None, action=None, tool=None):
        self._write_log(
            "\nProgress: " + json.dumps(
                {"text": text, "role": role, "task": task, "action": action, "tool": tool},
                ensure_ascii=False, default=str,
            ) + "\n"
        )
        self._progress_text = _compact(text, max(10, self.console.width - 5))
        if self._engine_active and self._status is not None:
            self._status.update(Text(self._progress_text))

    def _invoke(self, prompt, session):
        self._progress_text = "Working"
        self._engine_active = True
        try:
            try:
                self._start_activity()
                result = self.run_request(prompt, session)
            finally:
                self._engine_active = False
                self._stop_activity()
            self._try_log(
                "\nEngine result:\n"
                + json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n"
            )
            if not isinstance(result, dict):
                raise ValueError("Engine returned no result object.")
            status = _STATUSES.get(str(result.get("status", "")).lower())
            if status is None:
                raise ValueError(f"Engine returned an invalid status: {result.get('status')!r}")
            summary = str(result.get("summary") or f"Request {status}.")
            changed = result.get("changed_files", [])
            return status, summary, str(result.get("run_id") or ""), changed
        except KeyboardInterrupt:
            self._try_log("\nCancelled by user.\n")
            return "cancelled", "Cancelled. Ready for another request.", "", []
        except EOFError:
            self._try_log("\nInput closed during request; cancelled.\n")
            return "cancelled", "Input closed. Request cancelled.", "", []
        except (Exception, SystemExit) as error:
            self._try_log("\nUnexpected request failure:\n" + traceback.format_exc())
            return "failed", f"Request failed: {error}", "", []

    def _finish(self, turn, status, summary, run_id=""):
        try:
            self.store.finish_turn(
                turn.id, status=status, summary=summary, run_id=run_id,
            )
            return True
        except Exception as error:
            self._storage_error("request status could not be saved", error)
            self._try_log(f"\nStorage error saving request status: {error}\n")
            return False

    def _execute_request(self, prompt):
        if self._running:
            self._error("A request is already running. Cancel it before submitting another.")
            return
        self._running = True
        self._log_error = None
        started = time.monotonic()
        try:
            try:
                turn = self.store.start_turn(self._session.id, prompt)
            except Exception as error:
                self._storage_error("request was not started", error)
                return
            try:
                # SessionStore already created this unique file; never truncate it.
                self._log = turn.log_path.open("a", encoding="utf-8", newline="\n")
                self._write_log(
                    f"Hivo request\nSession: {self._session.id}\n"
                    f"Name: {self._session.name}\nWorkspace: {self._session.workspace}\n"
                    f"Model: {self.model}\nStarted: {turn.started_at}\n\nUser:\n{prompt}\n\n"
                )
            except (OSError, ValueError, UnicodeError) as error:
                self._storage_error("diagnostic log unavailable; request not run", error)
                self._finish(turn, "failed", "Request not run: diagnostic log unavailable.")
                return
            status, summary, run_id, changed = self._invoke(prompt, self._session)
            self._try_log(f"\nOutcome: {status}\nSummary:\n{summary}\nRun: {run_id}\n")
            if self._log_error is None:
                try:
                    self._log.flush()
                    os.fsync(self._log.fileno())
                except (OSError, ValueError) as error:
                    self._log_error = error
            if self._log_error is not None:
                self._storage_error("diagnostic log incomplete", self._log_error)
                status, summary = "failed", "Request diagnostics could not be fully saved."
            saved = self._finish(turn, status, summary, run_id)
            elapsed = time.monotonic() - started
            style = {"completed": "green", "failed": "red", "cancelled": "yellow", "blocked": "yellow"}
            self._line(f"{status.capitalize()}  {elapsed:.1f}s", style=style[status])
            self._line(_compact(summary, min(280, max(90, (self.console.width - 2) * 3))))
            if isinstance(changed, (list, tuple)) and changed:
                files = ", ".join(str(item) for item in changed[:3])
                if len(changed) > 3:
                    files += f" (+{len(changed) - 3} more)"
                self._line(f"Files: {_compact(files, 100)}", style="dim")
            if not saved:
                self._line("History remains unfinished; do not assume completion was recorded.", style="yellow")
            self._line(f"Log: {turn.log_path}", style="dim")
        finally:
            self._engine_active = False
            self._stop_activity()
            if self._log is not None:
                try:
                    self._log.close()
                except OSError as error:
                    self._storage_error("cannot close diagnostic log", error)
                self._log = None
            self._running = False
