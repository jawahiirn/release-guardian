import base64

from packages.crypto import SecretCipher


def test_secret_cipher_round_trip_and_rotation_nonce() -> None:
    key = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode()
    cipher = SecretCipher(key, "test-v1")
    first = cipher.encrypt("first-secret")
    second = cipher.encrypt("second-secret")
    assert first[1] != second[1]
    assert cipher.decrypt(*first) == "first-secret"
    assert cipher.decrypt(*second) == "second-secret"
