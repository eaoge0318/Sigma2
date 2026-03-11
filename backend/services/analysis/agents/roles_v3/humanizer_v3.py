"""
V3 Humanizer — 結構化結果 → 人話報告
============================================================
將工具執行結果轉為面向用戶的 Markdown 報告。
報告長度根據工具數量自動調整。
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================
# Humanizer Prompt
# ============================================================

HUMANIZER_SYSTEM_PROMPT = """你是工業數據分析報告撰寫專家。根據分析結果，撰寫精簡、面向現場人員的報告。

## 核心原則
- **回答優先**: 報告第一段必須直接回答用戶的問題（如「影響 X 的 Top 5 參數是...」），不要囉嗦
- **精簡第一**: 總字數 400-800 字，多說結論少說過程
- **數據必引**: 必須引用具體數字（第幾筆、T²_drop、均值、z-score），嚴禁編造
- **合併同類**: 相似異常區間合併為一個發現，不要逐一列出

## 報告結構

### 分析概述
⚠️ **禁止寫「所有指標均在正常範圍」** — 如果任何參數有 Z-score 異常、漂移、突波、或 scan 異常，概述必須明確點名。
格式：「針對 [參數列表] 的分析結果：[N] 個參數正常，[M] 個參數發現異常（[參數名: 異常類型]）。」
只有**全部參數都沒有任何異常**時才能寫「均在正常範圍」。

### 目標參數模式
若 evaluation_summary 中有 📊 參數摘要，**不需要寫目標參數段落**（系統會自動注入程式化段落）。
直接跳到「發現」和「行動建議」即可。

### 無目標參數模式（全域探索）
使用下方的「發現 1/2/3」結構。

### 發現 1: [標題]
描述 + 關鍵數據（用粗體標注重要數字），根因推論一句話帶過。

**兩種主導因子來源（取決於分析路徑）**:
A. T² Marginal Drop (全域異常區間):
- **主導欄位**: `欄位名` T²_drop=X, 均值=Y, baseline=Z, z=W
- **次要欄位**: `欄位名` T²_drop=X ...

B. Scan Segment Deep Analysis (滑動窗口異常掃描):
- **主導因子**: `欄位名` (score=X 或 z_diff=X), `欄位名` (score=Y)
- **分組驗證**: `欄位名` 異常均值=A, 基線均值=B, z_diff=C
若 evaluation_summary 中有「主導因子」「top_factor」「t2_contrib」「group_comparison」等關鍵字，必須在報告中呈現，不可省略。

若多個區間有同樣主導欄位，合併列出區間號即可。

### 發現 2-3: ...
最多 3-4 個發現。相似的合併。

### 語義解讀（結論關鍵）
**在寫每個發現的結論和行動建議時，必須根據欄位名稱推理業務含義**：

1. **欄位名 → 業務語境**
   - 看到「厚度(前)/(後)」→ 理解為「製程前後的量測」，後 < 前 代表異常
   - 看到「左/中/右」→ 理解為「橫向均勻性」，std 大代表不均
   - 看到「電流_01~20」→ 理解為「多組同類設備」，個別偏低可能是故障
   - 看到「速度/溫度/壓力」→ 理解為「製程參數」，突變代表換料或調機
   - 看到「IPQC/良率/剝離」→ 理解為「品質指標」

2. **異常 → 業務解釋**
   - 不要只說「Z-score 異常 3 筆」，要加：「電鍍厚度異常下降，可能是量測位置偏移或基材受損」
   - 不要只說「漂移 4 段」，要加：「塗佈量呈階梯式變化，可能對應批次切換或配方調整」
   - 不要只說「index 191 異常」，要加：「建議核對該時段的現場日報表，確認是否為試作或維護」

3. **行動建議 → 具體可查**
   - 不要寫「比對設定值變更紀錄」（太空泛）
   - 要寫「核對 #191 附近的線速/溫度變更紀錄，確認是否為換料切換」

4. **⛔ 嚴禁腦補**
   - 語義解讀只能基於**欄位名字面意義**，不能編造領域知識
   - 欄位名是編碼（如 DCS_A335、BCDRY_A101）→ **不做語義解讀**，只報告統計數字
   - 欄位名有中文/明確意義（如 電鍍厚度、烘箱溫度）→ 才做業務解讀
   - 不確定的解讀必須加「(推測)」標記
   - 寧可不解讀，也不要說錯

