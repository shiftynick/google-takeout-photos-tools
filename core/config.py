"""Configuration management for Google Photos Explorer.

Stores configuration in the user's home directory at:
  ~/.gphoto_explorer/config.json

Environment variables can override stored values:
  - AZURE_STORAGE_CONNECTION_STRING
  - AZURE_STORAGE_CONTAINER
  - AZURE_STORAGE_PREFIX
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


class ConfigManager:
    """Simple JSON-backed configuration manager."""

    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or (Path.home() / ".gphoto_explorer")
        self.config_file = self.config_dir / "config.json"
        self._config: Dict[str, Any] = {
            "azure": {
                "connection_string": None,
                "container": None,
                "default_prefix": "",
            }
        }
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        try:
            if self.config_file.exists():
                with open(self.config_file, "r") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self._config.update(data)
        except Exception:
            # Ignore config load errors; use defaults
            pass
        finally:
            self._loaded = True

    def save(self) -> None:
        self.load()
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w") as f:
            json.dump(self._config, f, indent=2)

    # Generic getters/setters
    def get(self, *keys: str, default: Any = None) -> Any:
        self.load()
        node: Any = self._config
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def set(self, value: Any, *keys: str) -> None:
        self.load()
        node: Dict[str, Any] = self._config
        for key in keys[:-1]:
            if key not in node or not isinstance(node[key], dict):
                node[key] = {}
            node = node[key]  # type: ignore[assignment]
        node[keys[-1]] = value

    # Azure-specific helpers
    def get_azure_connection_string(self) -> Optional[str]:
        env_val = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if env_val:
            return env_val
        return self.get("azure", "connection_string")

    def set_azure_connection_string(self, connection_string: str) -> None:
        self.set(connection_string, "azure", "connection_string")
        self.save()

    def get_azure_container(self) -> Optional[str]:
        env_val = os.getenv("AZURE_STORAGE_CONTAINER")
        if env_val:
            return env_val
        return self.get("azure", "container")

    def set_azure_container(self, container: str) -> None:
        self.set(container, "azure", "container")
        self.save()

    def get_azure_default_prefix(self) -> str:
        env_val = os.getenv("AZURE_STORAGE_PREFIX")
        if env_val is not None:
            return env_val
        return self.get("azure", "default_prefix", default="") or ""

    def set_azure_default_prefix(self, prefix: str) -> None:
        self.set(prefix, "azure", "default_prefix")
        self.save()

    # Convenience
    def azure_is_configured(self) -> bool:
        return bool(self.get_azure_connection_string() and self.get_azure_container())
