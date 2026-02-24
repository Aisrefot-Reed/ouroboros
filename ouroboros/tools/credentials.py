"""
Secure credential storage and management for external platforms.

Provides functionality to:
- Store encrypted credentials for platforms like LinkedIn and Kwork
- Retrieve credentials securely
- Manage multiple accounts for each platform
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List
from pathlib import Path
import base64
from cryptography.fernet import Fernet

from ouroboros.tools.registry import ToolContext, ToolEntry

log = logging.getLogger(__name__)


def _generate_key() -> bytes:
    """Generate a new encryption key. This should only be done once per installation."""
    return Fernet.generate_key()


def _get_credential_file_path(ctx: ToolContext) -> Path:
    """Get path to encrypted credential file."""
    return ctx.drive_path("credentials.encrypted")


def _get_cipher(ctx: ToolContext) -> Fernet:
    """Get a Fernet cipher for encryption/decryption."""
    # In a real implementation, we'd store a master key securely
    # For now, we'll use a key derived from the system for demo purposes
    # This is NOT secure for production use - production should use a proper key management system
    
    # For demo purposes, we'll use a key stored in the system
    key_path = ctx.drive_path("master.key")
    if not key_path.exists():
        # Generate a new key and save it (only once)
        key = _generate_key()
        key_path.write_bytes(key)
    else:
        key = key_path.read_bytes()
    
    return Fernet(key)


def _store_credentials(ctx: ToolContext, platform: str, credentials: Dict[str, str]) -> str:
    """
    Store encrypted credentials for a platform.
    
    Args:
        ctx: Tool context
        platform: Name of the platform ('linkedin', 'kwork', etc.)
        credentials: Dict containing credential data (email, password, etc.)
    
    Returns:
        Status message
    """
    try:
        credential_file = _get_credential_file_path(ctx)
        cipher = _get_cipher(ctx)
        
        # Load existing credentials if file exists
        existing_credentials = {}
        if credential_file.exists():
            encrypted_data = credential_file.read_bytes()
            decrypted_data = cipher.decrypt(encrypted_data)
            existing_credentials = json.loads(decrypted_data.decode())
        
        # Add new credentials
        existing_credentials[platform] = credentials
        
        # Encrypt and save
        data_to_encrypt = json.dumps(existing_credentials).encode()
        encrypted_data = cipher.encrypt(data_to_encrypt)
        credential_file.write_bytes(encrypted_data)
        
        return f"Successfully stored credentials for {platform}"
    except Exception as e:
        log.error(f"Error storing credentials: {e}")
        return f"Error storing credentials: {str(e)}"


def _get_credentials(ctx: ToolContext, platform: str) -> str:
    """
    Retrieve decrypted credentials for a platform.
    
    Args:
        ctx: Tool context
        platform: Name of the platform ('linkedin', 'kwork', etc.)
    
    Returns:
        JSON string containing credentials or error message
    """
    try:
        credential_file = _get_credential_file_path(ctx)
        cipher = _get_cipher(ctx)
        
        if not credential_file.exists():
            return f"No credentials file found for {platform}"
        
        # Decrypt and read credentials
        encrypted_data = credential_file.read_bytes()
        decrypted_data = cipher.decrypt(encrypted_data)
        all_credentials = json.loads(decrypted_data.decode())
        
        if platform not in all_credentials:
            return f"No credentials found for {platform}"
        
        return json.dumps(all_credentials[platform], indent=2)
    except Exception as e:
        log.error(f"Error retrieving credentials: {e}")
        return f"Error retrieving credentials: {str(e)}"


def _list_stored_platforms(ctx: ToolContext) -> str:
    """
    List all platforms with stored credentials.
    
    Args:
        ctx: Tool context
    
    Returns:
        JSON string listing platforms
    """
    try:
        credential_file = _get_credential_file_path(ctx)
        cipher = _get_cipher(ctx)
        
        if not credential_file.exists():
            return "[]"
        
        # Decrypt and read credentials
        encrypted_data = credential_file.read_bytes()
        decrypted_data = cipher.decrypt(encrypted_data)
        all_credentials = json.loads(decrypted_data.decode())
        
        return json.dumps(list(all_credentials.keys()), indent=2)
    except Exception as e:
        log.error(f"Error listing platforms: {e}")
        return f"Error listing platforms: {str(e)}"


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry(
            name="store_credentials",
            schema={
                "name": "store_credentials",
                "description": "Securely store encrypted credentials for a platform like LinkedIn or Kwork",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "platform": {"type": "string", "description": "Platform name (e.g., 'linkedin', 'kwork')"},
                        "credentials": {
                            "type": "object",
                            "description": "Credentials object with fields like email, password, etc.",
                            "properties": {
                                "email": {"type": "string", "description": "Email or username"},
                                "password": {"type": "string", "description": "Password"},
                                "api_token": {"type": "string", "description": "API token if available (optional)"}
                            }
                        }
                    },
                    "required": ["platform", "credentials"]
                }
            },
            handler=_store_credentials,
            timeout_sec=30
        ),
        ToolEntry(
            name="get_credentials",
            schema={
                "name": "get_credentials",
                "description": "Retrieve stored encrypted credentials for a platform",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "platform": {"type": "string", "description": "Platform name (e.g., 'linkedin', 'kwork')"}
                    },
                    "required": ["platform"]
                }
            },
            handler=_get_credentials,
            timeout_sec=30
        ),
        ToolEntry(
            name="list_stored_platforms",
            schema={
                "name": "list_stored_platforms",
                "description": "List all platforms with stored credentials",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            },
            handler=_list_stored_platforms,
            timeout_sec=30
        )
    ]