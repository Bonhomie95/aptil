"""Move every stored site credential onto the current CREDENTIAL_ENCRYPTION_KEY.

Usage (inside the api container):

    # 1. mint a new key
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

    # 2. in .env: CREDENTIAL_ENCRYPTION_KEY=<new>
    #             CREDENTIAL_ENCRYPTION_KEYS_OLD=<previous>[,<older>...]
    # 3. restart the api + workers, then:
    python -m scripts.rotate_credential_key            # dry run
    python -m scripts.rotate_credential_key --apply

Because credentials are envelope-encrypted, rotation re-wraps a 32-byte data key
per row; the encrypted password itself is copied verbatim and no plaintext is
ever decrypted. Rows written before envelope encryption existed are the one
exception — they have no data key, so they are decrypted once and re-encrypted.

Safe to re-run: rows already on the current key are skipped. Once the run
reports zero remaining, delete CREDENTIAL_ENCRYPTION_KEYS_OLD.
"""

from __future__ import annotations

import argparse
import asyncio

from cryptography.fernet import InvalidToken

from app.core.security import current_kek_id, needs_rewrap, rewrap_secret
from app.db.session import init_db
from app.models.profile import SiteCredential


async def rotate(apply: bool) -> int:
    await init_db()
    key_id = current_kek_id()
    scanned = stale = rotated = failed = 0

    async for cred in SiteCredential.find_all():
        scanned += 1
        if not needs_rewrap(cred.encrypted_password):
            continue
        stale += 1
        if not apply:
            continue
        try:
            cred.encrypted_password = rewrap_secret(cred.encrypted_password)
        except InvalidToken:
            # The key that wrote this row is not configured. Do not delete it and
            # do not guess — report it so the operator can add the old key.
            failed += 1
            print(f"  UNREADABLE {cred.id} ({cred.site_domain}) — add its old key")
            continue
        cred.touch()
        await cred.save()
        rotated += 1

    print(f"current key: {key_id}")
    print(f"scanned    : {scanned}")
    print(f"stale      : {stale}")
    if apply:
        print(f"rotated    : {rotated}")
        print(f"unreadable : {failed}")
        if failed == 0 and stale == rotated:
            print("\nAll credentials are on the current key. "
                  "You can now clear CREDENTIAL_ENCRYPTION_KEYS_OLD.")
    else:
        print("\nDry run. Re-run with --apply to write.")
    return failed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="write the changes (default: dry run)"
    )
    args = parser.parse_args()
    raise SystemExit(1 if asyncio.run(rotate(args.apply)) else 0)


if __name__ == "__main__":
    main()
