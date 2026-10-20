"""Application-layer envelope encryption for sensitive content (Phase 2, Req 3.4).

Wraps a ``KmsProvider`` to encrypt/decrypt document content at the persistence
boundary and serialize the result to a storable, self-describing string. Storage-level
access alone (DB/object store) therefore never reveals plaintext content.

Serialized form (version-prefixed, base64 fields, dot-separated):

    enc:v1:<b64 key_id>.<b64 nonce>.<b64 wrapped_data_key>.<b64 ciphertext>

A value that does not start with the ``enc:v1:`` marker is treated as plaintext and
returned unchanged on decrypt, so the layer is backward-compatible with already-stored
unencrypted content.
"""

from __future__ import annotations

import base64

from backend.providers.interfaces import EncryptedBlob, KmsProvider

_MARKER = "enc:v1:"


def _b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def serialize_blob(blob: EncryptedBlob) -> str:
    """Serialize an :class:`EncryptedBlob` to the ``enc:v1:`` storable string."""
    parts = ".".join(
        (
            _b64e(blob.key_id.encode("utf-8")),
            _b64e(blob.nonce),
            _b64e(blob.wrapped_data_key),
            _b64e(blob.ciphertext),
        )
    )
    return _MARKER + parts


def deserialize_blob(text: str) -> EncryptedBlob:
    """Parse a serialized ``enc:v1:`` string back into an :class:`EncryptedBlob`.

    Raises:
        ValueError: if the value is not a serialized blob.
    """
    if not is_encrypted(text):
        raise ValueError("value is not an enc:v1 serialized blob")
    payload = text[len(_MARKER):]
    try:
        key_id_b64, nonce_b64, wrapped_b64, ct_b64 = payload.split(".")
    except ValueError as e:
        raise ValueError("malformed enc:v1 payload") from e
    return EncryptedBlob(
        ciphertext=_b64d(ct_b64),
        wrapped_data_key=_b64d(wrapped_b64),
        key_id=_b64d(key_id_b64).decode("utf-8"),
        nonce=_b64d(nonce_b64),
    )


def is_encrypted(text: str) -> bool:
    """True if ``text`` is an ``enc:v1:`` serialized blob."""
    return isinstance(text, str) and text.startswith(_MARKER)


class ContentEncryptor:
    """Encrypts/decrypts document content via a KmsProvider (Req 3.4).

    ``tenant_id`` is bound into the AEAD additional-authenticated-data so a ciphertext
    encrypted for one tenant cannot be silently decrypted in another tenant's context.
    """

    def __init__(self, kms: KmsProvider) -> None:
        self._kms = kms

    async def encrypt_text(self, plaintext: str, *, tenant_id: str = "") -> str:
        """Envelope-encrypt ``plaintext`` and return the serialized storable string."""
        if plaintext is None:
            return plaintext  # type: ignore[return-value]
        aad = tenant_id.encode("utf-8") if tenant_id else None
        blob = await self._kms.encrypt(plaintext.encode("utf-8"), aad=aad)
        return serialize_blob(blob)

    async def decrypt_text(self, stored: str, *, tenant_id: str = "") -> str:
        """Decrypt a stored value. Plaintext (non-``enc:v1``) values pass through."""
        if not is_encrypted(stored):
            return stored
        aad = tenant_id.encode("utf-8") if tenant_id else None
        blob = deserialize_blob(stored)
        return (await self._kms.decrypt(blob, aad=aad)).decode("utf-8")
