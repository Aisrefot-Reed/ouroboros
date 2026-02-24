"""Shell tools: run_shell, qwen_code_edit."""

from __future__ import annotations

import json
import logging
import os
import pathlib
import shlex
import shutil
import subprocess
from typing import Any, Dict, List

from ouroboros.tools.registry import ToolContext, ToolEntry
from ouroboros.utils import utc_now_iso, run_cmd, append_jsonl, truncate_for_log

log = logging.getLogger(__name__)


def _run_shell(ctx: ToolContext, cmd, cwd: str = "") -> str:
    # Recover from LLM sending cmd as JSON string instead of list
    if isinstance(cmd, str):
        raw_cmd = cmd
        warning = "run_shell_cmd_string"
        try:
            parsed = json.loads(cmd)
            if isinstance(parsed, list):
                cmd = parsed
                warning = "run_shell_cmd_string_json_list_recovered"
            elif isinstance(parsed, str):
                try:
                    cmd = shlex.split(parsed)
                except ValueError:
                    cmd = parsed.split()
                warning = "run_shell_cmd_string_json_string_split"
            else:
                try:
                    cmd = shlex.split(cmd)
                except ValueError:
                    cmd = cmd.split()
                warning = "run_shell_cmd_string_json_non_list_split"
        except Exception:
            try:
                cmd = shlex.split(cmd)
            except ValueError:
                cmd = cmd.split()
            warning = "run_shell_cmd_string_split_fallback"

        try:
            append_jsonl(ctx.drive_logs() / "events.jsonl", {
                "ts": utc_now_iso(),
                "type": "tool_warning",
                "tool": "run_shell",
                "warning": warning,
                "cmd_preview": truncate_for_log(raw_cmd, 500),
            })
        except Exception:
            log.debug("Failed to log run_shell warning to events.jsonl", exc_info=True)
            pass

    if not isinstance(cmd, list):
        return "⚠️ SHELL_ARG_ERROR: cmd must be a list of strings."
    cmd = [str(x) for x in cmd]

    work_dir = ctx.repo_dir
    if cwd and cwd.strip() not in ("", ".", "./"):
        candidate = (ctx.repo_dir / cwd).resolve()
        if candidate.exists() and candidate.is_dir():
            work_dir = candidate

    try:
        res = subprocess.run(
            cmd, cwd=str(work_dir),
            capture_output=True, text=True, timeout=120,
        )
        out = res.stdout + ("\n--- STDERR ---\n" + res.stderr if res.stderr else "")
        if len(out) > 50000:
            out = out[:25000] + "\n...(truncated)...\n" + out[-25000:]
        prefix = f"exit_code={res.returncode}\n"
        return prefix + out
    except subprocess.TimeoutExpired:
        return "⚠️ TIMEOUT: command exceeded 120s."
    except Exception as e:
        return f"⚠️ SHELL_ERROR: {e}"


def _run_qwen_cli(work_dir: str, prompt: str, env: dict) -> subprocess.CompletedProcess:
    """Run Qwen CLI for code editing."""
    # Using the exact model ID for iFlow: Qwen3-Coder-Plus (or Qwen3-Coder-480B-A35B-Instruct)
    # The user found it on the iFlow model platform.
    qwen_bin = shutil.which("qwen")
    
    if not qwen_bin:
        return subprocess.CompletedProcess(
            args=["qwen"], returncode=127, stdout="", 
            stderr="⚠️ 'qwen' CLI not found in PATH."
        )

    # Calling qwen with the specific model for code editing
    cmd = [qwen_bin, "edit", "--model", "Qwen3-Coder-Plus", "--prompt", prompt, "--path", work_dir]

    res = subprocess.run(
        cmd, cwd=work_dir,
        capture_output=True, text=True, timeout=300, env=env,
    )
    return res


