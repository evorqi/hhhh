"""User-facing errors. Messages are safe to return to clients."""


class AppError(Exception):
    def __init__(
        self,
        message_en: str,
        message_fa: str,
        *,
        code: str = "invalid_request",
        status_code: int = 400,
    ) -> None:
        super().__init__(message_en)
        self.message_en = message_en
        self.message_fa = message_fa
        self.code = code
        self.status_code = status_code
