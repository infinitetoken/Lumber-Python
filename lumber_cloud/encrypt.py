import base64
import json
import os

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def encrypt_payload(payload: dict, key_b64: str) -> str:
    """
    Encrypts payload dict into the Lumber wire format.

    Returns base64(IV[12 bytes] + AuthTag[16 bytes] + ciphertext).

    Wire format is byte-for-byte identical to Lumber-Node's encryptPayload():
      - IV:  12 random bytes from os.urandom(12)
      - Tag: 16-byte AES-256-GCM authentication tag (read AFTER finalize())
      - CT:  AES-256-GCM ciphertext of compact JSON (separators=(',', ':'))

    Raises ValueError if key_b64 does not decode to exactly 32 bytes.

    CRITICAL: encryptor.tag must be accessed AFTER encryptor.finalize().
    Accessing it before finalize() returns an invalid (all-zero) tag.
    This mirrors Node's cipher.getAuthTag() which must also be called after cipher.final().
    """
    key = base64.b64decode(key_b64)
    if len(key) != 32:
        raise ValueError(
            f"Invalid encryption key: expected 32 bytes after base64 decode, "
            f"got {len(key)}. Pass the key exactly as returned by POST /apps."
        )

    iv = os.urandom(12)  # fresh random IV per call — never reuse

    # Use separators=(',', ':') to match Node's JSON.stringify() output exactly.
    # Default Python json.dumps uses ', ' and ': ' which differs character-for-character
    # from Node output (still decryptable but breaks byte-equality cross-language tests).
    plaintext = json.dumps(payload, separators=(',', ':')).encode('utf-8')

    encryptor = Cipher(algorithms.AES(key), modes.GCM(iv)).encryptor()
    ct = encryptor.update(plaintext) + encryptor.finalize()
    tag = encryptor.tag  # 16 bytes — only valid AFTER finalize()

    return base64.b64encode(iv + tag + ct).decode('ascii')
