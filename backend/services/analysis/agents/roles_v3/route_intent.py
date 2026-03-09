"""
V3 RouteIntent Agent — 統一合約路由
============================================================
一次 LLM 完成:
  1. 需求重述 (Restatement)
  2. 任務類型判斷 (task_type)
  3. 目標參數 + 區間識別
  4. 工具鏈選取 (suggested_tools, 最多 12 個)
"""

import json
import logging
from typing import Any, Dict, List, Optional

from backend.services.analysis.analysis_types_v3 import RouteIntentOutput

logger = logging.getLogger(__name__)

# ============================================================
# RouteIntent System Prompt
# ============================================================

ROUTE_INTENT_SYSTEM_PROMPT = """你是工業數據分析系統的意圖路由器 (RouteIntent)。
你的任務是：理解用戶的問題，並規劃最佳的分析路徑。

## 你必須輸出一個 JSON，格式嚴格如下:

```json
{{
  "restatement": "用一句話重述用戶的分析需求（補齊用戶沒說清楚的部分）",
  "task_type": "anomaly_detection 或 drift_analysis 或 optimization 或 spec_recommendation 或 global_analysis 或 general",
  "target_params": [],
  "reference_params": [],
  "target_range": [],
  "baseline_range": "",
  "clarification_question": null
}}
```

## task_type 判斷規則:

**優先級: anomaly_detection > optimization。**
「哪幾筆/哪段有問題」「異常區間」這類找異常的問法，永遠是 anomaly_detection。
  **但如果用戶同時提到了具體欄位名 (如 PMRL-MCC_116)，那些欄位名仍必須放入 target_params。**
「控制/穩定」只有在用戶**同時明確提到某個欄位名**時才算 optimization。

- **anomaly_detection**: 用戶問「為什麼異常」「哪裡有問題」「異常原因」「outlier」「OOC」「哪幾筆」「哪段」「異常區間」
- **drift_analysis**: 用戶問「飄移」「偏移」「shift」「前後差異」「品質變化」「趨勢變化」
- **optimization**: 用戶提到**具體欄位名** + 「最佳化」「怎麼調整」「參數組合」「sweet spot」「最佳操作窗口」「控制」「穩定」「壓下來」「拉上去」「降低波動」「調整哪些參數」
- **spec_recommendation**: 用戶問「建議規格」「管制界限」「spec」「上下限」「操作範圍」
- **global_analysis**: 用戶問「全域」「整體狀況」「幫我看看」「分析一下」(模糊問句)
- **general**: 其他無法歸類的情況

## 可用欄位 (部分):
{column_hint}

## target_params 規則:
- 只能填「可用欄位」列表中實際存在的欄位名
- 絕對不能填概念詞 (水份不均、品質差...)
- 概念類問題一律 target_params 留空，task_type 設為 global_analysis
- **optimization / spec_recommendation 情境**: 用戶提到欄位名 + 「最佳化/optimize/調整/sweet spot/建議規格」時，
  該欄位就是 target_params（可以有多個）。例:
  - 「[欄位A] 最佳化」→ target_params=["[欄位A]"]
  - 「幫我最佳化 X 和 Y」→ target_params=["X", "Y"]
- **anomaly_detection 情境**: 用戶提到欄位名 + 「異常/為什麼/問題」時，該欄位放入 target_params
- **drift_analysis 情境**: 用戶提到欄位名 + 「飄移/偏移/趨勢」時，該欄位放入 target_params
- 總結: 只要用戶明確提到了真實欄位名，就應該放入 target_params，不論 task_type
- **最高優先: 用戶 query 中出現的任何精確欄位名（含 - _ 數字），無論分析類型，都必須放入 target_params。這條規則覆蓋其他所有規則。**

## target_range 規則:
- 用戶指定了目標資料範圍 (如 "第30-50筆", "30到50", "#30-50") → target_range=["30-50"]
- 用戶指定多個區間 (如 "第30-50筆和100-120筆") → target_range=["30-50", "100-120"]
- **重要: 欄位名後接 `#N-M` 表示該欄位的第 N 到 M 筆樣本區間，`#N-M` 不是欄位名的一部分！**
  例: "METROLOGY-P21 #222-243" → target_params=["METROLOGY-P21"], target_range=["222-243"]
- 用戶未指定範圍 → target_range=[]

## baseline_range 規則 (對照區間):
- 用戶提到「好批 vs 壞批」「前後比較」「正常區 vs 異常區」時，將正常/好的區間填入 baseline_range
  例: "比較第100-200筆(壞批)和第1-99筆(好批)" → target_range=["100-200"], baseline_range="1-99"
- 用戶只說了目標區間沒有對照 → baseline_range=""

## reference_params 規則 (對照參數):
- 用戶提到「某參數跟哪些參數的關係」時，將「哪些參數」填入 reference_params
- 用戶提到「類別型分析」時，類別欄位填入 reference_params
- 用戶未指定對照 → reference_params=[]

## clarification_question:
只有在用戶問題極度模糊（連分析方向都無法判斷）時才填入追問問題。

## 重要:
- 只回傳 JSON，不要回傳其他內容
"""


