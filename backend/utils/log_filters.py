import logging
import typing


class EndpointFilter(logging.Filter):
    """
    過濾特定路徑的 Uvicorn 訪問日誌
    """

    def __init__(self, path: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.path = path

    def filter(self, record: logging.LogRecord) -> bool:
        # record.args 通常包含 (remote_addr, method, path, http_version, status_code)
        # 我們檢查 args[2] 是否為 path (這是 uvicorn.access 的格式)
        try:
            if len(record.args) >= 3:
                request_path = record.args[2]
                if self.path in request_path:  # 使用 in 支援 query params
                    return False  # 過濾掉

            # 備用檢查：直接檢查訊息字串
            if self.path in record.getMessage():
                return False

            return True
        except Exception:
            return True


def add_log_filter(logger_name: str, path: str):
    logger = logging.getLogger(logger_name)
    logger.addFilter(EndpointFilter(path))
