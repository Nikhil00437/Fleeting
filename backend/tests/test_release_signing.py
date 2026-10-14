"""#144: signed release artifacts.

The properties that matter, in order of how badly each would hurt if wrong:

1. **A tampered artifact fails.** The digest and the signature are both checked,
   and the digests are checked against the bytes on disk right now rather than
   against a record made at some earlier moment.
2. **A green digest alone is not enough.** Anyone can rewrite `SHA256SUMS` to
   match a modified binary. The signature covers the *digest file*, which is what
   makes the set tamper-evident rather than merely self-consistent — and the
   ordering is enforced, because signing artifacts individually would let one
   file be swapped while every other signature stayed valid.
3. **The private key is not in the repository.** It goes to the OS keyring, the
   same place #139 put the API keys. A signing key stored beside the artifacts it
   signs protects nothing.
4. **A glob that matched nothing is an error, not an empty release.** Publishing
   an empty `SHA256SUMS` is a silent success, and it ships.

The tests drive `sign` and `verify` as functions with injected paths, so none of
this touches the developer's real keyring or a real artifact.
"""

from __future__ import annotations

import importlib.util
import json
import sys

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tests.repo import REPO_ROOT


@pytest.fixture(scope="module")
def sign_release():
    path = REPO_ROOT / "scripts" / "sign_release.py"
    spec = importlib.util.spec_from_file_location("sign_release", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["sign_release"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def artifacts(tmp_path):
    """Three plausible release files, one per platform."""
    made = []
    for name, body in (
        ("fleeting-0.18.0.AppImage", b"ELF-ish payload"),
        ("fleeting-0.18.0.deb", b"deb payload"),
        ("fleeting-0.18.0.dmg", b"dmg payload"),
    ):
        p = tmp_path / name
        p.write_bytes(body)
        made.append(p)
    return made


@pytest.fixture()
def signed(sign_release, artifacts, tmp_path, monkeypatch):
    """The same signing, with the key held in a temp file instead of a keyring."""
    private, public = sign_release.generate_key()
    keyfile = tmp_path / "key.hex"
    keyfile.write_text(private.private_bytes_raw().hex(), encoding="utf-8")
    pubfile = tmp_path / sign_release.PUBLIC_KEY_FILE.name
    pubfile.write_text(json.dumps({"algorithm": "ed25519", "public_key": public.hex()}), encoding="utf-8")
    monkeypatch.setattr(sign_release, "load_private_key", lambda: Ed25519PrivateKey.from_private_bytes(bytes.fromhex(keyfile.read_text())))
    monkeypatch.setattr(sign_release, "PUBLIC_KEY_FILE", pubfile)
    result = sign_release.sign(artifacts)
    return {"module": sign_release, "artifacts": artifacts, "dir": tmp_path, "result": result}


# ---- digests ---------------------------------------------------------------


def test_digests_are_recorded_for_every_artifact(signed) -> None:
    sums = (signed["dir"] / "SHA256SUMS").read_text(encoding="utf-8")
    for path in signed["artifacts"]:
        assert path.name in sums


def test_the_sums_file_is_standard_sha256sum_format(signed) -> None:
    """Anyone with a coreutils box can check the digests without this script."""
    line = (signed["dir"] / "SHA256SUMS").read_text(encoding="utf-8").splitlines()[0]
    digest, sep, name = line.partition("  ")
    assert sep == "  "
    assert len(digest) == 64
    assert name


def test_the_recorded_digest_matches_the_file(signed) -> None:
    m = signed["module"]
    sums = m.parse_sums((signed["dir"] / "SHA256SUMS").read_text(encoding="utf-8"))
    for path in signed["artifacts"]:
        assert sums[path.name] == m.sha256_file(path)


def test_one_signature_covers_the_whole_set(signed) -> None:
    assert (signed["dir"] / "SHA256SUMS.sig").exists()
    assert len(signed["artifacts"]) == 3


def test_signing_nothing_is_an_error(signed) -> None:
    """An empty `SHA256SUMS` is a silent success, and it ships."""
    with pytest.raises(SystemExit):
        signed["module"].write_sums([], signed["dir"])


# ---- verifying -------------------------------------------------------------


def test_a_correctly_signed_artifact_verifies(signed) -> None:
    assert signed["module"].verify(signed["artifacts"][0])["ok"] is True


def test_a_modified_artifact_fails(signed) -> None:
    """The whole reason this exists."""
    target = signed["artifacts"][0]
    target.write_bytes(b"ELF-ish payload but evil")
    with pytest.raises(SystemExit) as err:
        signed["module"].verify(target)
    assert "modified" in str(err.value)


def test_a_rewritten_sums_file_fails(signed) -> None:
    """Anyone can edit a digest to match a modified file — which is why the
    signature covers the digest file rather than the artifacts."""
    m = signed["module"]
    target = signed["artifacts"][0]
    target.write_bytes(b"evil")
    (signed["dir"] / "SHA256SUMS").write_text(
        f"{m.sha256_file(target)}  {target.name}\n", encoding="utf-8"
    )
    with pytest.raises(SystemExit) as err:
        m.verify(target)
    assert "does not match" in str(err.value)


def test_an_artifact_that_was_never_signed_fails(signed) -> None:
    """Signing artifacts individually would let an unsigned fourth file join the
    set while every signature stayed valid. The digest file is the unit: a file
    it does not list is not covered by the signature at all."""
    m = signed["module"]
    intruder = signed["dir"] / "fleeting-0.18.0.snap"
    intruder.write_bytes(b"nobody signed this")
    with pytest.raises(SystemExit) as err:
        m.verify(intruder)
    assert "not listed" in str(err.value)


def test_an_unsigned_release_does_not_verify(signed, tmp_path) -> None:
    lonely = tmp_path / "unsigned"
    lonely.mkdir()
    f = lonely / "thing.dmg"
    f.write_bytes(b"x")
    with pytest.raises(SystemExit) as err:
        signed["module"].verify(f)
    assert "SHA256SUMS" in str(err.value)


def test_a_signature_from_another_key_fails(signed, tmp_path, monkeypatch) -> None:
    """The signature must be from *this* key, not merely well-formed."""
    m = signed["module"]
    _, other_public = m.generate_key()
    pubfile = signed["dir"] / m.PUBLIC_KEY_FILE.name
    pubfile.write_text(json.dumps({"algorithm": "ed25519", "public_key": other_public.hex()}), encoding="utf-8")
    with pytest.raises(SystemExit) as err:
        m.verify(signed["artifacts"][0])
    assert "does not match" in str(err.value)


def test_a_corrupt_signature_fails(signed) -> None:
    (signed["dir"] / "SHA256SUMS.sig").write_bytes(b"\x00" * 64)
    with pytest.raises(SystemExit):
        signed["module"].verify(signed["artifacts"][0])


# ---- the key ---------------------------------------------------------------


def test_the_public_key_file_is_written_on_keygen(sign_release, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sign_release, "PUBLIC_KEY_FILE", tmp_path / sign_release.PUBLIC_KEY_FILE.name)
    monkeypatch.setattr(sign_release, "store_private_key", lambda private: True)
    result = sign_release.keygen()
    assert (tmp_path / sign_release.PUBLIC_KEY_FILE.name).exists()
    assert result["secure_store"] == "OS keyring"


def test_a_file_keyring_is_reported_as_insecure(sign_release, tmp_path, monkeypatch) -> None:
    """"Signed" should not be a word that covers two very different situations."""
    monkeypatch.setattr(sign_release, "PUBLIC_KEY_FILE", tmp_path / sign_release.PUBLIC_KEY_FILE.name)
    monkeypatch.setattr(sign_release, "store_private_key", lambda private: False)
    assert sign_release.keygen()["secure_store"].startswith("file fallback")


def test_the_public_file_holds_the_public_key_not_the_private_one(sign_release, tmp_path, monkeypatch) -> None:
    """Checked against the key `keygen` actually used.

    Checking a *different* freshly-generated key proves nothing: the file would
    not contain it whether or not the private key were written there.
    """
    held: dict[str, object] = {}
    monkeypatch.setattr(sign_release, "PUBLIC_KEY_FILE", tmp_path / sign_release.PUBLIC_KEY_FILE.name)
    monkeypatch.setattr(sign_release, "store_private_key", lambda private: held.setdefault("k", private) is None or True)
    sign_release.keygen()

    private = held["k"]
    doc = json.loads((tmp_path / sign_release.PUBLIC_KEY_FILE.name).read_text(encoding="utf-8"))
    assert doc["public_key"] == private.public_key().public_bytes_raw().hex()
    assert private.private_bytes_raw().hex() not in json.dumps(doc)


def test_the_public_key_actually_verifies(sign_release, tmp_path, monkeypatch) -> None:
    """A 32-byte scalar in the file is not self-evidently a public key. This
    says what it is for."""
    held: dict[str, object] = {}
    monkeypatch.setattr(sign_release, "PUBLIC_KEY_FILE", tmp_path / sign_release.PUBLIC_KEY_FILE.name)
    monkeypatch.setattr(sign_release, "store_private_key", lambda private: held.setdefault("k", private) is None or True)
    sign_release.keygen()
    private = held["k"]
    doc = json.loads((tmp_path / sign_release.PUBLIC_KEY_FILE.name).read_text(encoding="utf-8"))
    # Sign with the private key, verify with what the file claims is the public one.
    signature = private.sign(b"payload")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    Ed25519PublicKey.from_public_bytes(bytes.fromhex(doc["public_key"])).verify(signature, b"payload")


def test_no_private_key_is_committed() -> None:
    """The check that matters day to day: nothing in the repo looks like a
    signing key."""
    offenders = [
        str(p.relative_to(REPO_ROOT))
        for p in REPO_ROOT.rglob("*.pem")
        if ".venv" not in str(p) and "node_modules" not in str(p)
    ]
    assert offenders == [], f"private-key-shaped files in the repo: {offenders}"
    assert not (REPO_ROOT / "release.key").exists()