# ============================================================
# RouteIntent Agent
# ============================================================


class RouteIntentAgent:
    """
    V3 RouteIntent: 一次 LLM 完成意圖解析 + 工具鏈選取

    輸入: 用戶問句 + 欄位列表 + 資料摘要
    輸出: RouteIntentOutput (結構化 JSON)
    """

    def __init__(self, llm: Any):
        self.llm = llm

    async def run(
        self,
        query: str,
        columns: List[str],
        column_mappings: Dict[str, str],
        data_summary: Optional[Dict] = None,
        history: str = "",
    ) -> RouteIntentOutput:
        """
        執行 RouteIntent

        Args:
            query: 用戶問句
            columns: 所有欄位名稱列表
            column_mappings: 欄位中文對照表 {英文: 中文}
            data_summary: 資料摘要 {row_count, col_count, ...}

        Returns:
            RouteIntentOutput
        """

        # --- 1. 構建欄位提示 (含中文名) ---
        col_hint = self._build_column_hint(columns, column_mappings)

        # --- 2. 構建 Prompt ---
        prompt = ROUTE_INTENT_SYSTEM_PROMPT.format(
            column_hint=col_hint,
        )

        # 資料描述
        data_desc = ""
        if data_summary:
            rc = data_summary.get("row_count", "?")
            cc = data_summary.get("col_count", "?")
            data_desc = f"資料集: {rc} 筆, {cc} 個參數。"

        # 注入最近對話歷史，讓 LLM 理解追問的前後文
        # 只有當 query 精確匹配已知欄位名時才跳過 history（避免腦補）
        # 其他短 query（如「前十筆」「全部」）都需要 history
        _query_stripped = query.strip()
        _is_bare_column = _query_stripped in columns if columns else False
        if not _is_bare_column and columns:
            # 也檢查 normalize 後是否匹配
            _qn = self._normalize(_query_stripped)
            _is_bare_column = (
                any(self._normalize(c) == _qn for c in columns)
                if _qn and len(_qn) >= 4
                else False
            )
        history_section = ""
        if history and not _is_bare_column:
            # 取最後 3 輪 (最多 6 條 user+assistant)
            lines = history.strip().split("\n")
            recent_lines = lines[-6:] if len(lines) > 6 else lines
            # 最後一條 assistant 保留較長 (最靠近，最重要)
            # 前面的截短
            trimmed = []
            last_asst_idx = -1
            for i, ln in enumerate(recent_lines):
                if ln.startswith("Assistant:"):
                    last_asst_idx = i
            for i, ln in enumerate(recent_lines):
                if ln.startswith("Assistant:"):
                    if i == last_asst_idx:
                        # 最近一條: 保留 500 字
                        if len(ln) > 550:
                            trimmed.append(ln[:550] + "...")
                        else:
                            trimmed.append(ln)
                    else:
                        # 較早的: 截到 150 字
                        if len(ln) > 200:
                            trimmed.append(ln[:200] + "...")
                        else:
                            trimmed.append(ln)
                else:
                    trimmed.append(ln)
            history_section = "\n最近對話:\n" + "\n".join(trimmed) + "\n"

        user_prompt = f"{data_desc}{history_section}\n用戶問題: {query}\n\n回傳 JSON:"

        # --- 3. 呼叫 LLM ---
        try:
            full_prompt = prompt + "\n\n" + user_prompt
            resp = await self.llm.acomplete(full_prompt, json_mode=True)
            resp_text = str(resp.text).strip()
            logger.info(f"[RouteIntent] LLM raw: {resp_text[:200]}")

            # Parse JSON
            result_json = self._parse_json(resp_text)
            output = self._validate_output(result_json, columns, column_mappings, query)
            logger.info(
                f"[RouteIntent] task_type={output.task_type}, "
                f"targets={output.target_params}, "
                f"tools={output.suggested_tools[:3]}, "
                f"has_y={output.has_y}"
            )
            return output

        except Exception as e:
            logger.error(f"[RouteIntent] LLM failed: {e}, fallback to global_analysis")
            return RouteIntentOutput(
                restatement=f"分析需求: {query}",
                task_type="global_analysis",
                has_y=False,
                suggested_tools=["combo_parameter_profiling"],
            )

    def _build_column_hint(
        self,
        columns: List[str],
        mappings: Dict[str, str],
        max_show: int = 60,
    ) -> str:
        """
        構建欄位提示字串 (英文名 + 中文名)
        最多顯示 max_show 個，避免 prompt 過長
        """
        lines = []
        show_cols = columns[:max_show]
        for col in show_cols:
            cn = mappings.get(col, "")
            if cn:
                lines.append(f"  {col} ({cn})")
            else:
                lines.append(f"  {col}")
        if len(columns) > max_show:
            lines.append(f"  ... (共 {len(columns)} 個欄位)")
        return "\n".join(lines)

    def _parse_json(self, text: str) -> dict:
        """解析 LLM 回傳的 JSON (容錯 markdown code block)"""
        text = text.strip()
        if "```" in text:
            parts = text.split("```")
            if len(parts) >= 2:
                text = parts[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
        return json.loads(text)

    def _validate_output(
        self,
        raw: dict,
        columns: List[str],
        mappings: Dict[str, str],
        query: str = "",
    ) -> RouteIntentOutput:
        """
        驗證並修正 LLM 輸出:
        - task_type 必須是合法值
        - target_params 必須存在於欄位列表中
        - suggested_tools 最多 12 個
        - 無精確欄位匹配時 has_y=false
        """
        restatement = raw.get("restatement", "")
        target_params = raw.get("target_params", [])
        target_range = raw.get("target_range", [])

        # --- target_range 型別防穡 ---
        if target_range is None:
            target_range = []
        elif isinstance(target_range, str):
            # 相容舊版 LLM 輸出 "50-69" 或 "all"
            if target_range in ("all", ""):
                target_range = []
            else:
                target_range = [target_range]
        target_range = [
            t for t in target_range if isinstance(t, str) and t.strip() and t != "all"
        ]

        # --- target_params 型別防禦 ---
        if target_params is None:
            target_params = []
        elif isinstance(target_params, str):
            target_params = [target_params]
        target_params = [t for t in target_params if isinstance(t, str) and t.strip()]
        logger.info(
            f"[RouteIntent:validate] LLM raw target_params={target_params}, "
            f"task_type={raw.get('task_type', '?')}, "
            f"columns_count={len(columns)}, query='{query[:80]}'"
        )

        # 驗證 task_type
        _VALID_TASK_TYPES = {
            "anomaly_detection",
            "drift_analysis",
            "optimization",
            "spec_recommendation",
            "global_analysis",
            "general",
        }
        task_type = raw.get("task_type", "general")
        if task_type not in _VALID_TASK_TYPES:
            task_type = "general"

        # 驗證 target_params: 只接受精確匹配的真實欄位名
        validated_targets = []
        for t in target_params:
            if t in columns:
                validated_targets.append(t)
            else:
                matched = self._fuzzy_match_column(t, columns, mappings)
                if matched:
                    validated_targets.append(matched)
                else:
                    logger.warning(
                        f"[RouteIntent] '{t}' 不是真實欄位名, 忽略 (columns sample: {columns[:3]})"
                    )

        # has_y 衍生
        has_y = len(validated_targets) > 0

        # === 兜底: LLM 沒設 target_params 但 query 裡有真實欄位名 ===
        if not validated_targets and query:
            extracted = self._extract_columns_from_query(query, columns, mappings)
            if extracted:
                validated_targets = extracted
                has_y = True
                logger.info(
                    f"[RouteIntent] 兜底提取 target_params={extracted} from query"
                )
            else:
                logger.warning(
                    f"[RouteIntent] 兜底也沒抓到欄位! "
                    f"query='{query[:80]}', columns_count={len(columns)}, "
                    f"columns_sample={columns[:5]}"
                )

        # 無目標參數時，如果 task_type 不是全域類，也不強制改
        # 讓 execute_tools 根據 has_y 決定工具的參數模式

        # suggested_tools: Code Interpreter 模式下不需要，一律空
        suggested_tools = []

        # 追問
        clarification = raw.get("clarification_question")
        if clarification:
            suggested_tools = []  # 有追問就不跑工具

        # 驗證 reference_params
        reference_params = raw.get("reference_params", [])
        validated_refs = []
        for r in reference_params:
            if r in columns:
                validated_refs.append(r)
            else:
                matched = self._fuzzy_match_column(r, columns, mappings)
                if matched:
                    validated_refs.append(matched)

        # 驗證 baseline_range
        baseline_range = raw.get("baseline_range", "")
        if not isinstance(baseline_range, str):
            baseline_range = ""

        return RouteIntentOutput(
            restatement=restatement,
            task_type=task_type,
            target_params=validated_targets,
            reference_params=validated_refs,
            target_range=target_range,
            baseline_range=baseline_range,
            has_y=has_y,
            suggested_tools=suggested_tools,
            clarification_question=clarification,
        )

    # ============================================================
    # 欄位名匹配工具
    # ============================================================

    @staticmethod
    def _normalize(s: str) -> str:
        """統一化: 去掉 -_空白全形符號，保留 A-Z0-9 和中文字元"""
        import re

        return re.sub(r"[^A-Z0-9\u4e00-\u9fff]", "", s.upper())

    def _fuzzy_match_column(
        self,
        target: str,
        columns: List[str],
        mappings: Dict[str, str],
    ) -> Optional[str]:
        """
        多層匹配欄位名:
        1. 大小寫不敏感的完全匹配
        2. normalize 後完全匹配 (忽略 -_空白)
        3. 中文映射反查 (mappings value → key)
        4. normalize 後 substring 匹配 (>= 4 chars)
        5. 尾碼匹配 (如 A12 → SECTION-DCS_A12)，僅唯一候選時命中
        """
        target_stripped = target.strip()
        if not target_stripped:
            return None

        target_lower = target_stripped.lower()
        target_norm = self._normalize(target_stripped)

        # 1. 大小寫不敏感的完全匹配
        for col in columns:
            if col.lower() == target_lower:
                return col

        # 2. normalize 後完全匹配
        for col in columns:
            if self._normalize(col) == target_norm:
                return col

        # 3. 中文映射反查: mappings = {英文: 中文}
        if mappings:
            for en_col, cn_name in mappings.items():
                if cn_name and target_stripped in cn_name or cn_name in target_stripped:
                    if en_col in columns:
                        return en_col

        # 4. normalize 後 substring 匹配 (>= 4 chars)
        if len(target_norm) >= 4:
            candidates = [col for col in columns if target_norm in self._normalize(col)]
            if len(candidates) == 1:
                return candidates[0]
            # 多個候選: 取最短的（最精確的匹配）
            if candidates:
                return min(candidates, key=len)

        # 5. 尾碼匹配 (如 A12 → SECTION-DCS_A12)
        if len(target_norm) >= 2:
            candidates = [
                col for col in columns if self._normalize(col).endswith(target_norm)
            ]
            if len(candidates) == 1:
                return candidates[0]
            # 多個候選: 不自動選，避免誤判
            if len(candidates) > 1:
                logger.info(
                    f"[RouteIntent] 尾碼 '{target_stripped}' 有 {len(candidates)} 個候選, 不自動選"
                )

        return None

    def _extract_columns_from_query(
        self,
        query: str,
        columns: List[str],
        mappings: Dict[str, str] = None,
    ) -> List[str]:
        """
        從 query 中確定性提取真實欄位名（兜底機制）。
        策略:
        1. normalize 後精確 substring 匹配（長欄位名優先）
        2. 中文映射匹配
        3. 尾碼匹配（僅唯一候選時命中）
        """
        import re

        # 清掉 code fence / markdown 標記
        clean_query = re.sub(r'[`"\'\'\']', "", query)
        query_norm = self._normalize(clean_query)
        found = []
        found_norms = set()  # 已匹配的 normalize 形式，防重複

        # --- 0. 精確原文匹配 (最高優先，避免 normalize 歧義) ---
        # 先用原始欄位名在清洗後 query 中做 case-insensitive 精確子字串匹配
        sorted_cols = sorted(columns, key=len, reverse=True)
        _clean_lower = clean_query.lower()
        for col in sorted_cols:
            if len(col) < 4:
                continue
            if col.lower() in _clean_lower:
                col_norm = self._normalize(col)
                if col_norm not in found_norms:
                    found.append(col)
                    found_norms.add(col_norm)

        # 精確匹配到了就直接返回，不走 normalize 層（避免子字串歧義）
        if found:
            logger.info(f"[RouteIntent] 精確原文匹配: {found}")
            return found

        # --- 1. normalize 後 substring 匹配 (長的優先, fallback) ---
        for col in sorted_cols:
            col_norm = self._normalize(col)
            if len(col_norm) < 4:
                continue
            if col_norm in query_norm and col_norm not in found_norms:
                found.append(col)
                found_norms.add(col_norm)

        # --- 2. 中文映射匹配 ---
        if mappings and not found:
            for en_col, cn_name in mappings.items():
                if cn_name and len(cn_name) >= 2 and cn_name in clean_query:
                    if en_col in columns and en_col not in found:
                        found.append(en_col)

        # --- 3. 尾碼匹配 (從 query 中抽取 token) ---
        if not found:
            tokens = re.findall(r"[A-Za-z]\d{1,4}", clean_query)
            for token in tokens:
                token_norm = token.upper()
                candidates = [
                    col for col in columns if self._normalize(col).endswith(token_norm)
                ]
                if len(candidates) == 1 and candidates[0] not in found:
                    found.append(candidates[0])

        # --- 4. 前綴模糊匹配 (SECTION-DCS_A1 → A12, A19, A21...) ---
        if not found:
            # 從 query 中抽取看起來像欄位名的 token (英數+-_)
            col_like_tokens = re.findall(r"[A-Za-z][A-Za-z0-9_\-]{3,}", clean_query)
            for token in col_like_tokens:
                token_norm = self._normalize(token)
                if len(token_norm) < 4:
                    continue
                # 找 normalize 後以 token_norm 為前綴的欄位
                prefix_matches = [
                    col
                    for col in columns
                    if self._normalize(col).startswith(token_norm) and col not in found
                ]
                if prefix_matches:
                    found.extend(prefix_matches[:5])  # 最多取 5 個
                    logger.info(
                        f"[RouteIntent] 前綴匹配 '{token}' → {prefix_matches[:5]}"
                    )

        return found
