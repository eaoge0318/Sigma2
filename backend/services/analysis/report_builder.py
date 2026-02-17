"""
ReportBuilder: 从 Humanizer 生成的 Markdown 中提取结构化报告

不需要额外的 LLM 调用。在 Humanizer 完成串流之后，
从 full_text (Markdown) 中用正则和规则提取 findings / action_items 等结构化数据，
供前端渲染卡片式摘要。
"""

import re
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ReportBuilder:
    """从 Humanizer 输出的 Markdown 中提取结构化报告 (纯算法，无 LLM)"""

    # Z-Score 严重度判定阈值
    CRITICAL_THRESHOLD = 6.0
    HIGH_THRESHOLD = 3.0

    def extract_from_markdown(self, markdown_text: str) -> Optional[Dict[str, Any]]:
        """
        从 Markdown 报告中提取结构化数据。

        Args:
            markdown_text: Humanizer 生成的完整 Markdown 文本

        Returns:
            结构化报告 dict，如果没有有意义的内容则返回 None
        """
        if not markdown_text or len(markdown_text.strip()) < 20:
            return None

        try:
            findings = self._extract_findings(markdown_text)
            action_items = self._extract_action_items(markdown_text)
            executive_summary = self._extract_summary(markdown_text)

            # 如果什么都没提取到，不返回空壳
            if not findings and not action_items:
                return None

            return {
                "executive_summary": executive_summary,
                "findings": findings,
                "action_items": action_items,
            }

        except Exception as e:
            logger.error(f"[ReportBuilder] Extraction failed: {e}")
            return None

    def _extract_summary(self, text: str) -> str:
        """
        提取报告摘要。
        策略：取第一个 ## 标题后的第一段文字，或者整个文本的前 150 字。
        """
        # 尝试匹配 "分析概要" / "概要" / "總結" 段落
        summary_patterns = [
            r"(?:^|\n)#+\s*(?:分析概要|概要|總結|摘要|核心發現|結論)\s*\n+(.*?)(?:\n#|\Z)",
        ]
        for pat in summary_patterns:
            m = re.search(pat, text, re.DOTALL)
            if m:
                summary = m.group(1).strip()
                # 清理 markdown 格式
                summary = re.sub(r"\*\*([^*]+)\*\*", r"\1", summary)
                summary = re.sub(r"\n+", " ", summary)
                return summary[:300]

        # Fallback: 取第一段非标题文字
        lines = text.strip().split("\n")
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#") and len(line) > 10:
                clean = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
                return clean[:300]

        return "分析已完成"

    def _extract_findings(self, text: str) -> List[Dict[str, Any]]:
        """
        从 Markdown 中提取发现，支持多种格式：
        1. Markdown 表格 (排名 | 参数 | Z-Score | ...)
        2. 加粗列点 (**参数名**: Z-Score = X.XX)
        3. 编号列表中的参数描述
        """
        findings = []

        # --- 策略 1: Markdown 表格 (异常发现排名) ---
        # 匹配如: | 1 | SHAP-DCS_A65 | 5.23 | 偏高 | HIGH |
        table_pattern = (
            r"\|\s*\d+\s*\|\s*([^|]+)\|\s*([\d.]+)\s*\|\s*([^|]+)\|\s*([^|]+)\|"
        )
        for m in re.finditer(table_pattern, text):
            param = m.group(1).strip()
            z_score = self._parse_float(m.group(2).strip())
            anomaly_type = m.group(3).strip()
            severity = self._determine_severity(z_score, m.group(4).strip())
            findings.append(
                {
                    "title": f"{param} (Z={z_score:.2f})" if z_score else param,
                    "severity": severity,
                    "detail": f"{anomaly_type}，Z-Score = {z_score}"
                    if z_score
                    else anomaly_type,
                    "z_score": z_score,
                    "parameter": param,
                }
            )

        # --- 策略 2: 内文 Z-Score 提及 ---
        # 匹配如: **SHAP-DCS_A65** 的 Z-Score 為 5.23
        # 或: SHAP-DCS_A65 (Z-Score: 5.23)
        if not findings:
            zscore_patterns = [
                r"\*\*([^*]+)\*\*\s*[的之]?\s*Z-?[Ss]core\s*[=為为：:]\s*([-\d.]+)",
                r"([A-Z][\w\-_]+)\s*[（(]\s*Z-?[Ss]core\s*[=:：]\s*([-\d.]+)\s*[)）]",
                r"Z-?[Ss]core\s*[=為为：:]\s*([-\d.]+)\s*[，,]\s*(?:參數|参数|欄位)?[：:]?\s*\*?\*?([A-Z][\w\-_]+)",
            ]
            for pat in zscore_patterns:
                for m in re.finditer(pat, text):
                    groups = m.groups()
                    # 有些 pattern 参数在前，有些 z 在前
                    if self._parse_float(groups[0]) is not None:
                        z_val, param = groups[0], groups[1]
                    else:
                        param, z_val = groups[0], groups[1]

                    z_score = self._parse_float(z_val)
                    if z_score is not None and abs(z_score) > 1.5:
                        severity = self._determine_severity(z_score)
                        # 避免重复
                        if not any(f["parameter"] == param.strip() for f in findings):
                            findings.append(
                                {
                                    "title": f"{param.strip()} (Z={z_score:.2f})",
                                    "severity": severity,
                                    "detail": self._find_context(text, param.strip()),
                                    "z_score": z_score,
                                    "parameter": param.strip(),
                                }
                            )

        # --- 策略 3: 加粗列点 ---
        if not findings:
            bullet_pattern = r"[-•]\s*\*\*([^*]+)\*\*\s*[：:]\s*(.+?)(?:\n|$)"
            for m in re.finditer(bullet_pattern, text):
                title = m.group(1).strip()
                detail = m.group(2).strip()
                z_score = self._extract_zscore_from_text(detail)
                severity = self._determine_severity(z_score) if z_score else "MEDIUM"
                findings.append(
                    {
                        "title": f"{title} (Z={z_score:.2f})" if z_score else title,
                        "severity": severity,
                        "detail": detail[:200],
                        "z_score": z_score,
                        "parameter": title,
                    }
                )

        # 按严重度排序
        severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        findings.sort(key=lambda f: severity_order.get(f["severity"], 3))

        return findings

    def _extract_action_items(self, text: str) -> List[Dict[str, str]]:
        """
        提取行动建议。
        搜索 "行動建議" / "建議" 标题下的列表项。
        """
        items = []

        # 找到行动建议段落
        action_section_pattern = (
            r"(?:^|\n)#+\s*(?:行動建議|建議|結論與建議|改善建議)\s*\n+(.*?)(?:\n#|\Z)"
        )
        m = re.search(action_section_pattern, text, re.DOTALL)

        if m:
            section = m.group(1)
            # 提取列表项
            list_pattern = r"(?:^|\n)\s*(?:\d+[.、]|[-•])\s*\*?\*?(.+?)(?:\n|$)"
            for item_match in re.finditer(list_pattern, section):
                action_text = item_match.group(1).strip()
                # 清理 markdown 格式
                action_text = re.sub(r"\*\*([^*]+)\*\*", r"\1", action_text)

                if len(action_text) > 5:
                    priority = self._determine_action_priority(action_text)
                    items.append(
                        {
                            "priority": priority,
                            "action": action_text[:200],
                        }
                    )

        return items

    def _determine_severity(self, z_score: float = None, text_hint: str = "") -> str:
        """根据 Z-Score 或文字提示判断严重程度"""
        if z_score is not None:
            abs_z = abs(z_score)
            if abs_z >= self.CRITICAL_THRESHOLD:
                return "CRITICAL"
            elif abs_z >= self.HIGH_THRESHOLD:
                return "HIGH"
            elif abs_z >= 2.0:
                return "MEDIUM"
            else:
                return "LOW"

        # 从文字提示判断
        hint_lower = text_hint.lower()
        if any(k in hint_lower for k in ["critical", "極端", "严重", "嚴重", "危險"]):
            return "CRITICAL"
        elif any(k in hint_lower for k in ["high", "高", "異常", "异常"]):
            return "HIGH"
        elif any(k in hint_lower for k in ["medium", "中", "偏高", "偏低"]):
            return "MEDIUM"
        return "LOW"

    def _determine_action_priority(self, text: str) -> str:
        """根据行动建议的文字内容判断优先级"""
        if any(k in text for k in ["立即", "馬上", "緊急", "停機", "urgent"]):
            return "HIGH"
        elif any(k in text for k in ["建議", "檢查", "確認", "調整"]):
            return "MEDIUM"
        return "LOW"

    def _parse_float(self, value: str) -> Optional[float]:
        """安全地解析浮点数"""
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    def _extract_zscore_from_text(self, text: str) -> Optional[float]:
        """从一段文字中提取 Z-Score 数值"""
        m = re.search(r"Z-?[Ss]core\s*[=為为：:]\s*([-\d.]+)", text)
        if m:
            return self._parse_float(m.group(1))
        return None

    def _find_context(self, full_text: str, param: str) -> str:
        """找到参数在全文中的上下文描述"""
        # 找到参数附近的句子
        escaped = re.escape(param)
        m = re.search(rf"[^。\n]*{escaped}[^。\n]*[。\n]?", full_text)
        if m:
            ctx = m.group(0).strip()
            ctx = re.sub(r"\*\*([^*]+)\*\*", r"\1", ctx)
            return ctx[:200]
        return param
