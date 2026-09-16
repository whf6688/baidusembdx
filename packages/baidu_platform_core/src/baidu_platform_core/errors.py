class BaiduPlatformError(RuntimeError):
    pass


class PermissionContextError(BaiduPlatformError):
    pass


class WriteDisabledError(BaiduPlatformError):
    pass


class TokenUnavailableError(BaiduPlatformError):
    pass


class RateLimitError(BaiduPlatformError):
    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: int = 1,
        source: str = "local",
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = max(1, int(retry_after_seconds))
        self.source = source


class UnknownWriteResultError(BaiduPlatformError):
    pass
