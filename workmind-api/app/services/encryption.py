"""Cifratura Fernet per config sensitive dei connector."""
from __future__ import annotations
import base64
import hashlib
import json
from cryptography.fernet import Fernet


def _fernet(secret_key: str) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode()).digest())
    return Fernet(key)


def encrypt_config(config: dict, secret_key: str) -> str:
    return _fernet(secret_key).encrypt(json.dumps(config).encode()).decode()


def decrypt_config(encrypted: str, secret_key: str) -> dict:
    return json.loads(_fernet(secret_key).decrypt(encrypted.encode()).decode())


def mask_config(config: dict, sensitive_keys: list[str]) -> dict:
    """Restituisce copia del config con valori sensibili mascherati."""
    out = {}
    for k, v in config.items():
        if k in sensitive_keys and v:
            out[k] = "••••••••"
        else:
            out[k] = v
    return out
