#!/usr/bin/env python3
"""#144: sign release artifacts, and verify them before shipping.

**What this actually proves, stated up front.** A signature here says *these
bytes came from whoever holds the private key*. It does not say they are safe to
run, and it is not a build attestation — the key signs what it is given, so a
compromised build machine with the key produces a valid signature of a compromised
binary. That is true of every signing scheme that does not also record provenance,
and it is worth writing down rather than letting "signed" imply more than it does.

**Ed25519 from `cryptography`**, already a dependency for #99 and #97. No GPG: a
second trust store, a second tool to install, and a key in a keyring the user
cannot see.

**The private key lives in the OS keyring**, same as the API keys from #139. A
signing key sitting next to the artifacts it signs protects nothing.

The output is two files, and both are checked on the way in:

- `SHA256SUMS` — the digests, in the standard `sha256sum` format, so anyone with
  a coreutils box can verify the digests even without this script.
- `<name>.sig` — an Ed25519 signature over the **digest file**, not over each
  artifact. One signature covers everything, and it is the file that must match
  for the set to be intact.

Order matters and is enforced: digests are computed from the artifacts, and the
signature covers the digest file. Signing artifacts individually would let
someone swap one file and keep a valid signature for every other.

Usage:

    python scripts/sign_release.py keygen
    python scripts/sign_release.py sign dist/*.AppImage dist/*.deb
    python scripts/sign_release.py verify dist/fleeting.AppImage
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from cryptography.exceptions import InvalidSignature  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: E402
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

KEY_NAME = "fleeting.release_signing"
PUBLIC_KEY_FILE = REPO_ROOT / "release.pub"
SUMS_FILE = "SHA256SUMS"

# A release with fewer artifacts than this is almost certainly a glob that
# matched nothing, and publishing an empty `SHA256SUMS` is a silent success.
MIN_ARTIFACTS = 1


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_sums(paths: list[Path], base: Path) -> Path:
    """Write `SHA256SUMS` next to the artifacts, in `sha256sum` format."""
    if len(paths) < MIN_ARTIFACTS:
        raise SystemExit("no artifacts given — check the glob")
    lines = [f"{sha256_file(p)}  {p.name}" for p in paths]
    target = base / SUMS_FILE
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def parse_sums(text: str) -> dict[str, str]:
    """`sha256  name` pairs. Skips blanks rather than failing on a trailing one."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        digest, _, name = line.partition("  ")
        if not name:
            continue
        out[name.strip()] = digest.strip()
    return out


# ---- keys ------------------------------------------------------------------


def generate_key() -> tuple[Ed25519PrivateKey, bytes]:
    private = Ed25519PrivateKey.generate()
    return private, private.public_key().public_bytes_raw()


def store_private_key(private: Ed25519PrivateKey) -> bool:
    """Into the keyring. Returns whether a real keyring took it."""
    from fleeting.services.keyring import set_secret

    return set_secret(KEY_NAME, private.private_bytes_raw().hex())


def load_private_key() -> Ed25519PrivateKey:
    from fleeting.services.keyring import get as keyring_get

    raw = keyring_get(KEY_NAME)
    if not raw:
        raise SystemExit(
            "no signing key in the keyring. Run `keygen` first — and keep the "
            "private key out of the repository, which is why it is not there."
        )
    try:
        return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(raw))
    except ValueError as exc:
        raise SystemExit(f"the stored signing key is unusable: {exc}") from exc


# ---- sign / verify ---------------------------------------------------------


def sign(paths: list[Path]) -> dict[str, object]:
    base = paths[0].parent
    sums = write_sums(paths, base)
    signature = load_private_key().sign(sums.read_bytes())
    sig_path = base / f"{SUMS_FILE}.sig"
    sig_path.write_bytes(signature)
    if not PUBLIC_KEY_FILE.exists():
        PUBLIC_KEY_FILE.write_text(
            json.dumps(
                {
                    "algorithm": "ed25519",
                    "public_key": load_private_key().public_key().public_bytes_raw().hex(),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return {"artifacts": [p.name for p in paths], "sums": sums.name, "signature": sig_path.name}


def verify(path: Path) -> dict[str, object]:
    """Check digests *and* signature. A green digest alone proves nothing.

    Raises `SystemExit` with a plain reason, because this is run by a human
    deciding whether to ship a file.
    """
    base = path.parent
    sums_path = base / SUMS_FILE
    sig_path = base / f"{SUMS_FILE}.sig"
    if not sums_path.exists():
        raise SystemExit(f"no {SUMS_FILE} next to {path.name}")
    if not sig_path.exists():
        raise SystemExit(f"no {SUMS_FILE}.sig next to {path.name}")
    pub_path = base / PUBLIC_KEY_FILE.name
    if not pub_path.exists():
        raise SystemExit(f"no {PUBLIC_KEY_FILE.name} to verify against")

    recorded = parse_sums(sums_path.read_text(encoding="utf-8"))
    if path.name not in recorded:
        raise SystemExit(f"{path.name} is not listed in {SUMS_FILE} — sign it first")
    actual = sha256_file(path)
    if actual != recorded[path.name]:
        raise SystemExit(f"{path.name} does not match {SUMS_FILE} — it has been modified")

    try:
        Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(json.loads(pub_path.read_text(encoding="utf-8"))["public_key"])
        ).verify(sig_path.read_bytes(), sums_path.read_bytes())
    except (InvalidSignature, ValueError, KeyError) as exc:
        raise SystemExit(f"{SUMS_FILE}.sig does not match {PUBLIC_KEY_FILE.name}") from exc

    return {"ok": True, "artifact": path.name, "sha256": actual, "signed": True}


def keygen() -> dict[str, object]:
    private, public = generate_key()
    secure = store_private_key(private)
    PUBLIC_KEY_FILE.write_text(
        json.dumps({"algorithm": "ed25519", "public_key": public.hex()}, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "public_key": PUBLIC_KEY_FILE.name,
        "secure_store": "OS keyring" if secure else "file fallback (0600)",
        "warning": None if secure else "no OS keyring — the key is in a file next to the config",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("keygen", help="create a signing key and store it in the OS keyring")
    for name in ("sign", "verify"):
        p = sub.add_parser(name, help=f"{name} one or more artifacts")
        p.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args(argv)

    paths = [Path(p) for p in getattr(args, "paths", [])]
    for p in paths:
        if args.cmd != "keygen" and not p.exists():
            print(f"no such file: {p}", file=sys.stderr)
            return 1
    result = keygen() if args.cmd == "keygen" else (sign(paths) if args.cmd == "sign" else verify(paths[0]))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())