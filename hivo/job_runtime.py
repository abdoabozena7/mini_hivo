"""Local, fail-closed Docker boundary for the headless job service."""

from __future__ import annotations

import base64
import binascii
from contextlib import contextmanager
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import queue
import re
import shutil
import socket
import stat
import subprocess
import sys
import threading
import time

from hivo.model_policy import GEMMA_MODEL


_GEMMA_DIGEST = "c6eb396dbd5992bbe3f5cdb947e8bbc0ee413d7c17e2beaae69f5d569cf982eb"
_IMAGE = re.compile(r"sha256:[0-9a-f]{64}")
_ID = re.compile(r"[0-9a-f]{64}")
_REVISION = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_COMPONENT = re.compile(r"[A-Za-z0-9._ -]{1,120}")
_DEVICE = re.compile(r"(?i)(?:aux|con|nul|prn|com[0-9]|lpt[0-9])")
_LABEL = "com.mini-hivo.attempt"
_METADATA = frozenset({
    ".hivo", ".mini_hivo", ".agent_backups", ".agent_evidence", ".agent_runs",
    ".agent_memory.json", ".agent_experiment.jsonl",
})
_FILE_BYTES = 2 * 1024 * 1024
_TREE_BYTES = 12 * 1024 * 1024
_TREE_ENTRIES = 1024
_LINE_BYTES = 3 * 1024 * 1024
_WORKER_OUT = 24 * 1024 * 1024
_WORKER_ERR = 1024 * 1024
_PROVIDER_BYTES = 512 * 1024
_ORACLE_BYTES = 64 * 1024
_COMMAND_SECONDS = 5
_POLL = 0.03
_MEMORY = 512 * 1024 * 1024
_SHM = 8 * 1024 * 1024
_TMPFS = "rw,noexec,nosuid,nodev,size=67108864,nr_inodes=4096,mode=1777"
_UID = "65532:65532"
_PYTHON = "/usr/local/bin/python"
_WORKSPACE = "/scratch/project"
_BOOT = "import sys; sys.path.insert(0, '/engine'); from hivo.job_runtime import _container_main; _container_main()"
_ORACLE_BOOT = (
    "import os, runpy, sys; sys.argv = sys.argv[1:]; "
    "sys.path.insert(0, os.path.dirname(sys.argv[0])); runpy.run_path(sys.argv[0], run_name='__main__')"
)
_IMAGE_ENV = frozenset({
    "PATH", "LANG", "LC_ALL", "PYTHON_VERSION", "PYTHON_SHA256", "PYTHON_PIP_VERSION",
    "PYTHON_GET_PIP_URL", "PYTHON_GET_PIP_SHA256", "PYTHON_SETUPTOOLS_VERSION", "GPG_KEY",
})
_CONTAINER_ENV = {
    "HOME": "/scratch/home", "TMPDIR": "/scratch", "PATH": "/usr/local/bin:/usr/bin:/bin",
    "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
}
_OUTCOME_STATES = frozenset({
    "waiting_clarification", "waiting_approval", "candidate", "failed", "blocked",
    "timed_out", "cancelled", "interrupted",
})


class _Failure(Exception):
    def __init__(self, code: str, status: str = "failed"):
        super().__init__(code)
        self.code = code
        self.status = status


def _check_clock(deadline, cancelled, *, expired="attempt_deadline"):
    if cancelled():
        raise _Failure("attempt_cancelled", "cancelled")
    if time.monotonic() >= deadline:
        raise _Failure(expired, "timed_out")


def _not_cancelled():
    return False


def _number(value, minimum, maximum):
    return (
        type(value) in (int, float)
        and minimum <= value <= maximum
        and math.isfinite(value)
    )


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def invalid(_value):
        raise ValueError("nonfinite JSON")

    def finite(text):
        value = float(text)
        if not math.isfinite(value):
            invalid(text)
        return value

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid, parse_float=finite)
    if not isinstance(value, dict):
        raise ValueError("not a JSON object")
    return value


def _line(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii") + b"\n"


def _oracle_command(script, args):
    return ("-I", "-B", "-u", "-c", _ORACLE_BOOT, script, *args)


class _Child:
    """Bounded pipes, including writes to a worker that may stop reading."""

    def __init__(self, argv, env, cwd, out_limit, err_limit, *, lines=False):
        self.proc = subprocess.Popen(
            argv, env=env, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, shell=False,
        )
        self.shutdown = threading.Event()
        self.overflow = threading.Event()
        self.output = queue.Queue(8)
        self.input = queue.Queue(2)
        self.stderr = bytearray()
        self.threads = [
            threading.Thread(target=self._read_stdout, args=(out_limit, lines), daemon=True),
            threading.Thread(target=self._read_stderr, args=(err_limit,), daemon=True),
            threading.Thread(target=self._write_stdin, daemon=True),
        ]
        for thread in self.threads:
            thread.start()

    def _emit(self, item):
        while not self.shutdown.is_set():
            try:
                self.output.put(item, timeout=_POLL)
                return
            except queue.Full:
                pass

    def _read_stdout(self, limit, lines):
        total = 0
        try:
            with self.proc.stdout as stream:
                while not self.shutdown.is_set():
                    data = stream.readline(_LINE_BYTES + 1) if lines else stream.read1(65536)
                    if not data:
                        break
                    total += len(data)
                    if total > limit or (lines and (len(data) > _LINE_BYTES or not data.endswith(b"\n"))):
                        self.overflow.set()
                        break
                    self._emit(data)
        except OSError:
            self.overflow.set()
        finally:
            self._emit(None)

    def _read_stderr(self, limit):
        try:
            with self.proc.stderr as stream:
                while not self.shutdown.is_set():
                    data = stream.read1(65536)
                    if not data:
                        break
                    if len(self.stderr) + len(data) > limit:
                        self.overflow.set()
                        break
                    self.stderr.extend(data)
        except OSError:
            self.overflow.set()

    def _write_stdin(self):
        try:
            with self.proc.stdin as stream:
                while not self.shutdown.is_set():
                    try:
                        item = self.input.get(timeout=_POLL)
                    except queue.Empty:
                        continue
                    if item is None:
                        break
                    stream.write(item)
                    stream.flush()
        except OSError:
            # Exit and the actual protocol, not a local broken pipe, decide the outcome.
            pass

    def send(self, data):
        try:
            self.input.put_nowait(data)
        except queue.Full:
            raise _Failure("worker_protocol_invalid") from None

    def _guard(self, deadline, cancelled):
        _check_clock(deadline, cancelled)
        if self.overflow.is_set():
            raise _Failure("process_output_limit")

    def receive(self, deadline, cancelled):
        while True:
            self._guard(deadline, cancelled)
            try:
                value = self.output.get(timeout=_POLL)
            except queue.Empty:
                continue
            self._guard(deadline, cancelled)
            return value

    def wait(self, deadline, cancelled):
        while self.proc.poll() is None or self.threads[1].is_alive():
            self._guard(deadline, cancelled)
            time.sleep(_POLL)
        self._guard(deadline, cancelled)
        return self.proc.returncode

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.shutdown.set()
        if self.proc.poll() is None:
            self.proc.kill()
        try:
            self.proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            # The daemon-side fence is still required even when its client was killed.
            pass
        for thread in self.threads:
            thread.join(timeout=_POLL * 2)


def _host_environment():
    # Do not let Docker contexts, proxy variables, Git alternates or credentials
    # override the local endpoint or affect which objects are staged.
    return {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "LANG") if key in os.environ}


