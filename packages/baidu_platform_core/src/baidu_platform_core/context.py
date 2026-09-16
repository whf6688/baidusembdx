from dataclasses import dataclass


@dataclass(frozen=True)
class WritePolicy:
    enabled: bool = False


@dataclass(frozen=True)
class BaiduCallContext:
    app_code: str
    baidu_application_code: str
    manager_login_name: str
    target_account_id: int
    target_login_name: str
    request_batch: str
    idempotency_key: str

    def validate(self, write: bool = False) -> None:
        if self.app_code not in {"ecom", "search"}:
            raise ValueError("app_code 只能是 ecom 或 search")
        if not self.baidu_application_code:
            raise ValueError("baidu_application_code 不能为空")
        if write and (not self.target_account_id or not self.target_login_name):
            from .errors import PermissionContextError
            raise PermissionContextError("百度写操作必须明确目标账户 ID 和登录名")
        if write and not self.idempotency_key:
            raise ValueError("百度写操作必须携带幂等键")