### 行動建議
2-3 條，按優先順序，具體可行。

## 鐵律
1. 繁體中文 + Markdown
2. **只引用 stdout / data_summary 中實際出現的數字和欄位名**，沒有就寫「—」，嚴禁編造欄位名或數字。行動建議中的欄位名必須在分析結果中出現過
3. **最多 4 個發現**，相似區間必須合併（如「區間 #A-B 和 #C-D 的主導欄位均為同一類別」）
4. 不要重複 data_summary 的原始內容，要做歸納
5. |r|<0.2 只能寫「無實質相關」，0.2~0.4 寫「弱相關」，0.4~0.6 寫「中等相關」，|r|>0.6 寫「強相關」。|r|≥0.4 時禁止寫「無異常」「無關」
6. stdout 出現 [GUARDRAIL] 的結果不能當結論
7. 若異常樣本數 < 5，加註「小樣本，結論需驗證」
8. 語義一致性: evaluation_summary 中若有「⚠ 語義守衛」提示，必須嚴格遵守
9. Lag 描述: 必須翻譯為「X 領先 Y 約 N 步」的人話，不可只寫 lag=-8
10. Feature Importance: 必須寫「預測貢獻度」，不可暗示因果關係（如「X 導致 Y」是錯的）

## 語言精確度（嚴格遵守）
- **禁止因果用語**: 不可使用「原因是」「導致」「根因」「造成」「影響因素」
- **正確用語**:
  - T²_drop 高 → 「高疑似主導因子」或「統計上較可能的異常貢獻變數」
  - correlation → 「共變關係」，不是因果
  - 分組差異顯著 → 「該區間均值偏移顯著」，不是「該欄位導致異常」
- **結尾語氣**: 每個發現結尾應加「目前證據屬統計關聯，尚需現場確認」之類的限定語

## 區間信心度分級
A. T² 異常區間 — 根據 Top-3 T²_drop 總和:
- **T²_drop 總和 > 20**: 「明確主導」— 可直接寫「該欄位為此區間的主要異常貢獻變數」
- **T²_drop 總和 10-20**: 「中度可信」— 寫「該欄位為較可能的貢獻因子」
- **T²_drop 總和 < 10**: 「訊號較弱」— 必須寫「該區間異常訊號較弱，主導集中度不足，以下欄位僅為相對較高的候選」

B. Scan 異常區段 — 根據 severity_score 和是否有 top_factors:
- **有 top_factors 且 severity >= 5**: 直接引用 top_factors 列表中的欄位名和分數
- **有 top_factors 且 severity < 5**: 引用但需加註「訊號中等」
- **無 top_factors**: 寫「此區段未找到明確的主導因子」
- 不同區間必須使用對應等級的語氣，不可一律用同等確定性描述

## 行動建議規則
- 每條建議**必須引用至少一個具體數字**（偏移量、區間編號、p-value 等）
- 格式為「數據觀察 → 建議動作」:
  - ✅ 「`[欄位A]` 在 #N-M 均值從 X→Y（偏移 +Z），建議比對此時段設定值變更紀錄」
  - ❌ 「檢查配方比例與供應商批次一致性」（太 generic）
- 供應商批次、原料切換等屬於第二層假設，不可作為第一建議
- 第一建議永遠是「比對該區間的參數設定/切換紀錄」"""

HUMANIZER_SHORT_PROMPT = """你是工業數據分析助手。
根據工具執行結果，簡短回答用戶的問題。