def _executable(name):
    binary = name + (".exe" if os.name == "nt" else "")
    for folder in os.get_exec_path():
        folder = Path(folder.strip('"'))
        if folder.is_absolute():
            candidate = folder / binary
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate.resolve())
    return None


def _capture(argv, env, cwd, deadline, cancelled, *, input_bytes=None, limit=_ORACLE_BYTES):
    _check_clock(deadline, cancelled)
    with _Child(argv, env, cwd, limit, min(limit, _WORKER_ERR)) as child:
        if input_bytes is not None:
            child.send(input_bytes)
        child.send(None)
        output = bytearray()
        while (part := child.receive(deadline, cancelled)) is not None:
            output.extend(part)
        code = child.wait(deadline, cancelled)
        return subprocess.CompletedProcess(argv, code, bytes(output), bytes(child.stderr))


def _path_parts(path, *, stage=False):
    if not isinstance(path, str) or len(path) > 400:
        raise _Failure("unsupported_project_path", "blocked" if stage else "failed")
    parts = path.split("/")
    if (
        any(not _COMPONENT.fullmatch(p) or p[-1] in ". " or p.lower() == ".git"
            or _DEVICE.fullmatch(p.partition(".")[0].rstrip()) for p in parts)
        or parts[0].lower() in _METADATA
    ):
        raise _Failure("unsupported_project_path", "blocked" if stage else "failed")
    return parts


