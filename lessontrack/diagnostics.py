"""Structured, privacy-conscious run traces, retained independently of email."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import time
import traceback
from uuid import uuid4

_run = ContextVar("lessontrack_run", default=None)


class Problem(RuntimeError):
    """A stable diagnostic code; never pass a provider response or secret here."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def reference(value):
    return sha256(str(value).encode()).hexdigest()[:16]


def error_details(exc):
    # Do not log exception messages, source lines, locals, URLs or response bodies.
    result = {"error_type": type(exc).__name__, "code": getattr(exc, "code", "unexpected_error")}
    result["trace"] = [
        {"file": Path(f.filename).name, "line": f.lineno, "function": f.name}
        for f in traceback.extract_tb(exc.__traceback__)
    ]
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        result["http_status"] = status
    smtp_code = getattr(exc, "smtp_code", None)
    if isinstance(smtp_code, int):
        result["smtp_code"] = smtp_code
    return result


def event(name, level="INFO", **fields):
    """Call with controlled metadata only; never names, addresses or narrative text."""
    run = _run.get()
    if run is not None:
        run.emit(name, level, **fields)


@contextmanager
def stage(name, **fields):
    started = time.monotonic()
    event("stage_started", stage=name, **fields)
    try:
        yield
    except Exception as exc:
        event(
            "stage_failed",
            "ERROR",
            stage=name,
            duration_ms=round((time.monotonic() - started) * 1000),
            **fields,
            **error_details(exc),
        )
        raise
    else:
        event("stage_completed", stage=name, duration_ms=round((time.monotonic() - started) * 1000), **fields)


class Run:
    def __init__(self, job, mode, root=Path(".lessontrack/runs")):
        self.id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:12]
        self.job, self.mode = job, mode
        self.directory = Path(root) / self.id
        self.counts = {"WARNING": 0, "ERROR": 0}

    def __enter__(self):
        self.directory.mkdir(parents=True, exist_ok=False)
        self.stream = (self.directory / "events.jsonl").open("x", encoding="utf-8")
        self.token = _run.set(self)
        self.started = time.monotonic()
        self.emit(
            "run_started",
            git_sha=os.getenv("GITHUB_SHA", "local"),
            action_run_id=os.getenv("GITHUB_RUN_ID", "local"),
        )
        return self

    def emit(self, name, level="INFO", **fields):
        row = {
            "time": datetime.now(timezone.utc).isoformat(),
            "run_id": self.id,
            "job": self.job,
            "mode": self.mode,
            "event": name,
            "level": level,
            **fields,
        }
        text = json.dumps(row, ensure_ascii=True, allow_nan=False)
        self.stream.write(text + "\n")
        self.stream.flush()
        print(text, flush=True)
        if level in self.counts:
            self.counts[level] += 1

    def __exit__(self, kind, exc, tb):
        try:
            if exc is not None:
                self.emit("run_failed", "ERROR", **error_details(exc))
            else:
                self.emit("run_completed")
            result = {
                "run_id": self.id,
                "job": self.job,
                "mode": self.mode,
                "status": "failed" if exc else "completed",
                "duration_ms": round((time.monotonic() - self.started) * 1000),
                **self.counts,
            }
            (self.directory / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            summary = os.getenv("GITHUB_STEP_SUMMARY")
            if summary:
                with open(summary, "a", encoding="utf-8") as f:
                    f.write(
                        f"\nLessonTrack {self.job}: **{result['status']}**\n\nRun ID: `{self.id}`\n\n"
                        f"Warnings: {self.counts['WARNING']}; errors: {self.counts['ERROR']}. "
                        "Download the diagnostics artifact for stage and row references.\n"
                    )
        finally:
            self.stream.close()
            _run.reset(self.token)
        return False
