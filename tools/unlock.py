#!/usr/bin/env python3
"""Unlock hidden_tests.enc with the password shown in the room at 1:30 PM on Sunday.

  python tools/unlock.py hidden_tests.enc PASSWORD

Spaces, dashes and capital letters in the password don't matter. Creates a hidden_tests/ folder with one input folder per hidden test. Needs only Python 3.
"""
from __future__ import annotations
import argparse
import hashlib
import hmac
import io
import sys
import zipfile
from pathlib import Path

MAGIC = b"YECH1"
ITERATIONS = 200_000

def normalize(password: str) -> str:
    """Spaces, dashes and letter case don't matter, so 'k7qm 4xtr' and 'K7QM-4XTR' both work."""
    return "".join(ch for ch in password.upper() if ch not in " -")

def keys(password: str, salt: bytes):
    k = hashlib.pbkdf2_hmac("sha256", normalize(password).encode(), salt, ITERATIONS, dklen=64)
    return k[:32], k[32:]

def keystream_xor(enc_key: bytes, nonce: bytes, data: bytes) -> bytes:
    out = bytearray(len(data))
    for block in range(0, len(data), 32):
        ks = hashlib.sha256(enc_key + nonce + (block // 32).to_bytes(8, "big")).digest()
        chunk = data[block:block + 32]
        out[block:block + len(chunk)] = bytes(a ^ b for a, b in zip(chunk, ks))
    return bytes(out)

def unlock(blob: bytes, password: str) -> bytes:
    if not blob.startswith(MAGIC):
        raise ValueError("not a hidden_tests.enc file")
    salt, nonce, tag, body = blob[5:21], blob[21:37], blob[37:69], blob[69:]
    enc_key, mac_key = keys(password, salt)
    if not hmac.compare_digest(tag, hmac.new(mac_key, nonce + body, hashlib.sha256).digest()):
        raise ValueError("wrong password (check each character against the board)")
    return keystream_xor(enc_key, nonce, body)

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help="hidden_tests.enc")
    ap.add_argument("password")
    ap.add_argument("-o", "--output", default="hidden_tests")
    args = ap.parse_args()
    try:
        data = unlock(Path(args.file).read_bytes(), args.password)
    except ValueError as e:
        sys.exit(f"Could not unlock: {e}")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(args.output)
        names = sorted({n.split("/")[0] for n in z.namelist()})
    print(f"Unlocked into {args.output}/: {', '.join(names)}")

if __name__ == "__main__":
    main()
