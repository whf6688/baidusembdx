from cryptography.fernet import Fernet, InvalidToken

from .errors import TokenUnavailableError


class FernetTokenCipher:
    def __init__(self, key: str):
        if not key:
            raise TokenUnavailableError("公共 Token 加密密钥未配置")
        self._fernet = Fernet(key.encode("ascii"))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise TokenUnavailableError("公共授权中心 Token 无法解密") from exc