def _check_uncommitted_changes(repo_dir: pathlib.Path) -> str:
    """Check git status after edit, return warning string or empty string."""
    try:
        status_res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if status_res.returncode == 0 and status_res.stdout.strip():
            diff_res = subprocess.run(
                ["git", "diff", "--stat"],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if diff_res.returncode == 0 and diff_res.stdout.strip():
                return (
                    f"\n\n⚠️ UNCOMMITTED CHANGES detected after Qwen Coder edit:\n"
                    f"{diff_res.stdout.strip()}\n"
                    f"Remember to run git_status and repo_commit_push!"
                )
    except Exception as e:
        log.debug("Failed to check git status after qwen_code_edit: %s", e, exc_info=True)
    return ""


def _parse_qwen_output(stdout: str, ctx: ToolContext) -> str:
    """Parse Qwen output and emit cost event, return result string."""
    # Qwen CLI might not return JSON by default like Claude, 
    # so we treat it as text unless it looks like JSON.
    try:
        payload = json.loads(stdout)
        return json.dumps(payload, ensure_ascii=False, indent=2)
    except Exception:
        return stdout


def _qwen_code_edit(ctx: ToolContext, prompt: str, cwd: str = "") -> str:
    """Delegate code edits to Qwen Coder CLI."""
    from ouroboros.tools.git import _acquire_git_lock, _release_git_lock

    # Use IFLOW_API_KEY or other relevant key if needed by the CLI
    api_key = os.environ.get("IFLOW_API_KEY", "")

    work_dir = str(ctx.repo_dir)
    if cwd and cwd.strip() not in ("", ".", "./"):
        candidate = (ctx.repo_dir / cwd).resolve()
        if candidate.exists():
            work_dir = str(candidate)

    ctx.emit_progress_fn("Delegating to Qwen Coder CLI...")

    lock = _acquire_git_lock(ctx)
    try:
        try:
            run_cmd(["git", "checkout", ctx.branch_dev], cwd=ctx.repo_dir)
        except Exception as e:
            return f"⚠️ GIT_ERROR (checkout): {e}"

        full_prompt = (
            f"STRICT: Only modify files inside {work_dir}. "
            f"Git branch: {ctx.branch_dev}. Do NOT commit or push.\n\n"
            f"{prompt}"
        )

        env = os.environ.copy()
        # Ensure the CLI has access to the API key if it needs to call home
        if os.environ.get("IFLOW_API_KEY"):
            env["OPENAI_API_KEY"] = os.environ["IFLOW_API_KEY"]
            env["OPENAI_BASE_URL"] = "https://apis.iflow.cn/v1"
            
        res = _run_qwen_cli(work_dir, full_prompt, env)

        stdout = (res.stdout or "").strip()
        stderr = (res.stderr or "").strip()
        if res.returncode != 0:
            return f"⚠️ QWEN_CODE_ERROR: exit={res.returncode}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
        
        result_text = stdout or "OK: Qwen Coder completed."

        # Check for uncommitted changes
        warning = _check_uncommitted_changes(ctx.repo_dir)
        if warning:
            result_text += warning

        return _parse_qwen_output(result_text, ctx)

    except subprocess.TimeoutExpired:
        return "⚠️ QWEN_CODE_TIMEOUT: exceeded 300s."
    except Exception as e:
        return f"⚠️ QWEN_CODE_FAILED: {type(e).__name__}: {e}"
    finally:
        _release_git_lock(lock)


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry("run_shell", {
            "name": "run_shell",
            "description": "Run a shell command (list of args) inside the repo. Returns stdout+stderr.",
            "parameters": {"type": "object", "properties": {
                "cmd": {"type": "array", "items": {"type": "string"}},
                "cwd": {"type": "string", "default": ""},
            }, "required": ["cmd"]},
        }, _run_shell, is_code_tool=True),
        ToolEntry("qwen_code_edit", {
            "name": "qwen_code_edit",
            "description": "Delegate code edits to Qwen Coder CLI. Preferred for multi-file changes and refactors. Follow with repo_commit_push.",
            "parameters": {"type": "object", "properties": {
                "prompt": {"type": "string"},
                "cwd": {"type": "string", "default": ""},
            }, "required": ["prompt"]},
        }, _qwen_code_edit, is_code_tool=True, timeout_sec=300),
    ]
