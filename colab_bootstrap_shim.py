"""Minimal Colab boot shim.

Updated for iFlow + Kimi + Qwen.
"""

import os
import pathlib
import subprocess
import sys
from typing import Optional

from google.colab import userdata  # type: ignore
from google.colab import drive  # type: ignore


def get_secret(name: str, required: bool = False) -> Optional[str]:
    v = None
    try:
        v = userdata.get(name)
    except Exception:
        v = None
    if v is None or str(v).strip() == "":
        v = os.environ.get(name)
    if required:
        assert v is not None and str(v).strip() != "", f"Missing required secret: {name}"
    return v


def export_secret_to_env(name: str, required: bool = False) -> Optional[str]:
    val = get_secret(name, required=required)
    if val is not None and str(val).strip() != "":
        os.environ[name] = str(val)
    return val


# Export required runtime secrets
for _name in ("TELEGRAM_BOT_TOKEN", "TOTAL_BUDGET", "GITHUB_TOKEN"):
    export_secret_to_env(_name, required=True)

# API Key (FlowAI / iFlow is required; OpenRouter is no longer used)
iflow_key = export_secret_to_env("IFLOW_API_KEY", required=True)

# Optional secrets
for _name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
    export_secret_to_env(_name, required=False)

# Export configuration variables (required for launcher subprocess)
for _name in (
    "GITHUB_USER",
    "GITHUB_REPO",
    "OUROBOROS_MODEL",
    "OUROBOROS_MODEL_CODE",
    "OUROBOROS_MODEL_LIGHT",
    "OUROBOROS_MAX_WORKERS",
    "OUROBOROS_SOFT_TIMEOUT_SEC",
    "OUROBOROS_HARD_TIMEOUT_SEC",
    "OUROBOROS_DIAG_HEARTBEAT_SEC",
    "OUROBOROS_DIAG_SLOW_CYCLE_SEC",
):
    export_secret_to_env(_name, required=False)

# Colab diagnostics
os.environ.setdefault("OUROBOROS_WORKER_START_METHOD", "fork")
os.environ.setdefault("PYTHONUNBUFFERED", "1")

GITHUB_TOKEN = str(os.environ["GITHUB_TOKEN"])
GITHUB_USER = os.environ.get("GITHUB_USER", "Aisrefot-Reed").strip()
GITHUB_REPO = os.environ.get("GITHUB_REPO", "ouroboros").strip()
BOOT_BRANCH = str(os.environ.get("OUROBOROS_BOOT_BRANCH", "ouroboros"))

REPO_DIR = pathlib.Path("/content/ouroboros_repo").resolve()
REMOTE_URL = f"https://{GITHUB_TOKEN}:x-oauth-basic@github.com/{GITHUB_USER}/{GITHUB_REPO}.git"

# Set up repo
if not (REPO_DIR / ".git").exists():
    subprocess.run(["rm", "-rf", str(REPO_DIR)], check=False)
    subprocess.run(["git", "clone", REMOTE_URL, str(REPO_DIR)], check=True)
else:
    subprocess.run(["git", "remote", "set-url", "origin", REMOTE_URL], cwd=str(REPO_DIR), check=True)

subprocess.run(["git", "fetch", "origin"], cwd=str(REPO_DIR), check=True)

# Defensive branch management
# Check if the branch exists on remote
result = subprocess.run(
    ["git", "ls-remote", "--heads", "origin", BOOT_BRANCH],
    cwd=str(REPO_DIR), capture_output=True, text=True
)

if BOOT_BRANCH in result.stdout:
    # Branch exists on remote, force local to match it
    print(f"[boot] syncing local {BOOT_BRANCH} with origin/{BOOT_BRANCH}")
    subprocess.run(["git", "checkout", "-B", BOOT_BRANCH, f"origin/{BOOT_BRANCH}"], cwd=str(REPO_DIR), check=True)
else:
    # Branch doesn't exist, create it from current HEAD (which is main after clone)
    print(f"[boot] branch {BOOT_BRANCH} not found on remote — creating from main")
    subprocess.run(["git", "checkout", "-B", BOOT_BRANCH], cwd=str(REPO_DIR), check=True)
    subprocess.run(["git", "push", "-u", "origin", BOOT_BRANCH], cwd=str(REPO_DIR), check=True)
    
    # Create stable branch too
    _STABLE = f"{BOOT_BRANCH}-stable"
    subprocess.run(["git", "checkout", "-B", _STABLE], cwd=str(REPO_DIR), check=True)
    subprocess.run(["git", "push", "-u", "origin", _STABLE], cwd=str(REPO_DIR), check=True)
    subprocess.run(["git", "checkout", BOOT_BRANCH], cwd=str(REPO_DIR), check=True)

HEAD_SHA = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(REPO_DIR), text=True).strip()
print(f"[boot] branch={BOOT_BRANCH} sha={HEAD_SHA[:12]}")

# Mount Drive **BEFORE** launching launcher (critical for subprocess context)
drive_path = pathlib.Path("/content/drive/MyDrive")
if not drive_path.exists():
    print("[boot] mounting Google Drive...")
    drive.mount("/content/drive", force_remount=True)
else:
    print("[boot] Google Drive already mounted")

# Verify Drive is mounted
if not drive_path.exists():
    raise RuntimeError("Failed to mount Google Drive")

print("[boot] Drive mounted successfully")

# Now launch launcher with better error handling
launcher_path = REPO_DIR / "colab_launcher.py"
print(f"[boot] Launching {launcher_path}...")
try:
    result = subprocess.run(
        [sys.executable, str(launcher_path)],
        cwd=str(REPO_DIR),
        check=True,
        capture_output=True,
        text=True
    )
    print(f"[boot] Launcher completed successfully")
except subprocess.CalledProcessError as e:
    print(f"[boot] Launcher failed with exit code {e.returncode}")
    print(f"[boot] STDOUT:\n{e.stdout}")
    print(f"[boot] STDERR:\n{e.stderr}")
    raise