規則:
1. 用繁體中文
2. 直接回答，不要囉嗦
3. 引用具體數字
4. 使用 Markdown 格式
"""


class HumanizerV3:
    """
    V3 Humanizer: 結構化結果 → 人話報告 (LLM #2)
    """

    def __init__(self, llm: Any):
        self.llm = llm

    async def generate_report(
        self,
        restatement: str,
        key_findings: list,
        tool_results: list,
        data_summary: str = "",
    ) -> str:
        """生成報告（一次性返回）"""
        sys_prompt, user_prompt = self._build_prompts(
            restatement, key_findings, tool_results, data_summary
        )

        # 呼叫 LLM
        try:
            full_prompt = sys_prompt + "\n\n" + user_prompt
            resp = await self.llm.acomplete(full_prompt)
            report = str(resp.text).strip()
            logger.info(f"[HumanizerV3] Generated report ({len(report)} chars)")

            # === D2: 程式層硬 gate — 缺數字自動降級 + D1: 數字可追湄性驗證 ===
            report = self._post_process(report, tool_results)

            return report
        except Exception as e:
            logger.error(f"[HumanizerV3] LLM failed: {e}, using fallback")
            return self._fallback_report(restatement, key_findings)

    async def generate_report_stream(
        self,
        restatement: str,
        key_findings: list,
        tool_results: list,
        data_summary: str = "",
        evaluation_summary: str = "",
    ):
        """
        串流版報告生成 — async generator, 逐 token yield。
        """
        sys_prompt, user_prompt = self._build_prompts(
            restatement,
            key_findings,
            tool_results,
            data_summary,
            evaluation_summary,
        )
        full_prompt = sys_prompt + "\n\n" + user_prompt
        logger.info(
            f"[HumanizerV3] Prompt size: sys={len(sys_prompt)}, "
            f"user={len(user_prompt)}, total={len(full_prompt)} chars"
        )
        try:
            response = self.llm.astream_complete(full_prompt)
            async for chunk in response:
                yield chunk.delta
        except Exception as e:
            logger.error(f"[HumanizerV3] Stream failed: {type(e).__name__}: {e}")
            yield self._fallback_report(restatement, key_findings)

    def _post_process(self, report: str, tool_results: list) -> str:
        """收集 CI stdout 並執行 evidence gate post-processing"""
        _ci_stdout = ""
        for _tr in tool_results:
            _r = (
                _tr.get("result", {})
                if isinstance(_tr, dict)
                else getattr(_tr, "result", {})
            )
            if isinstance(_r, dict) and "outputs" in _r:
                for _o in _r["outputs"]:
                    _ci_stdout += _o.get("stdout", "")
        return self._enforce_evidence_gate(report, stdout_text=_ci_stdout)

    def _build_prompts(
        self,
        restatement: str,
        key_findings: list,
        tool_results: list,
        data_summary: str = "",
        evaluation_summary: str = "",
    ) -> tuple:
        """組裝 system + user prompt (共用於 generate_report 和 stream)"""
        findings_text = (
            "\n".join(f"- {f}" for f in key_findings) if key_findings else "無異常發現"
        )
        tool_summaries = []
        for tr in tool_results:
            if hasattr(tr, "tool_name"):
                name = tr.tool_name
                success = tr.success
                result = tr.result
            elif isinstance(tr, dict):
                name = tr.get("tool_name", "unknown")
                success = tr.get("success", True)
                result = tr.get("result", {})
            else:
                continue
            summary = self._extract_tool_summary(name, result)
            tool_summaries.append(
                f"[{name}] {'成功' if success else '失敗'}: {summary}"
            )
        tools_text = "\n".join(tool_summaries) if tool_summaries else "無工具執行結果"

        _ci_stdout_parts = []
        MAX_STDOUT_PER_ROUND = 2000
        for _tr in tool_results:
            _r = (
                _tr.get("result", {})
                if isinstance(_tr, dict)
                else getattr(_tr, "result", {})
            )
            if isinstance(_r, dict) and "outputs" in _r:
                for _o in _r["outputs"]:
                    _s = _o.get("stdout", "")
                    if _s:
                        # 去掉所有 data_summary 區塊（本身已在 evidence_parts 裡）
                        # 匹配 [系統] 資料摘要 ... 到 [系統] 資料維度 或下一個 === 區塊
                        import re

                        _s = re.sub(
                            r"\[系統\] 資料摘要.*?(?=\n={5,}|\[系統\] 資料維度|$)",
                            "",
                            _s,
                            flags=re.DOTALL,
                        ).strip()
                        # 截斷
                        if len(_s) > MAX_STDOUT_PER_ROUND:
                            _s = _s[:2500] + "\n...(中間省略)...\n" + _s[-1000:]
                        if _s:
                            _ci_stdout_parts.append(
                                f"Round {_o.get('round', '?')} 輸出:\n{_s}"
                            )
        _ci_stdout_text = "\n".join(_ci_stdout_parts)
        evidence_parts = []
        if data_summary:
            _ds = data_summary[:2000] if len(data_summary) > 2000 else data_summary
            evidence_parts.append(f"=== 前處理分析摘要 ===\n{_ds}")
        if _ci_stdout_text:
            evidence_parts.append(
                f"=== Code Interpreter 執行結果 ===\n{_ci_stdout_text}"
            )
        evidence_text = "\n\n".join(evidence_parts)
        # Hard cap: 中文約 1.2~1.5 token/char，7000 chars ≈ 10000 tokens
        MAX_EVIDENCE_TOTAL = 7000
        if len(evidence_text) > MAX_EVIDENCE_TOTAL:
            evidence_text = (
                evidence_text[:5000] + "\n...(中間省略)...\n" + evidence_text[-1800:]
            )
        if evidence_text:
            evidence_text = (
                f"分析數據 (這些是實際計算結果，請直接引用):\n{evidence_text}"
            )

        tool_count = len(tool_results)
        is_ci = any(
            (
                getattr(tr, "tool_name", "") == "code_interpreter"
                or (isinstance(tr, dict) and tr.get("tool_name") == "code_interpreter")
            )
            for tr in tool_results
        )
        if tool_count <= 2 and len(key_findings) <= 3 and not is_ci:
            sys_prompt = HUMANIZER_SHORT_PROMPT
            user_prompt = (
                f"問題: {restatement}\n\n"
                f"結果:\n{findings_text}\n\n"
                f"工具結果:\n{tools_text}\n\n"
                f"簡短回答 (100-200 字):"
            )
        else:
            sys_prompt = HUMANIZER_SYSTEM_PROMPT
            eval_section = ""
            if evaluation_summary:
                eval_section = (
                    f"\n=== 證據評估結果 (已由系統判定嚴重性，請依此撰寫) ===\n"
                    f"{evaluation_summary}\n\n"
                )
            user_prompt = (
                f"需求: {restatement}\n\n"
                f"{eval_section}"
                f"關鍵發現:\n{findings_text}\n\n"
                f"{evidence_text}\n\n"
                f"工具結果摘要:\n{tools_text}\n\n"
                f"⚠ Round 2+ 分析: 若 CI stdout 含 Round 2 以上的相關性、分組對比、趨勢分段等深入分析結果，"
                f"必須在報告中呈現為獨立發現或補充分析段落，不可忽略。\n\n"
                f"請撰寫分析報告，嚴重性請依據上方評估結果（🔴高/🟡中/🟢低）撰寫:"
            )
        return sys_prompt, user_prompt

    def _extract_tool_summary(self, tool_name: str, result: Any) -> str:
        """從工具結果提取摘要 (避免塞入太多原始數據)"""
        if not isinstance(result, dict):
            return str(result)[:200]

        # 通用欄位
        if result.get("error"):
            return f"錯誤: {result['error']}"
        if result.get("summary"):
            return str(result["summary"])[:300]

        # 統計工具
        if "mean" in result:
            return (
                f"平均={result.get('mean', '?'):.4f}, "
                f"標準差={result.get('std', '?'):.4f}, "
                f"最大={result.get('max', '?'):.4f}, "
                f"最小={result.get('min', '?'):.4f}"
            )

        # 異常偵測
        if "outlier_count" in result or "z_score" in result:
            return (
                f"Z-Score={result.get('z_score', '?')}, "
                f"異常筆數={result.get('outlier_count', '?')}"
            )

        # 相關性
        if "top_correlations" in result:
            corrs = result["top_correlations"][:3]
            parts = []
            for c in corrs:
                if isinstance(c, dict):
                    parts.append(
                        f"{c.get('parameter', '?')}(r={c.get('correlation', 0):.2f})"
                    )
            return f"Top 相關: {', '.join(parts)}" if parts else "無顯著相關"

        # Code Interpreter: 拼接各 round 的 stdout
        if tool_name == "code_interpreter" and "outputs" in result:
            MAX_STDOUT_PER_ROUND = 2500
            parts = []
            for o in result["outputs"]:
                stdout = o.get("stdout", "")
                if stdout:
                    # 前後截取法: 保留開頭(戰略設計書+初步發現) 和 結尾(結論+summary)
                    if len(stdout) > MAX_STDOUT_PER_ROUND:
                        truncated = (
                            stdout[:1500] + "\n...(中間省略)...\n" + stdout[-1000:]
                        )
                    else:
                        truncated = stdout
                    parts.append(f"Round {o.get('round', '?')}:\n{truncated}")
            return (
                "\n---\n".join(parts) if parts else f"{result.get('rounds', 0)} rounds"
            )

        # 通用: 取前幾個 key
        keys = list(result.keys())[:5]
        return f"包含欄位: {', '.join(keys)}"

    def _fallback_report(self, restatement: str, findings: list) -> str:
        """LLM 失敗時的降級報告"""
        findings_text = (
            "\n".join(f"- {f}" for f in findings) if findings else "- 未發現異常"
        )
        return (
            f"## 分析報告\n\n"
            f"**需求:** {restatement}\n\n"
            f"**關鍵發現:**\n{findings_text}\n\n"
            f"_注: 此為自動生成的簡要報告_"
        )

    # ============================================================
    # D2: 程式層 Evidence Gate — LLM 輸出後自動降級
    # ============================================================

    _MISSING_DATA_TOKENS = [
        "需補充計算",
        "待計算",
        "待補充",
        "N/A",
        "未知",
        "需補算",
        "待確認",
        "需確認",
    ]

    _DETERMINISTIC_PHRASES = [
        "根因是",
        "根因為",
        "因為",
        "導致",
        "表示",
        "表明",
        "建議立即",
        "應立即",
        "必須立即",
        "證實",
        "確認了",
    ]

    def _enforce_evidence_gate(self, report: str, stdout_text: str = "") -> str:
        """
        掃描 LLM 報告，對缺數字的發現自動降級。

        策略:
        1. 偵測表格或段落中的缺值 token
        2. 找到對應的「發現 N」區塊
        3. 把根因分析段替換成「待驗證」
        4. 若有任何待驗證發現，降級綜合建議
        """
        import re

        # 檢查是否有缺值 token
        has_missing = any(token in report for token in self._MISSING_DATA_TOKENS)
        if not has_missing:
            return report

        logger.info("[HumanizerV3:EvidenceGate] 偵測到缺值 token，啟動降級")

        lines = report.split("\n")
        result_lines = []
        in_finding_block = False
        current_finding_has_missing = False
        any_finding_downgraded = False

        for i, line in enumerate(lines):
            stripped = line.strip()

            # 偵測「發現 N」或「### 發現」標題
            if re.match(r"^#{1,3}\s*(發現|Finding)\s*\d*", stripped):
                in_finding_block = True
                current_finding_has_missing = False
                # 向前看這個 block 是否有缺值
                block_text = "\n".join(lines[i : min(i + 40, len(lines))])
                current_finding_has_missing = any(
                    token in block_text for token in self._MISSING_DATA_TOKENS
                )
                if current_finding_has_missing:
                    any_finding_downgraded = True
                    # 改標題加「待驗證」
                    if "待驗證" not in stripped:
                        line = line.replace("發現", "待驗證發現", 1)
                        logger.info(f"[EvidenceGate] 降級: {stripped}")
                result_lines.append(line)
                continue

            # 偵測「綜合建議」區塊
            if re.match(r"^#{1,3}\s*綜合建議", stripped):
                in_finding_block = False
                result_lines.append(line)
                if any_finding_downgraded:
                    result_lines.append("")
                    result_lines.append(
                        "> ⚠️ **注意**: 上述部分發現的數據不完整（表格有缺值），"
                        "以下建議僅供參考方向，需補齊分析後才能確定行動方案。"
                    )
                continue

            # 在「有缺值的發現」中降級確定性措辭
            if in_finding_block and current_finding_has_missing:
                # 替換根因分析段
                if re.match(r"^[-\*]?\s*\*?\*?根因分析\*?\*?\s*[:：]", stripped):
                    line = (
                        "- **根因分析**: 待驗證"
                        "（表格數字不足，需補算均值/標準差/差異/檢定結果後才能下結論）"
                    )
                    result_lines.append(line)
                    continue

                # 把確定性措辭加警告
                for phrase in self._DETERMINISTIC_PHRASES:
                    if phrase in line:
                        line = line.replace(phrase, f"[待驗證] {phrase}")

            result_lines.append(line)

        result = "\n".join(result_lines)
        logger.info(
            f"[HumanizerV3:EvidenceGate] 降級完成, downgraded={any_finding_downgraded}"
        )

        # === D1: 數字可追溯性檢查 ===
        # 只有 CI 模式且有 stdout 時才做，避免誤殺普通小數
        if stdout_text and len(stdout_text) > 50:
            result = self._check_number_provenance(result, stdout_text)

        # === D2: 欄位名可追溯性檢查 ===
        if stdout_text and len(stdout_text) > 50:
            result = self._check_column_provenance(result, stdout_text)

        return result

    def _check_number_provenance(self, report: str, stdout_text: str) -> str:
        """
        D1: 找出報告中所有有小數點的數字，檢查是否可在 stdout 中找到。
        找不到的加上 ⚠️[needs-review] 標記（小數點 2 位以上）。
        """
        import re

        # 從 stdout 取出所有數字
        _stdout_nums_raw = re.findall(r"[-+]?\d+\.\d+", stdout_text)
        _stdout_nums = set()
        for _n in _stdout_nums_raw:
            try:
                _stdout_nums.add(float(_n))
            except ValueError:
                pass

        if not _stdout_nums:
            return report  # stdout 沒有數字，不做驗證

        def _in_stdout(val: float) -> bool:
            """容差貲 ±5%，並允許整數比對"""
            if val == 0:
                return True  # 0 不算編造
            return any(abs(val - s) / (abs(s) + 1e-9) < 0.05 for s in _stdout_nums)

        # 找出報告中的 2+ 小數點數字
        _suspicious_count = 0

        def _replace_if_unverified(m):
            nonlocal _suspicious_count
            raw = m.group(0)
            try:
                val = float(raw)
            except ValueError:
                return raw
            # 小數點 < 2 位不管（如 0.6），只管 2+ 位
            if "." not in raw or len(raw.split(".")[-1]) < 2:
                return raw
            if _in_stdout(val):
                return raw
            _suspicious_count += 1
            return f"{raw}⚠️"

        report_out = re.sub(r"[-+]?\d+\.\d{2,}", _replace_if_unverified, report)

        if _suspicious_count > 0:
            logger.warning(
                f"[HumanizerV3:D1] {_suspicious_count} 個數字無法在 stdout 中找到，已加標 ⚠️"
            )
            # 在報告最後加讓用戶知道的警告
            report_out += (
                f"\n\n> ⚠️ **數據可信度警示**: {_suspicious_count} 個報告中的數字無法從分析 stdout 中查到對應紀錄"
                f"（標記為 ⚠️）。建議檢驗這些數字的來源。"
            )

        return report_out

    def _check_column_provenance(self, report: str, stdout_text: str) -> str:
        """
        D2: 找出報告中所有看起來像欄位名的 token（含 - 或 _ 且長度 >= 5），
        檢查是否在 stdout 中出現過。沒出現的加 ⚠️[欄位未確認] 標記。
        """
        import re

        # 從 stdout 中提取所有 column-like tokens (含 - 或 _)
        _stdout_tokens = set(re.findall(r"[A-Za-z][A-Za-z0-9_-]{4,}", stdout_text))

        if not _stdout_tokens:
            return report

        # 從報告中找所有看起來像欄位名的 token
        _report_col_pattern = re.compile(
            r"(?<![\w/])"
            r"([A-Z][A-Z0-9]*[-_][A-Z0-9_-]{2,})"
            r"(?![\w/])"
        )

        _flagged = set()
        _seen = set()

        def _replace_col(m):
            col = m.group(1)
            if col in _seen:
                # 已經檢查過，如果被 flag 過就繼續 flag
                if col in _flagged:
                    return f"{col}⚠️[欄位未確認]"
                return col
            _seen.add(col)
            # 檢查是否在 stdout 中（大小寫敏感）
            if col in _stdout_tokens:
                return col
            _flagged.add(col)
            return f"{col}⚠️[欄位未確認]"

        report_out = _report_col_pattern.sub(_replace_col, report)

        if _flagged:
            logger.warning(
                f"[HumanizerV3:D2] {len(_flagged)} 個欄位名無法在 stdout 中找到: {_flagged}"
            )
            report_out += (
                f"\n\n> ⚠️ **欄位名可信度警示**: {len(_flagged)} 個欄位名無法從分析結果中確認"
                f"（標記為 ⚠️[欄位未確認]）: {', '.join(sorted(_flagged))}。"
                f"這些欄位可能不存在於此資料集中。"
            )

        return report_out
