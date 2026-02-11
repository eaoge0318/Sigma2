from abc import ABC, abstractmethod
from typing import Dict, Any, List


class AnalysisTool(ABC):
    """分析工具抽象基類"""

    def __init__(self, analysis_service):
        self.analysis_service = analysis_service

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名稱"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述"""
        pass

    @property
    def required_params(self) -> List[str]:
        """必需參數列表（子類可覆蓋）"""
        return ["file_id"]

    @abstractmethod
    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        """
        執行工具

        Args:
            params: 工具參數
            session_id: 用戶會話 ID

        Returns:
            工具執行結果
        """
        pass

    def validate_params(self, params: Dict) -> bool:
        """驗證參數完整性"""
        return all(p in params for p in self.required_params)

    def parse_indices(self, data: Any, max_len: int = 0) -> List[int]:
        """
        通用的索引解析工具，具備強大的語義識別能力。
        支援：
        - 列表/集合：[30, 50], {1, 2, 3}
        - 閉區間："30-50", "第30筆到第50筆", "30 to 50", "30 與 50 之間"
        - 開放區間："30之後", "30+", "100以前"
        - 混合格式："30, 40, 50-60"
        """
        import re

        indices = set()
        if not data:
            return []

        if isinstance(data, (list, tuple, set)):
            for item in data:
                if isinstance(item, int):
                    indices.add(item)
                else:
                    indices.update(self.parse_indices(str(item), max_len))
            return sorted(list(indices))

        # 轉為字串並初步清理
        input_str = str(data).replace("[", "").replace("]", "").strip()

        # 1. 識別「範圍」寫法 (如 30-50, 30到50)
        range_pattern = r"(?:第)?\s*(\d+)\s*(?:筆)?\s*(?:-|~|～|to|到|至|與|_)\s*(?:第)?\s*(\d+)\s*(?:筆)?"

        # 2. 識別「之後」系列 (如 30之後, 30+, 30 onwards)
        after_pattern = r"(?:第)?\s*(\d+)\s*(?:筆)?\s*(?:之後|以後|起|onwards|\+)"

        # 3. 識別「以前」系列 (如 100以前, 100之前, 100止)
        before_pattern = r"(?:第)?\s*(\d+)\s*(?:筆)?\s*(?:以前|之前|止|before|up to)"

        remaining_str = input_str

        # 處理 1: 閉區間
        for match in re.finditer(range_pattern, input_str):
            try:
                s_str, e_str = match.groups()
                s, e = int(s_str), int(e_str)
                start, end = min(s, e), max(s, e)
                indices.update(range(start, end + 1))
                remaining_str = remaining_str.replace(match.group(0), " ")
            except ValueError:
                pass

        # 處理 2: 之後 (Suffix)
        for match in re.finditer(after_pattern, input_str):
            try:
                start = int(match.group(1))
                # 如果有 max_len，則到 max_len-1；否則這是一個無效解析或需要調用方處理
                if max_len > 0:
                    indices.update(range(start, max_len))
                remaining_str = remaining_str.replace(match.group(0), " ")
            except ValueError:
                pass

        # 處理 3: 以前 (Prefix)
        for match in re.finditer(before_pattern, input_str):
            try:
                end = int(match.group(1))
                indices.update(range(0, end + 1))
                remaining_str = remaining_str.replace(match.group(0), " ")
            except ValueError:
                pass

        # 4. 識別剩餘字串中的「單點」寫法 (如 第30筆, 20)
        single_pattern = r"(?:第)?\s*(\d+)\s*(?:筆)?"
        for match in re.finditer(single_pattern, remaining_str):
            try:
                indices.add(int(match.group(1)))
            except ValueError:
                pass

        res = sorted(list(indices))
        if max_len > 0:
            res = [i for i in res if 0 <= i < max_len]
        return res
