"""One-off helper for building APP_USERS_JSON entries (api/auth.py) — bcrypt-hashes a password
so the real password never has to be typed into .env or Render's dashboard in plaintext.

Usage:
    .venv/Scripts/python.exe scripts/hash_password.py
    (prompts for a password, prints the bcrypt hash to paste into APP_USERS_JSON)
"""

from __future__ import annotations

import getpass

import bcrypt


def main() -> None:
    password = getpass.getpass("Password to hash: ")
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    print(hashed.decode("utf-8"))


if __name__ == "__main__":
    main()