class _Inventory:
    def __init__(self, *, stage=False):
        self.stage = stage
        self.nodes = {}
        self.total = 0
        self.files = 0

    def track(self, path, *, directory=False):
        parts = _path_parts(path, stage=self.stage)
        for index in range(len(parts)):
            name = "/".join(parts[:index + 1])
            key = name.lower()
            node = (name, index < len(parts) - 1 or directory)
            existing = self.nodes.get(key)
            if existing is not None and (existing != node or not node[1]):
                raise _Failure("project_path_collision", "blocked" if self.stage else "failed")
            self.nodes[key] = node
        if len(self.nodes) > _TREE_ENTRIES:
            raise _Failure("project_size_limit", "blocked" if self.stage else "failed")
        return parts

    def add(self, path, mode, data, root=None):
        parts = self.track(path)
        self.files += 1
        self.total += len(data)
        if (
            type(mode) is not int or mode not in (0o644, 0o755)
            or (os.name == "nt" and mode == 0o755)
            or len(data) > _FILE_BYTES or self.total > _TREE_BYTES or b"\0" in data
        ):
            raise _Failure("unsupported_project_blob", "blocked" if self.stage else "failed")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise _Failure("unsupported_project_blob", "blocked" if self.stage else "failed") from None
        if root is not None:
            dest = root.joinpath(*parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("xb") as file:
                file.write(data)
            dest.chmod(mode)
            if bool(dest.stat().st_mode & stat.S_IXUSR) != bool(mode & stat.S_IXUSR):
                raise _Failure("unsupported_project_mode", "blocked" if self.stage else "failed")


def _stage_repository(git, repository, revision, base, deadline, cancelled, host_cwd):
    if not isinstance(revision, str) or not _REVISION.fullmatch(revision):
        raise _Failure("invalid_base_revision", "blocked")
    env = _host_environment() | {
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
        "GIT_NO_LAZY_FETCH": "1", "GIT_ALLOW_PROTOCOL": "", "GIT_OPTIONAL_LOCKS": "0",
    }

    def read(*args, limit=_ORACLE_BYTES, input_bytes=None):
        if not git:
            raise _Failure("git_unavailable", "blocked")
        proc = _capture(
            [git, "--no-pager", "--no-replace-objects", "-C", str(repository), *args],
            env, host_cwd, min(deadline, time.monotonic() + _COMMAND_SECONDS),
            cancelled, limit=limit, input_bytes=input_bytes,
        )
        if proc.returncode:
            raise _Failure("base_revision_unavailable", "blocked")
        return proc.stdout

    top = read("rev-parse", "--show-toplevel").decode("utf-8").strip("\r\n")
    if Path(top).resolve(strict=True) != repository:
        raise _Failure("base_revision_unavailable", "blocked")
    commit = read("cat-file", "commit", revision, limit=_FILE_BYTES)
    algorithm = "sha1" if len(revision) == 40 else "sha256"
    if hashlib.new(algorithm, b"commit " + str(len(commit)).encode() + b"\0" + commit).hexdigest() != revision:
        raise _Failure("base_revision_unavailable", "blocked")
    tree = read("ls-tree", "-r", "-z", "-l", "--full-tree", revision, limit=1024 * 1024)
    entries = []
    inventory = _Inventory(stage=True)
    size = 0
    if tree and not tree.endswith(b"\0"):
        raise _Failure("base_revision_unavailable", "blocked")
    for record in tree.split(b"\0")[:-1]:
        header, path = record.split(b"\t", 1)
        mode, kind, oid, length = header.split()
        if mode not in (b"100644", b"100755") or kind != b"blob":
            raise _Failure("unsupported_project_blob", "blocked")
        path = path.decode("utf-8")
        inventory.track(path)
        length = int(length)
        size += length
        if length > _FILE_BYTES or size > _TREE_BYTES:
            raise _Failure("project_size_limit", "blocked")
        if not _REVISION.fullmatch(oid.decode("ascii")) or len(oid) != len(revision):
            raise _Failure("base_revision_unavailable", "blocked")
        entries.append((path, int(mode[-3:], 8), oid, length))

    inventory = _Inventory(stage=True)
    base.mkdir()
    if not entries:
        return b""
    raw = read("cat-file", "--batch", limit=_TREE_BYTES + _TREE_ENTRIES * 128,
               input_bytes=b"".join(oid + b"\n" for _, _, oid, _ in entries))
    stage = []
    cursor = 0
    for path, mode, oid, length in entries:
        _check_clock(deadline, cancelled)
        header = oid + b" blob " + str(length).encode("ascii") + b"\n"
        start = cursor + len(header)
        end = start + length
        data = raw[start:end]
        algorithm = "sha1" if len(oid) == 40 else "sha256"
        actual = hashlib.new(algorithm, b"blob " + str(length).encode("ascii") + b"\0" + data)
        if raw[cursor:start] != header or raw[end:end + 1] != b"\n" or actual.hexdigest().encode() != oid:
            raise _Failure("base_revision_unavailable", "blocked")
        inventory.add(path, mode, data, base)
        stage.append(_file_line(path, mode, data))
        cursor = end + 1
    if cursor != len(raw):
        raise _Failure("base_revision_unavailable", "blocked")
    return b"".join(stage)


def _file_line(path, mode, data):
    return _line({"kind": "file", "path": path, "mode": mode, "data": base64.b64encode(data).decode("ascii")})


def _receive_file(message, inventory, root):
    if set(message) != {"kind", "path", "mode", "data"} or not isinstance(message["data"], str):
        raise _Failure("worker_protocol_invalid")
    try:
        data = base64.b64decode(message["data"], validate=True)
    except (ValueError, binascii.Error):
        raise _Failure("worker_protocol_invalid") from None
    inventory.add(message["path"], message["mode"], data, root)


def _ordinary(stat_info):
    return not getattr(stat_info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)


def _files(root, *, ignore_metadata=False):
    """Read only bounded regular files; never follow candidate links."""
    inventory = _Inventory()
    root_info = root.lstat()
    if not _ordinary(root_info) or not stat.S_ISDIR(root_info.st_mode):
        raise _Failure("unsupported_project_path")

    def walk(folder, prefix):
        with os.scandir(folder) as listing:
            for entry in listing:
                if not prefix and ignore_metadata and entry.name in _METADATA:
                    continue
                relative = prefix + entry.name
                info = entry.stat(follow_symlinks=False)
                if _ordinary(info) and stat.S_ISDIR(info.st_mode):
                    inventory.track(relative, directory=True)
                    yield from walk(Path(entry.path), relative + "/")
                elif _ordinary(info) and stat.S_ISREG(info.st_mode):
                    if info.st_size > _FILE_BYTES:
                        raise _Failure("project_size_limit")
                    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
                    flags |= getattr(os, "O_BINARY", 0)
                    with os.fdopen(os.open(entry.path, flags), "rb") as file:
                        live = os.fstat(file.fileno())
                        if not stat.S_ISREG(live.st_mode) or live.st_nlink != 1:
                            raise _Failure("unsupported_project_path")
                        data = file.read(_FILE_BYTES + 1)
                    mode = 0o755 if os.name != "nt" and live.st_mode & stat.S_IXUSR else 0o644
                    inventory.add(relative, mode, data)
                    yield relative, mode, data
                else:
                    raise _Failure("unsupported_project_path")

    yield from walk(root, "")


def _container_main():
    """Image-side bootstrap. The only writable project is a private sized tmpfs."""
    import ctypes

    # A same-UID candidate subprocess must not open the launcher's attach fds.
    if ctypes.CDLL(None).prctl(4, 0, 0, 0, 0):  # PR_SET_DUMPABLE
        raise SystemExit(90)
    workspace = Path(_WORKSPACE)
    workspace.mkdir()
    Path("/scratch/home").mkdir()
    inventory = _Inventory()
    while True:
        raw = sys.stdin.buffer.readline(_LINE_BYTES + 1)
        if len(raw) > _LINE_BYTES or not raw.endswith(b"\n"):
            raise SystemExit(90)
        message = _json(raw)
        if message == {"kind": "stage_end"}:
            break
        if message.get("kind") != "file":
            raise SystemExit(90)
        _receive_file(message, inventory, workspace)
    sys.stdout.buffer.write(_line({"kind": "staged"}))
    sys.stdout.buffer.flush()
    worker = subprocess.run(
        [sys.executable, "-B", "-u", "-m", "hivo.job_worker"],
        cwd="/engine", stdin=sys.stdin.buffer, stdout=sys.stdout.buffer, stderr=sys.stderr.buffer,
        start_new_session=True,
    )
    if worker.returncode:
        raise SystemExit(91)
    # The host accepts an export only after verified container exit and removal.
    sys.stdout.buffer.write(_line({"kind": "snapshot"}))
    for path, mode, data in _files(workspace, ignore_metadata=True):
        sys.stdout.buffer.write(_file_line(path, mode, data))
    sys.stdout.buffer.write(_line({"kind": "snapshot_end"}))
    sys.stdout.buffer.flush()


def _local_http(method, path, body, deadline, cancelled):
    """One direct local request, with a wall deadline even for trickling HTTP."""
    _check_clock(deadline, cancelled, expired="provider_timeout")
    result = queue.Queue(1)
    transport = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    seconds = max(0.001, deadline - time.monotonic())
    transport.settimeout(seconds)

    def exchange():
        conn = http.client.HTTPConnection("127.0.0.1", 11434, timeout=seconds)
        try:
            transport.connect(("127.0.0.1", 11434))
            conn.sock = transport
            conn.request(method, path, body=body, headers={
                "Content-Type": "application/json", "Connection": "close", "Accept-Encoding": "identity",
            })
            with conn.getresponse() as response:
                if 300 <= response.status < 400:
                    raise ValueError("redirect")
                data = response.read(_PROVIDER_BYTES + 1)
                if len(data) > _PROVIDER_BYTES:
                    raise ValueError("large response")
                result.put((response.status, data.decode("utf-8")))
        except (OSError, ValueError, http.client.HTTPException):
            result.put(None)
        finally:
            conn.close()
            transport.close()

    thread = threading.Thread(target=exchange, daemon=True)
    thread.start()
    try:
        while True:
            _check_clock(deadline, cancelled, expired="provider_timeout")
            try:
                return result.get(timeout=_POLL)
            except queue.Empty:
                continue
    finally:
        try:
            transport.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        transport.close()
        thread.join(timeout=_POLL * 2)


def _chat_payload(payload):
    if not isinstance(payload, dict) or set(payload) - {
        "model", "messages", "stream", "keep_alive", "options", "think", "tools", "format",
    } or payload.get("model") != GEMMA_MODEL or payload.get("stream", False) is not False:
        return None
    if (
        not isinstance(payload.get("messages"), list) or not payload["messages"]
        or len(payload["messages"]) > 256 or payload.get("keep_alive", "10m") != "10m"
        or type(payload.get("think", False)) is not bool
    ):
        return None
    options = payload.get("options", {})
    if not isinstance(options, dict) or set(options) - {"num_ctx", "num_predict", "temperature", "seed", "num_gpu"}:
        return None
    options = {"num_ctx": 4096, "num_predict": 4096, **options}
    for key, lower, upper in (("num_ctx", 512, 12288), ("num_predict", 1, 4096),
                              ("seed", -1, 2147483647), ("num_gpu", 0, 0)):
        if key in options and (type(options[key]) is not int or not lower <= options[key] <= upper):
            return None
    if "temperature" in options and not _number(options["temperature"], 0, 2):
        return None
    return payload | {"stream": False, "keep_alive": "10m", "options": options}


class _Bridge:
    def __init__(self, limit, deadline, cancelled):
        self.limit, self.deadline, self.cancelled = limit, deadline, cancelled
        self.calls = self.requests = 0
        self.catalog = None

    def _pin(self, deadline):
        response = _local_http("GET", "/api/tags", None, deadline, self.cancelled)
        if response is None or response[0] != 200:
            return None
        try:
            models = _json(response[1].encode("utf-8"))["models"]
            matching = [
                row for row in models if isinstance(row, dict)
                and (row.get("name") or row.get("model")) == GEMMA_MODEL
            ]
            if len(matching) != 1:
                return None
            row = matching[0]
            digest = row.get("digest")
            if not isinstance(digest, str) or digest.removeprefix("sha256:") != _GEMMA_DIGEST:
                return None
            if row.get("remote_host") or row.get("remote_model"):
                return None
            return {"models": [{"name": GEMMA_MODEL, "model": GEMMA_MODEL, "digest": digest}]}
        except (KeyError, TypeError, ValueError, RecursionError):
            return None

    def handle(self, request):
        self.requests += 1
        if self.requests > self.limit + 8:
            raise _Failure("provider_request_limit")
        reply = {"kind": "provider_result"}
        denied = reply | {"error": "provider_request_denied"}
        if set(request) != {"kind", "op", "path", "timeout", "payload"}:
            return denied
        op, path, timeout, payload = (request[key] for key in ("op", "path", "timeout", "payload"))
        if not _number(timeout, 0.000001, 600):
            return denied
        tags = op == "get" and path == "/api/tags" and payload is None
        show = op == "post" and path == "/api/show" and payload == {"model": GEMMA_MODEL}
        chat = op == "post" and path == "/api/chat"
        if chat:
            payload = _chat_payload(payload)
        if not (tags or show or (chat and payload is not None)):
            return denied
        if chat and self.calls >= self.limit:
            return reply | {"error": "provider_call_budget_exhausted"}
        body = _line(payload) if not tags else None
        if body is not None and len(body) > _PROVIDER_BYTES:
            return denied
        deadline = min(self.deadline, time.monotonic() + timeout)
        try:
            if tags or self.catalog is None:
                self.catalog = self._pin(deadline)
            if self.catalog is None:
                return reply | {"error": "pinned_local_model_unavailable"}
            if tags:
                return reply | {"status_code": 200, "text": _line(self.catalog).decode("ascii")}
            if chat:
                self.calls += 1
            result = _local_http("POST", path, body, deadline, self.cancelled)
        except _Failure as exc:
            if exc.status == "cancelled" or time.monotonic() >= self.deadline:
                raise
            return reply | {"error": "provider_timeout"}
        if result is None:
            return reply | {"error": "local_provider_unavailable"}
        return reply | {"status_code": result[0], "text": result[1]}


class _Attempt:
    def __init__(self, root, attempt_id):
        self.key = hashlib.sha256(attempt_id.encode("utf-8")).hexdigest()
        self.path = root / ("attempt-" + self.key)
        self.scratch = self.path / "scratch"
        self.journal = self.path / "state.json"
        self.cancellation = self.path / "cancel"

    def cancelled(self):
        return self.cancellation.exists()

    def _ensure_directory(self):
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.path.mkdir(mode=0o700, exist_ok=True)

    def request_cancel(self):
        self._ensure_directory()
        try:
            with self.cancellation.open("xb"):
                pass
        except FileExistsError:
            pass

    @contextmanager
    def lease(self):
        self._ensure_directory()
        with (self.path / "lease").open("a+b") as lock:
            if os.name == "nt":
                import msvcrt

                lock.seek(0)
                try:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    yield False
                    return
            else:
                import fcntl

                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    yield False
                    return
            yield True

    def read(self):
        try:
            with self.journal.open("rb") as file:
                return _json(file.read(4096))
        except FileNotFoundError:
            return None

    def write(self, phase, **fields):
        temporary = self.path / "state.new"
        with temporary.open("wb") as file:
            file.write(_line({"phase": phase, **fields}))
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, self.journal)


