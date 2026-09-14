"""Failure contract for reading the installed local-model catalog."""


class LocalModelCatalogUnavailableError(RuntimeError):
    def __init__(self, safe_error_code: str) -> None:
        super().__init__(safe_error_code)
        self.safe_error_code = safe_error_code


__all__ = ["LocalModelCatalogUnavailableError"]
