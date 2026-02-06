"""
統一的日誌管理系統
提供結構化日誌記錄，支援檔案輪轉和多層級輸出
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional
import sys


class LoggerFactory:
    """日誌工廠類，提供統一的 Logger 實例"""

    _loggers = {}
    _initialized = False

    @classmethod
    def _initialize(cls):
        """初始化全域日誌配置"""
        if cls._initialized:
            return

        # 從環境變數讀取配置
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        log_dir = os.getenv("LOG_DIR", "logs")
        log_file = os.path.join(log_dir, "sigma2.log")

        # 建立日誌目錄
        os.makedirs(log_dir, exist_ok=True)

        # 設定根 logger
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, log_level, logging.INFO))

        # 清除現有的 handlers
        root_logger.handlers.clear()

        # 建立格式化器
        detailed_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        simple_formatter = logging.Formatter("%(levelname)s - %(name)s - %(message)s")

        # 檔案 Handler (使用輪轉，最大 10MB，保留 5 個備份)
        try:
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=10 * 1024 * 1024,  # 10MB
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(detailed_formatter)
            root_logger.addHandler(file_handler)
        except Exception as e:
            print(f"無法建立日誌檔案 handler: {e}", file=sys.stderr)

        # 控制台 Handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(simple_formatter)
        root_logger.addHandler(console_handler)

        # 標記已初始化
        cls._initialized = True

        # 記錄初始化訊息
        init_logger = logging.getLogger("LoggerFactory")
        init_logger.info(f"日誌系統初始化完成 - 層級: {log_level}, 檔案: {log_file}")

    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """
        取得指定名稱的 Logger 實例

        Args:
            name: Logger 名稱，通常使用 __name__

        Returns:
            Logger 實例
        """
        # 確保已初始化
        if not cls._initialized:
            cls._initialize()

        # 如果已經建立過，直接返回
        if name in cls._loggers:
            return cls._loggers[name]

        # 建立新的 logger
        logger = logging.getLogger(name)
        cls._loggers[name] = logger

        return logger

    @classmethod
    def set_level(cls, level: str):
        """
        動態設定全域日誌層級

        Args:
            level: 日誌層級 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        level = level.upper()
        if hasattr(logging, level):
            logging.getLogger().setLevel(getattr(logging, level))
            cls.get_logger("LoggerFactory").info(f"日誌層級已更新為: {level}")
        else:
            raise ValueError(f"無效的日誌層級: {level}")


# 便捷函數
def get_logger(name: str = None) -> logging.Logger:
    """
    便捷函數，取得 Logger

    Args:
        name: Logger 名稱，如果為 None 則使用調用者的模組名稱

    Returns:
        Logger 實例
    """
    if name is None:
        # 自動取得調用者的模組名稱
        import inspect

        frame = inspect.currentframe().f_back
        name = frame.f_globals.get("__name__", "unknown")

    return LoggerFactory.get_logger(name)


# 抑制第三方庫的冗長日誌
def suppress_noisy_loggers():
    """抑制第三方庫的冗長日誌輸出"""
    noisy_loggers = [
        "d3rlpy",
        "urllib3",
        "httpx",
        "httpcore",
        "asyncio",
    ]

    for logger_name in noisy_loggers:
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.WARNING)
        logger.propagate = False


# 在模組載入時自動初始化
LoggerFactory._initialize()
suppress_noisy_loggers()
