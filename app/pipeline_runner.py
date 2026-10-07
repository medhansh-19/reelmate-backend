"""Killable process boundary for untrusted local media analysis."""

from __future__ import annotations

import multiprocessing
import os
import queue
import signal
import time
from collections.abc import Callable
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import Any

from app.pipeline import (
    MediaValidationError,
    PipelineDependencyError,
    PipelineError,
    PipelineV1,
    run_pipeline,
)

PipelineCallable = Callable[..., PipelineV1]


def _pipeline_child(
    result_queue: Any,
    runner: PipelineCallable,
    video_path: str,
    workspace_root: str,
    max_frames: int,
    ffmpeg_binary: str,
    ffprobe_binary: str,
) -> None:
    """Run in a spawned child and return only schema data or a stable code."""

    if hasattr(os, "setsid"):
        os.setsid()
    try:
        result = runner(
            video_path,
            workspace_root=workspace_root,
            max_frames=max_frames,
            ffmpeg_binary=ffmpeg_binary,
            ffprobe_binary=ffprobe_binary,
        )
        result_queue.put(("ok", result.model_dump_json()))
    except MediaValidationError as exc:
        result_queue.put(("media", exc.code))
    except PipelineDependencyError:
        result_queue.put(("dependency", "PIPELINE_DEPENDENCY_MISSING"))
    except PipelineError as exc:
        result_queue.put(("pipeline", exc.code))
    except BaseException:
        # Child exception details may include filenames or library internals.
        result_queue.put(("pipeline", "PIPELINE_PROCESS_FAILED"))


def _terminate_process_tree(process: BaseProcess) -> None:
    """Terminate the child process group so active FFmpeg children do not escape."""

    if not process.is_alive():
        process.join(timeout=1.0)
        return
    pid = process.pid
    if hasattr(os, "killpg") and pid is not None:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    else:  # pragma: no cover - production image is Linux
        process.terminate()
    process.join(timeout=3.0)
    if process.is_alive():
        if hasattr(os, "killpg") and pid is not None:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:  # pragma: no cover - production image is Linux
            process.kill()
        process.join(timeout=2.0)


def _context(start_method: str) -> Any:
    try:
        return multiprocessing.get_context(start_method)
    except ValueError as exc:
        raise ValueError(f"Unsupported multiprocessing start method: {start_method}") from exc


def run_pipeline_isolated(
    video_path: str | Path,
    *,
    workspace_root: str | Path,
    timeout_seconds: float,
    max_frames: int = 24,
    ffmpeg_binary: str = "ffmpeg",
    ffprobe_binary: str = "ffprobe",
    start_method: str = "spawn",
    runner: PipelineCallable = run_pipeline,
) -> PipelineV1:
    """Run PipelineV1 in a process that is forcibly ended at the hard timeout."""

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if max_frames <= 0:
        raise ValueError("max_frames must be positive")

    context = _context(start_method)
    result_queue = context.Queue(maxsize=1)
    process = context.Process(
        target=_pipeline_child,
        args=(
            result_queue,
            runner,
            str(video_path),
            str(workspace_root),
            max_frames,
            ffmpeg_binary,
            ffprobe_binary,
        ),
        name="reelmate-pipeline",
    )
    deadline = time.monotonic() + timeout_seconds
    process.start()
    message: tuple[str, str] | None = None
    timed_out = False
    try:
        while message is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            try:
                raw_message = result_queue.get(timeout=min(0.2, remaining))
            except queue.Empty:
                if not process.is_alive():
                    break
                continue
            if (
                isinstance(raw_message, tuple)
                and len(raw_message) == 2
                and all(isinstance(value, str) for value in raw_message)
            ):
                message = raw_message
            else:
                message = ("pipeline", "PIPELINE_PROCESS_FAILED")
    finally:
        if timed_out or process.is_alive():
            _terminate_process_tree(process)
        else:
            process.join(timeout=1.0)
        result_queue.close()
        result_queue.join_thread()

    if timed_out:
        raise PipelineError(
            "Local media analysis exceeded the configured job timeout.",
            code="PIPELINE_TIMEOUT",
        )
    if message is None:
        raise PipelineError(
            "The isolated media process exited without a result.",
            code="PIPELINE_PROCESS_FAILED",
        )

    kind, payload = message
    if kind == "ok":
        try:
            return PipelineV1.model_validate_json(payload)
        except (ValueError, TypeError) as exc:
            raise PipelineError(
                "The isolated media process returned an invalid result.",
                code="PIPELINE_RESULT_INVALID",
            ) from exc
    if kind == "media":
        raise MediaValidationError("The uploaded media is invalid.", code=payload)
    if kind == "dependency":
        raise PipelineDependencyError(
            "worker media dependency",
            "Install the dependencies included in the ReelMate production image.",
        )
    raise PipelineError("Local media analysis failed.", code=payload)


__all__ = ["run_pipeline_isolated"]
