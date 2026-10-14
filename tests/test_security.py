"""API key generation / verification."""

from app.core.security import generate_api_key, hash_key, key_prefix, verify_key


def test_generate_returns_hashable_triple():
    full_key, prefix, stored_hash = generate_api_key()
    assert full_key.startswith(f"nn_{prefix}_")
    assert stored_hash == hash_key(full_key)
    assert verify_key(full_key, stored_hash)


def test_keys_are_unique():
    keys = {generate_api_key()[0] for _ in range(50)}
    assert len(keys) == 50


def test_wrong_key_rejected():
    _, _, stored_hash = generate_api_key()
    other_key, _, _ = generate_api_key()
    assert not verify_key(other_key, stored_hash)
    assert not verify_key("", stored_hash)


def test_prefix_extraction():
    full_key, prefix, _ = generate_api_key()
    assert key_prefix(full_key) == prefix
    assert key_prefix("garbage") is None
    assert key_prefix("nn_") is None
