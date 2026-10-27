from packages.security import hash_password, hash_token, verify_password


def test_password_hash_round_trip() -> None:
    password_hash = hash_password("a-secure-password")
    assert password_hash != "a-secure-password"
    assert verify_password(password_hash, "a-secure-password")
    assert not verify_password(password_hash, "wrong-password")


def test_token_hash_is_deterministic_and_not_plaintext() -> None:
    token_hash = hash_token("token")
    assert token_hash == hash_token("token")
    assert token_hash != "token"
