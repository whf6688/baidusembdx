from cryptography.fernet import Fernet

from baidu_platform_core import FernetTokenCipher


def test_token_cipher_round_trip_does_not_store_plaintext():
    cipher = FernetTokenCipher(Fernet.generate_key().decode("ascii"))
    encrypted = cipher.encrypt("sensitive-access-token")
    assert "sensitive-access-token" not in encrypted
    assert cipher.decrypt(encrypted) == "sensitive-access-token"

