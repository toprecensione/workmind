"""
WorkMind Encryption Manager
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Crittografia at-rest per dati sensibili (email, documenti parsati, cache).
Usa Fernet (AES-128-CBC con HMAC SHA256) dalla libreria cryptography.

La chiave di crittografia è derivata da una master password in .env
(WORKMIND_ENCRYPTION_KEY) tramite PBKDF2.
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
from typing import Optional, Union

from logging_system import get_logger, LogAction, LogStatus

log = get_logger("security.encryption")

_ENCRYPTION_KEY_ENV = "WORKMIND_ENCRYPTION_KEY"
_SALT_FILE_ENV = "WORKMIND_SALT_PATH"


class EncryptionManager:
    """
    Crittografia simmetrica per dati at-rest.
    Se la chiave non è configurata, opera in modalità passthrough (no-op)
    con un warning.
    """

    def __init__(self) -> None:
        self._fernet = None
        self._init_fernet()

    @property
    def is_active(self) -> bool:
        return self._fernet is not None

    def encrypt(self, data: Union[str, bytes]) -> bytes:
        """Cripta i dati. Ritorna bytes crittati."""
        if not self._fernet:
            return data.encode("utf-8") if isinstance(data, str) else data

        plaintext = data.encode("utf-8") if isinstance(data, str) else data
        return self._fernet.encrypt(plaintext)

    def decrypt(self, token: bytes) -> bytes:
        """Decripta i dati. Ritorna bytes in chiaro."""
        if not self._fernet:
            return token

        return self._fernet.decrypt(token)

    def decrypt_str(self, token: bytes) -> str:
        return self.decrypt(token).decode("utf-8")

    def encrypt_file(self, src: Path, dst: Optional[Path] = None) -> Path:
        """Cripta un file. Se dst è None, sovrascrive l'originale."""
        dst = dst or src
        plaintext = src.read_bytes()
        ciphertext = self.encrypt(plaintext)
        dst.write_bytes(ciphertext)
        return dst

    def decrypt_file(self, src: Path, dst: Optional[Path] = None) -> Path:
        """Decripta un file."""
        dst = dst or src
        ciphertext = src.read_bytes()
        plaintext = self.decrypt(ciphertext)
        dst.write_bytes(plaintext)
        return dst

    # ── Inizializzazione ──────────────────────────────────────────────────────

    def _init_fernet(self) -> None:
        key_material = os.getenv(_ENCRYPTION_KEY_ENV, "")
        if not key_material:
            log.warning(
                "Encryption key non configurata — dati NON crittati",
                action=LogAction.CONFIG, status=LogStatus.WARNING,
                suggestion=f"Imposta {_ENCRYPTION_KEY_ENV} nel file .env",
            )
            return

        try:
            from cryptography.fernet import Fernet
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

            salt = self._get_or_create_salt()
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=600_000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(key_material.encode("utf-8")))
            self._fernet = Fernet(key)
            log.info("Encryption inizializzata (Fernet/PBKDF2)", action=LogAction.STARTUP, status=LogStatus.OK)
        except ImportError:
            log.error(
                "Libreria cryptography non installata",
                action=LogAction.CONFIG, status=LogStatus.ERROR,
                suggestion="pip install cryptography",
            )
        except Exception as exc:
            log.error(f"Errore inizializzazione encryption: {exc}", action=LogAction.STARTUP)

    @staticmethod
    def _get_or_create_salt() -> bytes:
        from config.settings import DATA_DIR
        salt_path = Path(os.getenv(_SALT_FILE_ENV, str(DATA_DIR / ".encryption_salt")))
        if salt_path.exists():
            return salt_path.read_bytes()
        salt = os.urandom(16)
        salt_path.write_bytes(salt)
        os.chmod(str(salt_path), 0o600)
        return salt


# ─── Singleton ────────────────────────────────────────────────────────────────

_enc: Optional[EncryptionManager] = None


def get_encryption() -> EncryptionManager:
    global _enc
    if _enc is None:
        _enc = EncryptionManager()
    return _enc
