import base64
import os
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class SecretCipher:
    """Encrypt integration secrets using an operator-supplied AES-GCM key."""

    def __init__(self, encoded_key: str | None = None, key_id: str | None = None) -> None:
        encoded = encoded_key or os.getenv("ENCRYPTION_MASTER_KEY")
        if not encoded:
            raise RuntimeError("ENCRYPTION_MASTER_KEY is required for secret operations")
        try:
            key = base64.urlsafe_b64decode(encoded.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise RuntimeError("ENCRYPTION_MASTER_KEY must be URL-safe base64") from exc
        if len(key) not in {16, 24, 32}:
            raise RuntimeError("ENCRYPTION_MASTER_KEY must decode to 16, 24, or 32 bytes")
        self._key = key
        self.key_id = key_id or os.getenv("ENCRYPTION_KEY_ID") or "local-v1"

    def encrypt(self, secret: str) -> tuple[bytes, bytes, str]:
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self._key).encrypt(nonce, secret.encode("utf-8"), None)
        return ciphertext, nonce, self.key_id

    def decrypt(self, ciphertext: bytes, nonce: bytes, key_id: str) -> str:
        if key_id != self.key_id:
            raise RuntimeError(f"unsupported encryption key id: {key_id}")
        try:
            plaintext = AESGCM(self._key).decrypt(nonce, ciphertext, None)
        except InvalidTag as exc:
            raise RuntimeError("encrypted secret failed authentication") from exc
        return plaintext.decode("utf-8")
