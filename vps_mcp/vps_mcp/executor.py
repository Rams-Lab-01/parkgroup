"""Run a command on the VPS (SSH) or locally (tests, or when the server itself runs on the box)."""

from __future__ import annotations

import asyncio
import shlex
from dataclasses import dataclass
from typing import Protocol

from .config import Settings


class ExecError(Exception):
    """The command could not be run (connection, host key, timeout)."""


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    exit_status: int | None
    truncated: bool = False
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_status == 0 and not self.timed_out


def sh(*argv: str) -> str:
    """Quote an argv list into one shell-safe command string. Every dynamic value goes through here."""
    return shlex.join(argv)


class Executor(Protocol):
    async def run(self, command: str, *, stdin: str | None = None, timeout: float = 60.0,
                  max_bytes: int = 60_000) -> ExecResult: ...

    async def close(self) -> None: ...


class _Capture:
    """Collects a stream up to a byte cap while keeping partial output available after a timeout."""

    def __init__(self, cap: int):
        self.cap = cap
        self.chunks: list[str] = []
        self.size = 0
        self.truncated = False

    async def pump(self, stream) -> None:
        while True:
            data = await stream.read(8192)
            if not data:
                return
            if isinstance(data, bytes):
                data = data.decode("utf-8", "replace")
            if self.size + len(data) > self.cap:
                self.chunks.append(data[: max(self.cap - self.size, 0)])
                self.truncated = True
                return
            self.chunks.append(data)
            self.size += len(data)

    @property
    def text(self) -> str:
        return "".join(self.chunks)


async def _collect(stdout, stderr, *, timeout: float, cap: int) -> tuple[str, str, bool, bool]:
    """Returns (stdout, stderr, truncated, timed_out). Stops as soon as stdout ends or hits the cap; stderr only
    gets a short grace period, so a flood of output can never keep us waiting for the full timeout."""
    out, err = _Capture(cap), _Capture(max(cap // 4, 1000))
    out_task = asyncio.ensure_future(out.pump(stdout))
    err_task = asyncio.ensure_future(err.pump(stderr))
    timed_out = False
    try:
        await asyncio.wait_for(asyncio.shield(out_task), timeout)
        if not out.truncated:
            await asyncio.wait_for(asyncio.shield(err_task), min(timeout, 5))
    except asyncio.TimeoutError:
        timed_out = not out_task.done()
    finally:
        for task in (out_task, err_task):
            if not task.done():
                task.cancel()
    return out.text, err.text, out.truncated, timed_out


class SSHExecutor:
    """One reusable SSH connection. Host keys are always verified against VPS_KNOWN_HOSTS; password logins and
    agent forwarding are never used."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._conn = None
        self._lock = asyncio.Lock()

    async def _connect(self):
        import asyncssh
        s = self.settings
        try:
            return await asyncssh.connect(
                s.host, port=s.port, username=s.user, client_keys=[s.key_path], passphrase=s.key_passphrase,
                known_hosts=s.known_hosts, agent_path=None, password=None, connect_timeout=15,
                keepalive_interval=30, keepalive_count_max=3)
        except asyncssh.HostKeyNotVerifiable as exc:
            raise ExecError("Host key verification FAILED: the server's key does not match VPS_KNOWN_HOSTS. "
                            "Refusing to connect (possible man-in-the-middle, or the server was rebuilt).") from exc
        except asyncssh.PermissionDenied as exc:
            raise ExecError("SSH authentication refused for this user/key.") from exc
        except (OSError, asyncssh.Error, asyncio.TimeoutError) as exc:
            raise ExecError(f"Could not connect to {s.host}:{s.port}: {exc}") from exc

    async def _connection(self):
        async with self._lock:
            if self._conn is None or self._conn.is_closed():
                self._conn = await self._connect()
            return self._conn

    async def run(self, command: str, *, stdin: str | None = None, timeout: float = 60.0,
                  max_bytes: int = 60_000) -> ExecResult:
        conn = await self._connection()
        process = await conn.create_process(command, encoding=None)
        # Always close stdin explicitly (even with no input): an empty `input=` does NOT send EOF in asyncssh,
        # and anything reading stdin (psql -f -, docker exec -i) would then wait forever.
        if stdin:
            process.stdin.write(stdin.encode())
        process.stdin.write_eof()
        out, err, truncated, timed_out = await _collect(process.stdout, process.stderr, timeout=timeout, cap=max_bytes)
        if timed_out or truncated:
            process.terminate()
            process.close()
            return ExecResult(out, err, None, truncated=truncated, timed_out=timed_out)
        try:
            await asyncio.wait_for(process.wait(), 10)
        except asyncio.TimeoutError:
            process.terminate()
        return ExecResult(out, err, process.exit_status)

    async def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            await self._conn.wait_closed()
            self._conn = None


class LocalExecutor:
    """Runs commands with /bin/sh on this machine (tests, or the server deployed on the VPS itself)."""

    def __init__(self, env: dict[str, str] | None = None):
        self.env = env

    async def run(self, command: str, *, stdin: str | None = None, timeout: float = 60.0,
                  max_bytes: int = 60_000) -> ExecResult:
        proc = await asyncio.create_subprocess_exec(
            "/bin/sh", "-c", command, stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=self.env)
        if stdin is not None:
            proc.stdin.write(stdin.encode())
            await proc.stdin.drain()
            proc.stdin.close()
        out, err, truncated, timed_out = await _collect(proc.stdout, proc.stderr, timeout=timeout, cap=max_bytes)
        if timed_out or truncated:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
            return ExecResult(out, err, None, truncated=truncated, timed_out=timed_out)
        return ExecResult(out, err, await proc.wait())

    async def close(self) -> None:
        return None
