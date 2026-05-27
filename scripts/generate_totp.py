#!/usr/bin/env python
"""
TOTP Code Generator
===================

Generates the 6-digit TOTP code for Upstox 2FA login — same code your
Google Authenticator / Authy app shows.

Use this when you want to log in from a headless server and don't have
your phone handy, OR to verify your TOTP secret is correct.

Requirements:
  - Your TOTP secret (the 32-character base32 string shown during 2FA setup in Upstox)
  - No external dependencies — uses Python's built-in hmac + hashlib

How to find your TOTP secret:
  1. Log in to Upstox web → Profile → Security → 2FA
  2. Click "Reset TOTP" or "View QR"
  3. The QR code URL contains: ?secret=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
  4. Copy that 32-character base32 string

Usage:
    # Interactive (prompts for secret)
    python scripts/generate_totp.py

    # With secret as argument (be careful with shell history)
    python scripts/generate_totp.py --secret JBSWY3DPEHPK3PXP

    # Live mode — refreshes every 30 seconds until you press Ctrl+C
    python scripts/generate_totp.py --secret JBSWY3DPEHPK3PXP --live

    # Save secret to file (avoids typing it every time)
    python scripts/generate_totp.py --save
    python scripts/generate_totp.py  # reads from saved file next time
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_SECRET_FILE = ROOT / "data" / ".totp_secret"   # stored encrypted (XOR — not high security)


# ── Pure-Python TOTP (RFC 6238) ───────────────────────────────────────────────

def _hotp(key_bytes: bytes, counter: int) -> int:
    """HMAC-based OTP (RFC 4226)."""
    msg = struct.pack(">Q", counter)
    h = hmac.new(key_bytes, msg, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    code = struct.unpack(">I", h[offset: offset + 4])[0] & 0x7FFFFFFF
    return code % 1_000_000


def totp(secret_b32: str, drift: int = 0) -> str:
    """
    Generate a 6-digit TOTP code from a base32 secret.

    Args:
        secret_b32: base32-encoded secret (case-insensitive, spaces allowed)
        drift:      time step offset (+1 for next window, -1 for previous)

    Returns:
        6-digit string, zero-padded
    """
    secret = secret_b32.upper().replace(" ", "").replace("-", "")
    # base32 padding
    pad = len(secret) % 8
    if pad:
        secret += "=" * (8 - pad)
    try:
        key_bytes = base64.b32decode(secret)
    except Exception as e:
        raise ValueError(f"Invalid TOTP secret (not valid base32): {e}") from e

    counter = int(time.time()) // 30 + drift
    return str(_hotp(key_bytes, counter)).zfill(6)


def seconds_remaining() -> int:
    """Seconds until current TOTP window expires."""
    return 30 - (int(time.time()) % 30)


# ── Secret storage (light obfuscation, not real encryption) ──────────────────

def _xor(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def save_secret(secret: str) -> None:
    _SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    key = b"loony-totp-2026"
    encrypted = _xor(secret.encode(), key)
    with open(_SECRET_FILE, "wb") as f:
        f.write(base64.b64encode(encrypted))
    _SECRET_FILE.chmod(0o600)
    print(f"  Secret saved to {_SECRET_FILE}")
    print("  (Lightly obfuscated — don't rely on this for security.)")


def load_secret() -> str | None:
    if not _SECRET_FILE.exists():
        return None
    try:
        key = b"loony-totp-2026"
        with open(_SECRET_FILE, "rb") as f:
            encrypted = base64.b64decode(f.read())
        return _xor(encrypted, key).decode()
    except Exception:
        return None


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Upstox TOTP code")
    parser.add_argument("--secret", help="Base32 TOTP secret (32 chars)")
    parser.add_argument("--save", action="store_true", help="Save secret for future use")
    parser.add_argument("--live", action="store_true", help="Auto-refresh every 30 seconds")
    parser.add_argument("--show-next", action="store_true", help="Also show the next window's code")
    args = parser.parse_args()

    print("\n" + "=" * 50)
    print("  Upstox TOTP Code Generator")
    print("=" * 50)

    # Get secret
    secret = args.secret or load_secret()

    if not secret:
        print("\n  No TOTP secret provided or saved.")
        print("  Enter your base32 TOTP secret (32 characters).")
        print("  (Input is hidden)\n")
        secret = getpass.getpass("  TOTP Secret: ").strip()
        if not secret:
            print("  [ERROR] Secret cannot be empty.")
            sys.exit(1)

    # Validate
    try:
        test_code = totp(secret)
    except ValueError as e:
        print(f"\n  [ERROR] {e}")
        print("  Make sure you copied the full base32 secret (letters + numbers, ~32 chars).")
        sys.exit(1)

    # Save if requested
    if args.save:
        save_secret(secret)

    if args.live:
        print("\n  Live mode — showing TOTP codes (Ctrl+C to stop)\n")
        try:
            while True:
                code = totp(secret)
                remaining = seconds_remaining()
                bar = "█" * remaining + "░" * (30 - remaining)
                sys.stdout.write(f"\r  Code: {code}  [{bar}] {remaining:2d}s remaining")
                sys.stdout.flush()
                if remaining == 1:
                    time.sleep(1)
                    print()   # newline when window changes
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\n\n  Stopped.")
        return

    # Single output
    code     = totp(secret)
    remaining = seconds_remaining()
    print(f"\n  Current TOTP code: {code}")
    print(f"  Valid for:         {remaining} more seconds")

    if args.show_next or remaining < 5:
        next_code = totp(secret, drift=1)
        print(f"  Next code:         {next_code}  (valid in {remaining}s)")

    if remaining < 8:
        print("\n  [!] Less than 8 seconds left — wait for the next code to avoid timeout.")
        next_code = totp(secret, drift=1)
        print(f"  Next code ready in {remaining}s: {next_code}")

    print()
    print("  Enter this code on the Upstox login page under 'TOTP'.")
    print()


if __name__ == "__main__":
    main()