class DockerJobRuntime:
    """Operate against one trusted local Linux daemon and a pinned local image ID.

    ``work_root`` must be private to the host service and outside registered
    projects. Retain its journals across service restarts. A lost journal or
    an unknown daemon response is not stop evidence. Only a trusted finalizer
    may call ``check`` to borrow an independently materialized candidate.
    """

    def __init__(self, work_root, *, image, engine_root):
        self.work_root = Path(work_root).resolve()
        self.engine_root = Path(engine_root).resolve()
        self.image = image
        self._docker = _executable("docker")
        self._git = _executable("git")
        self._config = self.work_root / "docker-config"
        self._endpoint = (
            "npipe:////./pipe/dockerDesktopLinuxEngine" if os.name == "nt"
            else "unix:///var/run/docker.sock"
        )
        self._current = threading.local()

    def _docker_argv(self, *args):
        if not self._docker:
            raise _Failure("docker_unavailable", "blocked")
        return [self._docker, "--config", str(self._config), "--host", self._endpoint, *args]

    def _command(self, args, deadline, cancelled, *, limit=_ORACLE_BYTES):
        return _capture(self._docker_argv(*args), _host_environment(), self.work_root,
                        min(deadline, time.monotonic() + _COMMAND_SECONDS), cancelled, limit=limit)

    def _daemon_json(self, args, deadline, cancelled, code):
        try:
            proc = self._command(args, deadline, cancelled)
            if not proc.returncode:
                return _json(proc.stdout)
        except _Failure as exc:
            if exc.status == "cancelled" or time.monotonic() >= deadline:
                raise
        except (OSError, ValueError, RecursionError):
            pass
        raise _Failure(code, "blocked")

    def _admit(self, deadline, cancelled):
        if not isinstance(self.image, str) or not _IMAGE.fullmatch(self.image):
            raise _Failure("immutable_image_required", "blocked")
        self._config.mkdir(mode=0o700, exist_ok=True)
        if self._config.is_symlink() or any(self._config.iterdir()):
            raise _Failure("untrusted_docker_configuration", "blocked")
        info = self._daemon_json(("info", "--format", "{{json .}}"), deadline, cancelled, "docker_unavailable")
        security = info.get("SecurityOptions") or []
        if (
            info.get("OSType") != "linux" or info.get("MemTotal", 0) < _MEMORY
            or not all(info.get(key) is True for key in ("MemoryLimit", "SwapLimit", "PidsLimit", "CPUCfsQuota"))
            or "name=seccomp,profile=builtin" not in security
        ):
            raise _Failure("isolation_profile_unavailable", "blocked")
        image = self._daemon_json(
            ("image", "inspect", "--format", "{{json .}}", self.image),
            deadline, cancelled, "local_image_unavailable",
        )
        arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(info.get("Architecture"), info.get("Architecture"))
        config = image.get("Config") or {}
        if (
            image.get("Id") != self.image or image.get("Os") != "linux"
            or arch not in {"amd64", "arm64"} or image.get("Architecture") != arch
            or config.get("Volumes")
            or any(not isinstance(item, str) or item.partition("=")[0] not in _IMAGE_ENV
                   for item in (config.get("Env") or []))
        ):
            raise _Failure("untrusted_image_profile", "blocked")

    def _engine_copy(self, destination, deadline, cancelled):
        destination.mkdir()
        (destination / "hivo").mkdir()
        paths = [self.engine_root / "mini.py", *self.engine_root.joinpath("hivo").glob("*.py")]
        required = {"mini.py", "__init__.py", "job_worker.py", "job_runtime.py", "model_policy.py"}
        if not required.issubset({path.name for path in paths}) or len(paths) > 256:
            raise _Failure("controller_unavailable", "blocked")
        total = 0
        for path in paths:
            _check_clock(deadline, cancelled)
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or not _ordinary(info) or info.st_size > _FILE_BYTES:
                raise _Failure("controller_unavailable", "blocked")
            total += info.st_size
            if total > _TREE_BYTES:
                raise _Failure("controller_unavailable", "blocked")
            shutil.copyfile(path, destination / path.relative_to(self.engine_root))

    def _create(self, attempt, source, target, cwd, command, deadline):
        source_text = str(source)
        if any(c in source_text for c in ',\"\r\n'):
            raise _Failure("unsupported_mount_path", "blocked")
        name = "hivo-" + attempt.key[:20] + "-" + os.urandom(8).hex()
        env_args = tuple(arg for key, value in _CONTAINER_ENV.items() for arg in ("--env", f"{key}={value}"))
        args = (
            "create", "--pull=never", "--name", name, "--label", f"{_LABEL}={attempt.key}",
            "--runtime=runc", "--network=none", "--read-only", "--cap-drop=ALL",
            "--security-opt=no-new-privileges", "--user", _UID, "--ipc=private", "--cgroupns=private",
            "--restart=no", "--no-healthcheck", "--log-driver=none", "--memory", str(_MEMORY),
            "--memory-swap", str(_MEMORY), "--cpus=1", "--pids-limit=64", "--shm-size", str(_SHM),
            "--ulimit", "nofile=256:256", "--ulimit", "fsize=4194304:4194304",
            "--tmpfs", "/scratch:" + _TMPFS, *env_args,
            "--mount", f"type=bind,source={source_text},target={target},readonly,"
            "bind-propagation=rprivate,bind-recursive=disabled",
            "--workdir", cwd, "--entrypoint", _PYTHON, "-i", self.image, *command,
        )
        _check_clock(deadline, attempt.cancelled)
        attempt.write("creating", name=name)
        proc = self._command(args, deadline, attempt.cancelled)
        container = proc.stdout.decode("ascii").strip()
        if proc.returncode or not _ID.fullmatch(container):
            raise _Failure("container_create_failed", "blocked")
        attempt.write("created", name=name, container=container)
        info = self._inspect(container, deadline, attempt.cancelled)
        self._verify_container(info, attempt, container, target, cwd, command)
        return container

    def _inspect(self, container, deadline, cancelled):
        return self._daemon_json(("container", "inspect", "--format", "{{json .}}", container),
                                 deadline, cancelled, "container_inspect_failed")

    def _verify_container(self, info, attempt, container, target, cwd, command):
        config, host, state = (info.get(key) or {} for key in ("Config", "HostConfig", "State"))
        mounts = info.get("Mounts") or []
        binds = [mount for mount in mounts if mount.get("Type") == "bind"]
        security = host.get("SecurityOpt")
        environment = dict(item.split("=", 1) for item in (config.get("Env") or []))
        limits = {entry.get("Name"): (entry.get("Soft"), entry.get("Hard"))
                  for entry in (host.get("Ulimits") or [])}
        if (
            info.get("Id") != container or info.get("Image") != self.image
            or config.get("User") != _UID or config.get("WorkingDir") != cwd
            or config.get("Entrypoint") != [_PYTHON] or config.get("Cmd") != list(command)
            or any(environment.get(key) != value for key, value in _CONTAINER_ENV.items())
            or environment.keys() - (_IMAGE_ENV | _CONTAINER_ENV.keys())
            or (config.get("Labels") or {}).get(_LABEL) != attempt.key
            or not config.get("OpenStdin") or config.get("Tty") is not False
            or state.get("Status") != "created" or state.get("Pid") != 0
            or host.get("Runtime") != "runc" or host.get("NetworkMode") != "none"
            or host.get("ReadonlyRootfs") is not True or host.get("Privileged") is not False
            or host.get("CapDrop") != ["ALL"] or host.get("CapAdd")
            or host.get("IpcMode") != "private" or host.get("CgroupnsMode") != "private"
            or host.get("PidMode") not in ("", "private") or host.get("UsernsMode") not in ("", "private")
            or security not in (["no-new-privileges"], ["no-new-privileges=true"])
            or (host.get("RestartPolicy") or {}).get("Name") not in ("", "no")
            or (host.get("LogConfig") or {}).get("Type") != "none"
            or host.get("Memory") != _MEMORY or host.get("MemorySwap") != _MEMORY
            or host.get("NanoCpus") != 1_000_000_000 or host.get("PidsLimit") != 64
            or host.get("ShmSize") != _SHM or host.get("Tmpfs") != {"/scratch": _TMPFS}
            or limits != {"nofile": (256, 256), "fsize": (4194304, 4194304)}
            or any(host.get(key) for key in ("Binds", "Devices", "DeviceRequests", "VolumesFrom", "PortBindings"))
            or len(binds) != 1 or binds[0].get("Destination") != target or binds[0].get("RW") is not False
            or any(mount.get("Type") != "bind" and (
                mount.get("Type") != "tmpfs" or mount.get("Destination") != "/scratch"
            ) for mount in mounts)
        ):
            raise _Failure("container_profile_mismatch", "blocked")

    def _gone(self, attempt):
        """Only positive removal of our exact immutable container is a fence."""
        try:
            state = attempt.read()
            if state is None:
                return False
            phase = state.get("phase")
            if phase in ("idle", "stopped"):
                return True
            if phase not in ("creating", "created", "launching"):
                return False
            deadline = time.monotonic() + _COMMAND_SECONDS
            container = state.get("container")
            if container is None:
                info = self._inspect(state["name"], deadline, _not_cancelled)
                if (info.get("Config", {}).get("Labels") or {}).get(_LABEL) != attempt.key:
                    return False
                container = info.get("Id")
            if not isinstance(container, str) or not _ID.fullmatch(container):
                return False
            result = self._command(("container", "rm", "--force", container), deadline, _not_cancelled)
            if result.returncode or result.stdout.strip() != container.encode("ascii"):
                return False
            attempt.write("idle")
            return True
        except (_Failure, OSError, TypeError, ValueError, KeyError, RecursionError):
            return False

    def _exit_code(self, container, deadline, cancelled):
        info = self._inspect(container, deadline, cancelled)
        state = info.get("State") or {}
        code = state.get("ExitCode")
        if (
            info.get("Id") != container or state.get("Status") != "exited"
            or state.get("Pid") != 0 or state.get("Running") is not False
            or state.get("Restarting") is not False or type(code) is not int
        ):
            raise _Failure("container_exit_unconfirmed")
        return code

    def _worker_io(self, attempt, container, job, stage, candidate, bridge, deadline):
        if len((request := _line({"kind": "start", "job": job, "workspace": _WORKSPACE}))) > _LINE_BYTES:
            raise _Failure("job_request_size_limit", "blocked")
        cancelled = attempt.cancelled
        _check_clock(deadline, cancelled)
        attempt.write("launching", name=attempt.read()["name"], container=container)
        with _Child(
            self._docker_argv("start", "-a", "-i", container), _host_environment(), self.work_root,
            _WORKER_OUT, _WORKER_ERR, lines=True,
        ) as child:
            child.send(stage + _line({"kind": "stage_end"}))
            raw = child.receive(deadline, cancelled)
            if raw is None or _json(raw) != {"kind": "staged"}:
                raise _Failure("worker_stage_failed")
            child.send(request)
            outcome, snapshot, complete = None, False, False
            inventory = _Inventory()
            while (raw := child.receive(deadline, cancelled)) is not None:
                message = _json(raw)
                kind = message.get("kind")
                if kind == "provider" and outcome is None:
                    if len(raw) > _PROVIDER_BYTES:
                        raise _Failure("provider_request_limit")
                    reply = _line(bridge.handle(message))
                    child.send(reply if len(reply) <= _PROVIDER_BYTES else _line({
                        "kind": "provider_result", "error": "provider_response_limit",
                    }))
                elif kind == "outcome" and set(message) == {"kind", "outcome"} and outcome is None:
                    outcome = self._worker_outcome(message["outcome"], job["limits"], bridge.calls)
                elif message == {"kind": "snapshot"} and outcome is not None and not snapshot:
                    snapshot = True
                    if outcome["status"] == "candidate":
                        candidate.mkdir()
                elif kind == "file" and snapshot and not complete:
                    _receive_file(message, inventory, candidate if outcome["status"] == "candidate" else None)
                elif message == {"kind": "snapshot_end"} and snapshot and not complete:
                    complete = True
                else:
                    raise _Failure("worker_protocol_invalid")
            code = child.wait(deadline, cancelled)
        if code != 0 or self._exit_code(container, deadline, cancelled) != 0:
            raise _Failure("worker_exit_failed")
        if not complete or outcome is None:
            raise _Failure("worker_protocol_invalid")
        return outcome

    @staticmethod
    def _worker_outcome(outcome, limits, model_calls):
        fields = {"status", "failure_code", "checkpoint", "decision_request", "evidence", "usage"}
        if not isinstance(outcome, dict) or set(outcome) != fields:
            raise _Failure("worker_protocol_invalid")
        status, code, usage = (outcome[key] for key in ("status", "failure_code", "usage"))
        if (
            not isinstance(status, str) or status not in _OUTCOME_STATES
            or (code is not None and (not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", code)))
            or not isinstance(usage, dict) or set(usage) != {"model_calls", "tool_calls", "elapsed_seconds"}
            or type(usage["model_calls"]) is not int or not model_calls <= usage["model_calls"] <= limits["max_model_calls"]
            or type(usage["tool_calls"]) is not int or not 0 <= usage["tool_calls"] <= limits["max_tool_calls"]
            or not _number(usage["elapsed_seconds"], 0, limits["max_elapsed_seconds"])
            or any(outcome[key] is not None and not isinstance(outcome[key], dict)
                   for key in ("checkpoint", "decision_request", "evidence"))
            or (status.startswith("waiting_") and (not outcome["checkpoint"] or not outcome["decision_request"]))
            or (status == "candidate" and not outcome["evidence"])
        ):
            raise _Failure("worker_protocol_invalid")
        return outcome

    def _attempt(self, attempt_id):
        if not isinstance(attempt_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", attempt_id):
            raise ValueError("invalid attempt id")
        return _Attempt(self.work_root, attempt_id)

    @staticmethod
    def _outcome(status, code, usage):
        return {
            "status": status, "failure_code": code, "checkpoint": None, "decision_request": None,
            "evidence": None, "usage": usage,
        }

    def run(self, job, repository, finalize):
        """Run a claimed attempt and finalize only after positive stop evidence."""
        empty_usage = {"model_calls": 0, "tool_calls": 0, "elapsed_seconds": 0}
        limits = job["limits"]
        if (
            not _number(limits.get("max_elapsed_seconds"), 0.000001, 86400)
            or any(type(limits.get(key)) is not int or not 0 <= limits[key] <= 10000
                   for key in ("max_model_calls", "max_tool_calls"))
        ):
            return self._outcome("blocked", "invalid_attempt_limits", empty_usage)
        began = time.monotonic()
        deadline = began + limits["max_elapsed_seconds"]
        # Refuse before creating a work root or opening a journal in an original.
        try:
            repository = Path(repository).resolve(strict=True)
        except (OSError, ValueError):
            return self._outcome("blocked", "registered_project_unavailable", empty_usage)
        if os.name == "nt" and repository.drive.startswith("\\\\"):
            return self._outcome("blocked", "nonlocal_project_path", empty_usage)
        if self.work_root.is_relative_to(repository) or repository.is_relative_to(self.work_root):
            return self._outcome("blocked", "overlapping_project_and_runtime", empty_usage)
        attempt = self._attempt(job["attempt_id"])
        with attempt.lease() as owned:
            if not owned or attempt.read() is not None:
                return self._outcome("interrupted", "attempt_already_registered", None)
            attempt.write("idle")
            base, candidate, engine = (attempt.scratch / name for name in ("base", "candidate", "engine"))
            outcome, failure, launched = None, None, False
            try:
                _check_clock(deadline, attempt.cancelled)
                for executable in (self._docker, self._git):
                    if executable and Path(executable).is_relative_to(repository):
                        raise _Failure("untrusted_host_executable", "blocked")
                self._admit(deadline, attempt.cancelled)
                attempt.scratch.mkdir(mode=0o700)
                stage = _stage_repository(self._git, repository, job["base_revision"], base,
                                          deadline, attempt.cancelled, self.work_root)
                self._engine_copy(engine, deadline, attempt.cancelled)
                container = self._create(attempt, engine, "/engine", "/engine", ("-I", "-B", "-u", "-c", _BOOT), deadline)
                bridge = _Bridge(limits["max_model_calls"], deadline, attempt.cancelled)
                launched = True
                outcome = self._worker_io(attempt, container, job, stage, candidate, bridge, deadline)
            except _Failure as exc:
                failure = exc
            except (OSError, ValueError, TypeError, KeyError, RecursionError):
                failure = _Failure("worker_protocol_invalid" if launched else "runtime_preparation_failed",
                                   "failed" if launched else "blocked")
            finally:
                confirmed = self._gone(attempt)
            if not confirmed:
                return self._outcome("interrupted", "worker_stop_unconfirmed", None)

            usage = outcome["usage"] if outcome is not None else {
                "model_calls": limits["max_model_calls"] if launched else 0,
                "tool_calls": limits["max_tool_calls"] if launched else 0,
                "elapsed_seconds": 0,
            }
            if failure is None and outcome["status"] == "candidate":
                try:
                    _check_clock(deadline, attempt.cancelled)
                    self._current.attempt = (attempt, deadline)
                    result = finalize(base, candidate, outcome)
                    if not isinstance(result, dict):
                        raise ValueError("invalid finalizer result")
                    _check_clock(deadline, attempt.cancelled)
                    outcome = dict(outcome, status="verified", result=result)
                except _Failure as exc:
                    failure = exc
                except ValueError:
                    failure = _Failure("candidate_verification_failed")
                except Exception:
                    failure = _Failure("finalization_failed")
                finally:
                    self._current.attempt = None
            if not self._gone(attempt):
                return self._outcome("interrupted", "worker_stop_unconfirmed", None)

            attempt.write("stopped")
            shutil.rmtree(attempt.scratch, ignore_errors=True)
            usage["elapsed_seconds"] = min(
                limits["max_elapsed_seconds"], max(usage["elapsed_seconds"], time.monotonic() - began),
            )
            if attempt.cancelled():
                return self._outcome("cancelled", "attempt_cancelled", usage)
            if time.monotonic() >= deadline:
                return self._outcome("timed_out", "attempt_deadline", usage)
            if failure is not None:
                return self._outcome(failure.status, failure.code, usage)
            return outcome

    def cancel(self, attempt_id):
        """Fence future launch, then report whether the attempt is fully stopped."""
        try:
            self._attempt(attempt_id).request_cancel()
        except (ValueError, OSError):
            return False
        return self.stopped(attempt_id)

    def stopped(self, attempt_id):
        """Reconcile a known attempt, without racing a launcher or its finalizer."""
        try:
            attempt = self._attempt(attempt_id)
            if not attempt.path.is_dir():
                return False
            with attempt.lease() as owned:
                if not owned or not self._gone(attempt):
                    return False
                attempt.write("stopped")
                shutil.rmtree(attempt.scratch, ignore_errors=True)
                return True
        except (ValueError, OSError, TypeError):
            return False

    def check(self, workspace, argv, *, timeout=10):
        """Run trusted ``['python', '-B', '<project-script>.py', ...]`` oracle argv.

        Use only synchronously inside this runtime's finalizer. The project is
        mounted read-only, stdin is closed, no provider bridge is present, and
        stdout/stderr are exact bounded bytes, not a verification decision.
        """
        active = getattr(self._current, "attempt", None)
        if active is None:
            raise ValueError("oracle requires an active trusted finalizer")
        attempt, attempt_deadline = active
        if (
            not _number(timeout, 0.000001, 30) or not isinstance(argv, (list, tuple))
            or not 3 <= len(argv) <= 16 or argv[0:2] not in (["python", "-B"], ("python", "-B"))
            or any(not isinstance(arg, str) or not re.fullmatch(r"[A-Za-z0-9_./ -]{1,256}", arg)
                   for arg in argv[2:])
            or argv[2].startswith("-") or not argv[2].endswith(".py")
        ):
            raise ValueError("oracle argv is not allowlisted")
        deadline = min(attempt_deadline, time.monotonic() + timeout)
        try:
            workspace = Path(workspace).absolute()
            if (
                workspace != workspace.resolve(strict=True) or not workspace.is_relative_to(attempt.scratch)
                or workspace == attempt.scratch
                or workspace.relative_to(attempt.scratch).parts[0] in {"base", "candidate", "engine"}
                or attempt.read() != {"phase": "idle"}
            ):
                raise ValueError("oracle workspace is not an independent disposable project")
            script = "/".join(_path_parts(argv[2]))
            found = False
            for path, _, _data in _files(workspace):
                _check_clock(deadline, attempt.cancelled)
                found |= path == script
            if not found:
                raise ValueError("oracle script is not a regular project file")
            command = _oracle_command("/project/" + script, argv[3:])
            container = self._create(attempt, workspace, "/project", "/project", command, deadline)
            attempt.write("launching", name=attempt.read()["name"], container=container)
            process = _capture(self._docker_argv("start", "-a", "-i", container), _host_environment(),
                               self.work_root, deadline, attempt.cancelled)
            exit_code = self._exit_code(container, deadline, attempt.cancelled)
            if process.returncode != exit_code:
                raise ValueError("oracle exit code mismatch")
        except (_Failure, OSError):
            raise ValueError("isolated oracle did not complete") from None
        finally:
            if not self._gone(attempt):
                raise ValueError("isolated oracle stop unconfirmed")
        return {"exit_code": exit_code, "stdout": process.stdout, "stderr": process.stderr}
