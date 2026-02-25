"""Credentials management with Fernet encryption.

Secure storage for LinkedIn, Kwork, and other platform credentials.
"""

from __future__ import annotations

import base64
import json
import os
import pathlib
from typing import Any, Dict, List, Optional

from cryptography.fernet import Fernet
from ouroboros.tools.registry import ToolContext, ToolEntry


def _get_encryption_key(ctx: ToolContext) -> bytes:
    """Get or create encryption key from Drive."""
    key_path = ctx.drive_root() / "state" / "encryption.key"
    
    if key_path.exists():
        return key_path.read_bytes()
    else:
        key = Fernet.generate_key()
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_bytes(key)
        return key


def _get_credentials_path(ctx: ToolContext) -> pathlib.Path:
    """Get credentials storage path."""
    return ctx.drive_root() / "state" / "credentials.json"


def _load_credentials(ctx: ToolContext) -> Dict[str, Any]:
    """Load and decrypt credentials."""
    creds_path = _get_credentials_path(ctx)
    
    if not creds_path.exists():
        return {}
    
    try:
        key = _get_encryption_key(ctx)
        f = Fernet(key)
        encrypted_data = creds_path.read_bytes()
        decrypted_data = f.decrypt(encrypted_data)
        return json.loads(decrypted_data.decode('utf-8'))
    except Exception as e:
        return {"_error": str(e)}


def _save_credentials(ctx: ToolContext, credentials: Dict[str, Any]) -> bool:
    """Encrypt and save credentials."""
    try:
        key = _get_encryption_key(ctx)
        f = Fernet(key)
        creds_path = _get_credentials_path(ctx)
        
        # Serialize and encrypt
        json_data = json.dumps(credentials, ensure_ascii=False).encode('utf-8')
        encrypted_data = f.encrypt(json_data)
        
        # Atomic write
        creds_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = creds_path.with_suffix('.tmp')
        tmp_path.write_bytes(encrypted_data)
        tmp_path.rename(creds_path)
        
        return True
    except Exception as e:
        return False


def _store_credentials_impl(
    ctx: ToolContext,
    platform: str,
    email: str,
    password: str,
    extra_fields: Optional[str] = None
) -> str:
    """Store credentials for a platform."""
    credentials = _load_credentials(ctx)
    
    # Parse extra fields
    extra = {}
    if extra_fields:
        try:
            extra = json.loads(extra_fields)
        except json.JSONDecodeError:
            return f"⚠️ Invalid JSON in extra_fields"
    
    # Store credentials
    credentials[platform] = {
        "email": email,
        "password": password,
        "extra": extra,
        "updated_at": __import__('datetime').datetime.now().isoformat()
    }
    
    if _save_credentials(ctx, credentials):
        return f"✅ Credentials stored for {platform} (email: {email})"
    else:
        return "⚠️ Failed to store credentials"


def _manage_credentials_impl(
    ctx: ToolContext,
    action: str,
    platform: Optional[str] = None
) -> str:
    """Manage credentials (list, delete)."""
    credentials = _load_credentials(ctx)
    
    if "_error" in credentials:
        return f"⚠️ Error loading credentials: {credentials['_error']}"
    
    if action == "list":
        if not credentials:
            return "📭 No credentials stored"
        
        lines = ["📋 Stored credentials:"]
        for plat, data in credentials.items():
            email = data.get("email", "unknown")
            updated = data.get("updated_at", "unknown")
            lines.append(f"  • {plat}: {email} (updated: {updated})")
        
        return "\n".join(lines)
    
    elif action == "delete":
        if not platform:
            return "⚠️ Platform required for delete action"
        
        if platform in credentials:
            del credentials[platform]
            if _save_credentials(ctx, credentials):
                return f"✅ Credentials deleted for {platform}"
            else:
                return "⚠️ Failed to delete credentials"
        else:
            return f"⚠️ No credentials found for {platform}"
    
    elif action == "get":
        if not platform:
            return "⚠️ Platform required for get action"
        
        if platform in credentials:
            data = credentials[platform]
            return (
                f"📋 {platform} credentials:\n"
                f"  Email: {data.get('email', 'N/A')}\n"
                f"  Updated: {data.get('updated_at', 'N/A')}\n"
                f"  Extra: {json.dumps(data.get('extra', {}), indent=2)}"
            )
        else:
            return f"⚠️ No credentials found for {platform}"
    
    else:
        return f"⚠️ Unknown action: {action}. Use: list, get, delete"


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry("store_credentials", {
            "name": "store_credentials",
            "description": "Securely store credentials for a platform (LinkedIn, Kwork, etc.) with Fernet encryption.",
            "parameters": {"type": "object", "properties": {
                "platform": {"type": "string", "description": "Platform name (e.g., 'linkedin', 'kwork')"},
                "email": {"type": "string", "description": "Email/username"},
                "password": {"type": "string", "description": "Password"},
                "extra_fields": {"type": "string", "description": "Optional JSON with extra fields (e.g., phone, 2FA)"},
            }, "required": ["platform", "email", "password"]},
        }, _store_credentials_impl),
        
        ToolEntry("manage_credentials", {
            "name": "manage_credentials",
            "description": "Manage stored credentials: list all, get details, or delete.",
            "parameters": {"type": "object", "properties": {
                "action": {"type": "string", "description": "Action: list, get, delete"},
                "platform": {"type": "string", "description": "Platform name (required for get/delete)"},
            }, "required": ["action"]},
        }, _manage_credentials_impl),
    ]
