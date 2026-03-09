from typing import Any, Dict, AsyncGenerator, List
import logging
from backend.services.analysis.analysis_types import (
    StartEvent,
    AnalysisState,
    AnalysisContext,
    AnalysisReport,
    RoleInput,
    RoleOutput,
    StepResult,
    ProgressEvent,
    MonologueEvent,
    TextChunkEvent,
    ExperimentContext,
    Evidence,
)
from collections import Counter
from backend.services.analysis.knowledge_utils import (
    build_initial_knowledge,
    append_routing,
    inject_to_section,
)

# Import V2 Roles
from .roles_v2.strategist import Strategist
from .roles_v2.planner import ExperimentPlanner
from .roles_v2.executor import BatchExecutor
from .roles_v2.synthesizer import Synthesizer


class OrchestratedAnalysisAgentV2:
    """
    [V2 Architecture] Orchestrated Agent with Batch Analysis Loop
    Flow: Strategist -> Planner -> Executor -> Synthesizer
    """

    MAX_STEPS = 10  # Default max (overridden by mode)
    QUICK_MAX_STEPS = 5  # Quick mode: focused scan
    DEEP_MAX_STEPS = 60  # Deep mode: thorough investigation

    def __init__(
        self,
        llm: Any,
        tool_executor: Any,
        analysis_service: Any = None,
        shared_states: Dict[str, Any] = None,
        chat_history_service: Any = None,
    ):
        self.llm = llm
        self.executor = tool_executor
        self.analysis_service = analysis_service
        self.chat_history_service = chat_history_service
        self.logger = logging.getLogger("OrchestratedAgentV2")

        # [RESUME] In-memory cache of last analysis state per session+file
        # 如果外部傳入 shared_states，使用它 (跨請求保留)
        # 否則建立新的 dict (僅本次請求有效)
        self._last_states: Dict[str, Any] = (
            shared_states if shared_states is not None else {}
        )

        # [RESUME] 排除已分析的目標參數 (續查時填入, 用於代碼層級過濾場景)
        self._resume_excluded_targets: set = set()

        # [CHAT→ANALYSIS] 待確認的領域問題 (用戶確認後自動觸發分析)
        self._pending_domain_queries: Dict[str, str] = {}

        # Initialize V2 Roles
        self.roles = {
            "strategist": Strategist(llm),
            "planner": ExperimentPlanner(llm),
            "executor": BatchExecutor(llm, tool_executor),  # Uses updated adapter
            "synthesizer": Synthesizer(llm),
        }

    # ── State Persistence Helpers ──────────────────────────

    @staticmethod
    def _state_key(session_id: str, file_id: str = "") -> str:
        """Build composite key for _last_states."""
        return f"{session_id}:{file_id}" if file_id else session_id

    def _serialize_state_entry(self, entry: Dict) -> Dict:
        """
        將 _last_states 的 entry 序列化為可 JSON 化的 dict。
        entry = {"state": AnalysisState, "summary_data": dict, "is_deep": bool, "max_turns": int}
        """
        import json

        state_obj = entry.get("state")
        if state_obj is None:
            return {}

        try:
            # AnalysisState 是 Pydantic BaseModel，用 .dict() 序列化
            state_dict = state_obj.dict() if hasattr(state_obj, "dict") else {}

            # evidence 欄位是 Any，可能有不可序列化的物件
            # 先做一輪 JSON round-trip 用 default=str 降級
            sanitized = json.loads(
                json.dumps(state_dict, ensure_ascii=False, default=str)
            )

            return {
                "state": sanitized,
                "summary_data": entry.get("summary_data", {}),
                "is_deep": entry.get("is_deep", False),
                "max_turns": entry.get("max_turns", 5),
            }
        except Exception as e:
            self.logger.error(f"State serialization failed: {e}")
            return {}

    def _deserialize_state_entry(self, data: Dict) -> Dict:
        """
        從磁碟讀取的 dict 還原為 _last_states entry。
        state 欄位還原為 AnalysisState 物件。
        """
        state_dict = data.get("state", {})
        if not state_dict or not isinstance(state_dict, dict):
            return {}

        try:
            # 從 dict 重建 AnalysisState (Pydantic 會自動處理嵌套模型)
            state_obj = AnalysisState(**state_dict)
            return {
                "state": state_obj,
                "summary_data": data.get("summary_data", {}),
                "is_deep": data.get("is_deep", False),
                "max_turns": data.get("max_turns", 5),
            }
        except Exception as e:
            self.logger.warning(f"State deserialization failed (may be stale): {e}")
            return {}

    def _persist_state(self, session_id: str, file_id: str, entry: Dict) -> None:
        """同時寫入記憶體和磁碟。"""
        _key = self._state_key(session_id, file_id)
        self._last_states[_key] = entry

        # 非同步寫入磁碟 (不阻塞主流程)
        if self.chat_history_service:
            try:
                serialized = self._serialize_state_entry(entry)
                if serialized:
                    self.chat_history_service.save_analysis_state(
                        session_id, file_id, serialized
                    )
            except Exception as e:
                self.logger.error(f"State disk persist failed: {e}")

    def _load_state_from_disk(self, session_id: str, file_id: str) -> bool:
        """
        嘗試從磁碟載入 state 到 _last_states。
        回傳 True 如果成功載入。
        """
        _key = self._state_key(session_id, file_id)
        if _key in self._last_states:
            return True  # 已在記憶體中

        if not self.chat_history_service:
            return False

        disk_data = self.chat_history_service.load_analysis_state(session_id, file_id)
        if not disk_data:
            return False

        entry = self._deserialize_state_entry(disk_data)
        if entry:
            self._last_states[_key] = entry
            self.logger.info(
                f"Restored state from disk for {session_id}:{file_id} "
                f"(version={entry['state'].version})"
            )
            return True
        return False

    def has_saved_state(self, session_id: str, file_id: str = "") -> bool:
        """Check if there is a saved analysis state for this session+file."""
        _key = self._state_key(session_id, file_id)
        _in_memory = _key in self._last_states
        # [DEBUG] 強力追蹤
        _all_keys = list(self._last_states.keys())
        print(
            f"[HAS_SAVED_STATE] key='{_key}', in_memory={_in_memory}, "
            f"all_keys={_all_keys}"
        )
        if _in_memory:
            _cached = self._last_states[_key]
            _sq = (
                getattr(_cached.get("state"), "scene_queue", None) if _cached else None
            )
            print(
                f"[HAS_SAVED_STATE] FOUND! scene_queue="
                f"{len(_sq) if _sq else 0} scenes, "
                f"pending={sum(1 for s in (_sq or []) if s.status == 'PENDING')}"
            )
            return True
        # [PERSIST] Fallback: try loading from disk
        _disk = self._load_state_from_disk(session_id, file_id)
        print(f"[HAS_SAVED_STATE] disk fallback={_disk}")
        return _disk

    async def run_analysis(
        self,
        start_event: StartEvent,
        summary_data: Dict,
        resume: bool = False,
        scene_continue: bool = False,
    ) -> AsyncGenerator[Any, None]:
        """
        V2 Main Loop (Async Batch Execution)
        """
        session_id = start_event.session_id
        file_id = getattr(start_event, "file_id", "")
        _key = self._state_key(session_id, file_id)

        # [RESUME PATH] If resuming from a previous analysis, load cached state
        # [PERSIST] Try loading from disk if not in memory
        if resume and _key not in self._last_states:
            self._load_state_from_disk(session_id, file_id)
        if resume and not scene_continue and _key in self._last_states:
            cached = self._last_states[_key]
            state = cached["state"]
            is_deep = cached["is_deep"]
            max_turns = cached["max_turns"]
            summary_data = cached["summary_data"]

            # ── [排除記憶] 提取上次分析的關鍵發現 ──
            # 1) 已使用工具
            _prev_tools = set(
                t.split("::")[0] for t in (state.used_tools_history or [])
            )
            _prev_tools_str = ", ".join(sorted(_prev_tools)) if _prev_tools else "無"

            # 2) 已分析的參數目標 (從場景 targets 提取)
            _prev_targets = set()
            _prev_findings = []
            for scene in state.scene_queue or []:
                for t in scene.targets or []:
                    _prev_targets.add(t)
                for f in scene.findings or []:
                    _prev_findings.append(f)

            # 3) 從 StepResult history 額外提取結論
            for step in state.history or []:
                if step.tool_params:
                    # 提取 target/targets 參數
                    for key in ("target", "targets", "parameter"):
                        val = step.tool_params.get(key, "")
                        if val:
                            for p in str(val).split(","):
                                p = p.strip()
                                if p:
                                    _prev_targets.add(p)

            _prev_targets_str = (
                ", ".join(sorted(_prev_targets)) if _prev_targets else "無"
            )
            _prev_findings_str = (
                "\n".join(f"  - {f}" for f in _prev_findings[:10])
                if _prev_findings
                else "  - 無顯著發現"
            )

            # 4) 已失敗的實驗
            _prev_failed = state.failed_experiments or []

            # 5) 已發現的異常區段 (供續查生成 segment 場景)
            _prev_segments = []
            for site in state.discovered_sites or []:
                seg_str = getattr(site, "row_range", "") or ""
                if seg_str:
                    _prev_segments.append(seg_str)
            # 也從 scene_queue 中提取 segment 類型場景的資訊
            for scene in state.scene_queue or []:
                if getattr(scene, "scene_type", "") == "segment":
                    _seg_label = getattr(scene, "label", "")
                    if _seg_label and _seg_label not in _prev_segments:
                        _prev_segments.append(_seg_label)
            # 從 current_knowledge 中提取 Row 區段 (fallback)
            if not _prev_segments:
                import re as _re_resume

                _row_matches = _re_resume.findall(
                    r"Row\s+\d+[-–~]\d+", state.current_knowledge or ""
                )
                _prev_segments = list(set(_row_matches))[:5]

            _segments_str = (
                "\n".join(f"  - {s}" for s in _prev_segments[:5])
                if _prev_segments
                else "  - 無已知異常區段"
            )

            # ── 構建排除指令 ──
            _exclusion_directive = (
                "\n\n========== [排除記憶: 續查模式] ==========\n"
                f"上次分析已完成 {state.step_count - 1} 個 Turn。\n"
                f"已使用工具: {_prev_tools_str}\n"
                f"已分析參數: {_prev_targets_str}\n"
                f"已確認發現:\n{_prev_findings_str}\n"
                f"\n[已發現的異常區段]\n{_segments_str}\n"
                "\n[續查指令]\n"
                "1. 禁止重複使用相同參數+工具組合\n"
                "2. 請探索尚未涉及的參數和分析角度\n"
                "3. [MANDATORY] 續查分析必須至少包含一個「區段分析」場景 (segment 類型)，\n"
                "   使用上方已發現的異常區段進行深入調查（例如 compare_data_segments、classify_anomaly_type）\n"
                "4. 如果所有合理線索都已探索完畢, 直接 FINISH\n"
                "========================================\n"
            )

            # ── 重置場景, 讓 Strategist 透過 Path A 生成新場景 ──
            extra_turns = 3
            new_max = extra_turns  # 重新計算 (不從舊 step_count 開始)
            state = state.update(
                role_name="Resume",
                max_steps=new_max + 1,
                step_count=1,  # 回到 Turn 1, 走 Path A 用 LLM 生成新場景
                scene_queue=[],  # 清空場景, 讓 Strategist 重新生成
                current_scene_index=-1,
                original_query=start_event.query,  # 更新為新查詢
                current_knowledge=state.current_knowledge + _exclusion_directive,
                has_domain_intent=True,  # 避免重新分類意圖
                # 保留 used_tools_history 和 failed_experiments 以供去重
                failed_experiments=_prev_failed
                + [
                    f"{t}::{','.join(sorted(_prev_targets))}"
                    for t in _prev_tools
                    if _prev_targets
                ],
            )

            # [RESUME DEDUP] 記錄已分析參數, 在場景生成後代碼層級過濾
            self._resume_excluded_targets = _prev_targets.copy()

            mode_label = "深度分析" if is_deep else "快速回應"
            has_specific_targets = False  # 允許 Turn 1 重新掃描 (用新角度)
            is_optimization = False  # Resume always uses Strategist

            yield ProgressEvent(
                msg=f"續查模式: 繼承上次分析 ({len(_prev_targets)} 個已分析參數), "
                f"將探索新線索 (額外 {extra_turns} Turn)..."
            )
            self.logger.info(
                f"[RESUME-EXCLUSION] prev_tools={_prev_tools_str}, "
                f"prev_targets={_prev_targets_str}, "
                f"findings_count={len(_prev_findings)}"
            )
        elif scene_continue and _key in self._last_states:
            # [SCENE CONTINUE] 場景選擇後繼續: 不重置場景, 直接使用 run_scene_select 設定的 state
            cached = self._last_states[_key]
            state = cached["state"]
            is_deep = cached.get("is_deep", False)
            summary_data = cached.get("summary_data", summary_data)

            # [FIX] 重置 step_count: 場景分析從 Turn 1 重新計數
            # 避免繼承上次快速分析的 step_count 導致 Turn 跳號
            state = state.update(role_name="SceneContinue_Reset", step_count=1)

            # 動態設定 max_turns: 每個 ACTIVE 場景給 2 Turn
            _active_count = sum(
                1 for s in (state.scene_queue or []) if s.status == "ACTIVE"
            )
            _pending_count = sum(
                1 for s in (state.scene_queue or []) if s.status == "PENDING"
            )
            _total_scenes = _active_count + _pending_count
            max_turns = 1 + max(_total_scenes * 2, 4)

            mode_label = "深度分析" if is_deep else "快速回應"
            has_specific_targets = True  # 場景已有 targets
            is_optimization = False

            # 注入場景清單到 knowledge
            _scene_lines = []
            for s in state.scene_queue or []:
                _status = (
                    "→ 當前"
                    if s.status == "ACTIVE"
                    else ("  完成" if s.status == "DONE" else "  待辦")
                )
                _scene_lines.append(
                    f"  [{_status}] {s.scene_id}: {s.label} "
                    f"(targets: {', '.join(s.targets[:3]) if s.targets else '全域'})"
                )
            _scene_text = "\n".join(_scene_lines)
            _scene_knowledge = (
                f"\n\n[場景清單] 使用者已選擇執行 {_total_scenes} 個場景:\n"
                f"{_scene_text}\n\n"
                "[場景驅動規則] [MOST CRITICAL]\n"
                "  1. 一次只分析一個場景, 完成後才切換到下一個\n"
                "  2. 分析到位後, directive 末尾加: [場景完成] S1: 主要發現摘要\n"
                "  3. 分析中發現新線索 → 記入 [潛在線索], 不中斷當前場景\n"
                "  4. Turn 限制內未完成的場景 → 列為潛在線索, 納入結論\n"
            )
            state = state.update(
                role_name="SceneContinue",
                current_knowledge=(state.current_knowledge or "") + _scene_knowledge,
                has_domain_intent=True,
                max_steps=max_turns + 1,
            )

            yield ProgressEvent(
                msg=f"場景執行開始: {_active_count} 個活動場景, "
                f"{_pending_count} 個待執行 (最多 {max_turns - state.step_count + 1} Turn)"
            )
            print(
                f"[SCENE_CONTINUE] step_count={state.step_count}, max_turns={max_turns}, "
                f"active={_active_count}, pending={_pending_count}, "
                f"scene_queue={[f'{s.scene_id}:{s.status}' for s in (state.scene_queue or [])]}"
            )
        else:
            # [NORMAL PATH] Fresh analysis initialization
            # 1. Initialize State (Dashboard)
            # [Fix] Parse summary_data correctly (AnalysisService format)
            n_rows = summary_data.get(
                "total_rows", summary_data.get("n_rows", "Unknown")
            )
            columns = summary_data.get("parameters", summary_data.get("columns", []))

            # Construct schema from numerical_columns if dtypes unavailable
            numerical_cols = set(summary_data.get("numerical_columns", []))
            data_schema = {}
            for col in columns:
                data_schema[col] = "float" if col in numerical_cols else "object"

            data_summary_str = f"Rows: {n_rows}, Columns: {len(columns)}"
            if "quality_stats" in summary_data:
                q = summary_data["quality_stats"]
                data_summary_str += f", Null Cols: {q.get('null_column_count')}, Sparse: {q.get('sparse_column_count')}"

            # [NEW] Mode-based configuration
            analysis_mode = getattr(start_event, "mode", "quick") or "quick"
            is_deep = analysis_mode in ("deep", "full")
            if is_deep:
                max_turns = self.DEEP_MAX_STEPS
                mode_label = "深度分析"
            else:
                max_turns = self.QUICK_MAX_STEPS
                mode_label = "快速回應"

            # Detect if user specified targets (suspect_pool)
            suspect_pool = getattr(start_event, "suspect_pool", []) or []

            # --- [NEW] Query Pre-Processing ---
            import re
            import json as _json

            query = start_event.query or ""

            # 1. Resolve positional references (最後一個欄位, etc.) -- deterministic fallback
            if not suspect_pool and columns:
                positional_patterns = [
                    (r"最後\s*(?:一個|1個)?(?:欄位|參數|column|變數|變量)", -1),
                    (r"倒數第?\s*(?:一個|1個)?(?:欄位|參數|column|變數|變量)", -1),
                    (r"第\s*(?:一個|1個)?(?:欄位|參數|column|變數|變量)", 0),
                    (
                        r"倒數第\s*(\d+)\s*(?:個)?(?:欄位|參數|column|變數|變量)",
                        "neg_idx",
                    ),
                    (r"第\s*(\d+)\s*(?:個)?(?:欄位|參數|column|變數|變量)", "pos_idx"),
                ]
                for pattern, idx_type in positional_patterns:
                    m = re.search(pattern, query)
                    if m:
                        if idx_type == "neg_idx":
                            idx = -int(m.group(1))
                        elif idx_type == "pos_idx":
                            idx = int(m.group(1)) - 1  # 0-indexed
                        else:
                            idx = idx_type
                        try:
                            resolved_col = columns[idx]
                            suspect_pool = [resolved_col]
                            self.logger.info(
                                f"[QueryPreProcess] Resolved '{m.group()}' -> '{resolved_col}'"
                            )
                        except IndexError:
                            pass
                        break

            # 2. LLM-based intent classification (scalable, handles any phrasing)
            analysis_type = "anomaly_detection"  # default
            llm_target = None
            specified_tool = None  # [PATH D] 用戶指定的工具
            llm_goal = ""

            # [QUICK_SCAN 短路] 前綴觸發快速掃描, 跳過 LLM 意圖分類
            _QUICK_SCAN_PREFIX = "[QUICK_SCAN]"
            _is_quick_scan = start_event.query.strip().startswith(_QUICK_SCAN_PREFIX)

            # [SCENE_CONTINUE 短路] 場景選擇後直接走分析, 不做意圖分類
            # 避免場景標題中的「趨勢」被誤判為 visualization
            _skip_intent = scene_continue or _is_quick_scan
            if scene_continue:
                self.logger.info(
                    "[IntentClassifier] SKIPPED (scene_continue=True), "
                    "forced analysis_type=anomaly_detection"
                )
                yield ProgressEvent(msg="場景分析啟動中...")
                llm_goal = "場景分析"
            elif _is_quick_scan:
                self.logger.info(
                    "[IntentClassifier] SKIPPED ([QUICK_SCAN] prefix), "
                    "forced analysis_type=anomaly_detection"
                )
                yield ProgressEvent(msg="快速掃描模式啟動...")
                llm_goal = "四合一快速掃描"

            if not _skip_intent:
                try:
                    # Build a short column hint (first 5 + last 5 to keep prompt small)
                    col_hint = (
                        columns[:5]
                        + (["..."] if len(columns) > 10 else [])
                        + columns[-5:]
                    )
                    col_hint_str = ", ".join(col_hint)

                    # [PATH D] 構建工具名稱提示 (取前 15 個常用工具)
                    from backend.services.analysis.tools.registry import TOOL_REGISTRY

                    _tool_names_hint = ", ".join(list(TOOL_REGISTRY.keys())[:15])

                    classify_prompt = (
                        "你是工業數據分析系統的意圖分類器。根據用戶的問題,回傳一個 JSON:\n"
                        '{"type": "...", "target": "...", "goal": "...", "specified_tool": "..."}\n\n'
                        "type 必須是以下之一:\n"
                        "- optimization: 用戶想調整/降低/提高某個指標 (例: 如何降低不良率? 怎麼讓水分更均勻?)\n"
                        "- anomaly_detection: 用戶想找異常/診斷問題 (例: 哪些參數異常? 為什麼良率下降?)\n"
                        "- comparison: 用戶想比較不同區段/條件 (例: 前100筆和後100筆有什麼差異?)\n"
                        "- visualization: 用戶只想看圖/趨勢 (例: 畫出溫度的趨勢圖)\n\n"
                        "target: 用戶關注的目標欄位名稱 (從可用欄位中選擇最接近的)。\n"
                        '  - 若有多個目標 (如同時優化兩個欄位), 用逗號分隔: "col_a,col_b"\n'
                        "  - 若用戶說「最後兩個欄位」或類似語句,請從欄位清單中取最後兩個\n"
                        "  - 若無法確定則為 null。\n"
                        "goal: 用戶想達成的目標 (例: '降低', '提高', '穩定', '找出原因', '同時優化')。\n"
                        "specified_tool: 如果用戶明確提到要使用的分析工具名稱,填入工具名。\n"
                        "  - 只有用戶明確提到工具名時才填寫,否則為 null。\n"
                        f"  - 可用工具名: {_tool_names_hint}\n\n"
                        f"可用欄位 (部分): [{col_hint_str}]\n"
                        f"用戶問題: {query}\n\n"
                        "回傳 JSON (不要回傳其他內容):"
                    )
                    resp = await self.llm.acomplete(classify_prompt)
                    resp_text = str(resp.text).strip()

                    # Parse JSON from response (handle markdown code blocks)
                    if "```" in resp_text:
                        resp_text = resp_text.split("```")[1]
                        if resp_text.startswith("json"):
                            resp_text = resp_text[4:]
                        resp_text = resp_text.strip()

                    intent_result = _json.loads(resp_text)
                    analysis_type = intent_result.get("type", "anomaly_detection")
                    llm_target = intent_result.get("target")
                    llm_goal = intent_result.get("goal", "")

                    # [PATH D] 提取 LLM 識別的 specified_tool
                    _llm_tool = intent_result.get("specified_tool")
                    if _llm_tool and _llm_tool in TOOL_REGISTRY:
                        specified_tool = _llm_tool

                    # Validate analysis_type
                    if analysis_type not in (
                        "optimization",
                        "anomaly_detection",
                        "comparison",
                        "visualization",
                    ):
                        analysis_type = "anomaly_detection"

                    # If LLM found a target and we don't have one yet, try to match it
                    if llm_target and not suspect_pool and columns:
                        # Handle multi-target: LLM may return "col_a,col_b"
                        raw_targets = [
                            t.strip() for t in llm_target.split(",") if t.strip()
                        ]
                        resolved = []
                        for rt in raw_targets:
                            if rt in columns:
                                resolved.append(rt)
                            else:
                                matches = [
                                    c for c in columns if rt.lower() in c.lower()
                                ]
                                if matches:
                                    resolved.append(matches[0])
                        if resolved:
                            suspect_pool = resolved

                    self.logger.info(
                        f"[IntentClassifier] type={analysis_type}, target={llm_target}, "
                        f"goal={llm_goal}, resolved_pool={suspect_pool}, "
                        f"specified_tool={specified_tool}"
                    )

                    # 發送前端事件: 意圖分類結果
                    _type_labels = {
                        "anomaly_detection": "異常偵測",
                        "optimization": "參數優化",
                        "comparison": "區段比較",
                        "visualization": "圖表視覺化",
                    }
                    _type_label = _type_labels.get(analysis_type, analysis_type)
                    _target_str = (
                        f", 目標: {', '.join(suspect_pool)}" if suspect_pool else ""
                    )
                    _goal_str = f", 目的: {llm_goal}" if llm_goal else ""
                    yield ProgressEvent(
                        msg=f"意圖分類: {_type_label}{_target_str}{_goal_str}"
                    )
                    yield MonologueEvent(
                        monologue=(
                            f"【意圖分析】\n"
                            f"分析類型: {_type_label}\n"
                            f"目標參數: {', '.join(suspect_pool) if suspect_pool else '未指定 (將自動偵測)'}\n"
                            f"分析目的: {llm_goal or '未指定'}\n"
                            f"指定工具: {specified_tool or '無'}"
                        ),
                        tool_name="IntentClassifier",
                        tool_params={
                            "type": analysis_type,
                            "target": llm_target,
                            "goal": llm_goal,
                        },
                        query=start_event.query,
                        file_id=start_event.file_id,
                        session_id=session_id,
                        history="",
                    )
                except Exception as e:
                    self.logger.warning(
                        f"[IntentClassifier] LLM classification failed: {e}, using default"
                    )
                    analysis_type = "anomaly_detection"

            # [PATH D] Regex fallback: 直接在 query 中搜索已知工具名
            if not specified_tool:
                from backend.services.analysis.tools.registry import (
                    TOOL_REGISTRY as _TR,
                )

                for _tn in _TR.keys():
                    if _tn in query:
                        specified_tool = _tn
                        self.logger.info(
                            f"[IntentClassifier] Regex fallback detected tool: {_tn}"
                        )
                        break

            is_optimization = analysis_type == "optimization"
            has_specific_targets = len(suspect_pool) > 0

            # [動態判定] 是否有領域意圖 (路徑 S: 跳過 Turn 1 盲掃)
            # 方案 C: LLM IntentClassifier 結果 + 欄位名交叉比對
            _has_domain_intent = False
            if analysis_type == "anomaly_detection" and not has_specific_targets:
                _q = start_event.query

                # [快速通道] 前綴 [QUICK_SCAN] → 直接走 Path C (四合一盲掃)
                _is_quick_scan = _q.strip().startswith(_QUICK_SCAN_PREFIX)

                if not _is_quick_scan:
                    # --- 來源 A: LLM IntentClassifier 結果 ---
                    # 如果 LLM 識別出 goal (如「找出原因」「降低」「穩定」),
                    # 代表有明確分析意圖
                    _has_llm_intent = bool(llm_goal) and llm_goal != "null"

                    # --- 來源 B: 欄位中文名交叉比對 ---
                    # 取所有中文欄位名, 檢查 query 是否提到任何一個
                    _term_map = summary_data.get("mappings", {})
                    _cn_names = set(v for v in _term_map.values() if v and len(v) >= 2)
                    # 也用欄位名的子串比對 (如「含水量」→ 用戶說「水份」)
                    _has_col_match = False
                    _matched_col = ""
                    _q_lower = _q.lower()
                    for cn in _cn_names:
                        # 雙向比對: query 包含欄位名 OR 欄位名包含 query 的關鍵詞
                        if cn in _q:
                            _has_col_match = True
                            _matched_col = cn
                            break
                        # 欄位名中的每 2 字子串是否出現在 query 中
                        for i in range(len(cn) - 1):
                            sub = cn[i : i + 2]
                            if sub in _q:
                                _has_col_match = True
                                _matched_col = f"{cn}(via '{sub}')"
                                break
                        if _has_col_match:
                            break

                    if _has_llm_intent or _has_col_match:
                        _has_domain_intent = True
                        _reason = []
                        if _has_llm_intent:
                            _reason.append(f"LLM goal='{llm_goal}'")
                        if _has_col_match:
                            _reason.append(f"欄位比對='{_matched_col}'")
                        self.logger.info(
                            f"[DomainIntent] 動態偵測: {', '.join(_reason)}"
                        )

            if _has_domain_intent:
                self.logger.info(
                    f"[IntentClassifier] 偵測到領域意圖, Turn 1 將跳過盲掃"
                )

            # 載入資料描述 (如果用戶有設定)
            _data_desc = ""
            try:
                from pathlib import Path as _Path
                import json as _json_desc

                _desc_file = (
                    _Path("data") / "descriptions" / f"{start_event.file_id}.json"
                )
                if _desc_file.exists():
                    _desc_data = _json_desc.loads(
                        _desc_file.read_text(encoding="utf-8")
                    )
                    _data_desc = _desc_data.get("description", "")
            except Exception:
                pass

            state = AnalysisState(
                session_id=session_id,
                file_id=start_event.file_id,
                original_query=start_event.query,
                current_context=AnalysisContext(
                    targets=suspect_pool, feature_pool=summary_data.get("columns", [])
                ),
                data_summary=data_summary_str,
                data_schema=data_schema,
                term_mappings=summary_data.get("mappings", {}),
                max_steps=max_turns,
                current_knowledge=build_initial_knowledge("Analysis started."),
                has_domain_intent=_has_domain_intent,
                is_quick_scan=_is_quick_scan,  # [PATH C 快速通道]
                specified_tool=specified_tool,  # [PATH D]
                analysis_type=analysis_type,  # [PATH B 優化]
                data_description=_data_desc,
            )

            # Inject mode context into state so Strategist knows the depth expectation
            _mode_text = f"\n[模式: {mode_label}, 最多 {max_turns} Turn] " + (
                "有足夠的 Turn 進行完整調查。請充分探索每個發現,進行相關性驗證、因果推理和殘差分析。"
                if is_deep
                else f"請在 {max_turns} 個 Turn 內完成分析。優先做全域掃描,快速定位問題。"
            )
            state.current_knowledge = append_routing(
                state.current_knowledge, _mode_text
            )

            # --- Inject Analysis Type Context (from LLM classification) ---
            is_multi_target = analysis_type == "optimization" and len(suspect_pool) > 1

            if analysis_type == "optimization" and suspect_pool:
                if is_multi_target:
                    # Multi-objective optimization path
                    target_names = ", ".join(suspect_pool)
                    targets_csv = ",".join(suspect_pool)
                    state.current_knowledge = append_routing(
                        state.current_knowledge,
                        f"\n\n[分析類型: 多目標優化] 用戶想同時優化: {target_names}"
                        f"\n[CRITICAL] 這是多目標問題! 需要先分析目標間的 Synergy/Trade-off 關係!"
                        f"\n[策略] Turn 1: 多目標分析+側寫"
                        f"\n  1. multi_objective_analysis(targets='{targets_csv}') - Synergy/Trade-off 分類"
                        f"\n  2. get_top_correlations 對每個目標 - 相關參數"
                        f"\n  3. performance_segmentation 對主要目標 - 好壞批次"
                        f"\n[策略] Turn 2: 邊際效應+因果"
                        f"\n  4. partial_dependence - 各參數對各目標的影響曲線"
                        f"\n  5. interaction_scatter - 兩關鍵參數的交互效應"
                        f"\n[策略] Turn 3: 多劇本建議"
                        f"\n  6. generate_operating_window - SOP"
                        f"\n[禁止] 不要做無目標的全域異常掃描!",
                    )
                else:
                    # Single-target optimization path
                    target_name = suspect_pool[0]
                    state.current_knowledge = append_routing(
                        state.current_knowledge,
                        f"\n\n[分析類型: 優化推薦] 用戶目標: 調整 '{target_name}' 的數值。"
                        f"\n[CRITICAL] 這不是異常檢測! 用戶想知道: 哪些參數影響 '{target_name}'? 怎麼調整能達到目標?"
                        f"\n[策略] Turn 1: 側寫+分割"
                        f"\n  1. get_top_correlations(target='{target_name}') - 找出相關參數"
                        f"\n  2. analyze_feature_importance(target='{target_name}') - 驅動因子"
                        f"\n  3. performance_segmentation(target='{target_name}') - 好壞批次分割"
                        f"\n[策略] Turn 2: 因果+邊際效應"
                        f"\n  4. partial_dependence(target='{target_name}') - 非線性影響曲線"
                        f"\n  5. cross_correlation_lag / causal_relationship_analysis - 因果驗證"
                        f"\n[策略] Turn 3: 操作建議"
                        f"\n  6. interaction_scatter - Sweet Spot 識別"
                        f"\n  7. generate_operating_window(target='{target_name}') - SOP 建議表"
                        f"\n[禁止] 不要做無目標的全域異常掃描!",
                    )
            elif analysis_type == "optimization" and not suspect_pool:
                state.current_knowledge = append_routing(
                    state.current_knowledge,
                    "\n\n[分析類型: 優化推薦] 用戶想調整某個變數,但未能自動解析目標欄位。"
                    "\n請從用戶的問題中推斷目標變數,並使用 get_top_correlations + analyze_feature_importance 分析。",
                )
            elif analysis_type == "comparison":
                state.current_knowledge = append_routing(
                    state.current_knowledge,
                    "\n\n[分析類型: 區段比較] 用戶想比較不同數據區段。"
                    "\n使用 compare_data_segments 和 distribution_shift_analysis 進行比較分析。",
                )
            elif analysis_type == "visualization":
                state.current_knowledge = append_routing(
                    state.current_knowledge,
                    "\n\n[分析類型: 視覺化] 用戶只想看圖表。"
                    "\n優先使用 draw_trend / get_time_series_data,快速產出圖表後結案。",
                )

            # --- Intent Decomposition (for Coverage Tracking) ---
            # visualization 類型已有明確目標, 不需要 LLM 分解
            if analysis_type == "visualization":
                _viz_intent = f"意圖1: {start_event.query}"
                state = state.update(
                    role_name="IntentDecomposition",
                    query_intents=[_viz_intent],
                )
                self.logger.info(
                    f"[IntentDecomposition] Visualization shortcut: {[_viz_intent]}"
                )
            elif _is_quick_scan:
                # [QUICK_SCAN] 跳過 LLM 意圖分解, 使用固定意圖
                _qs_intent = (
                    "意圖1: 四合一快速掃描 (異常偵測 + T2分析 + 相關性 + 異常區段)"
                )
                state = state.update(
                    role_name="IntentDecomposition",
                    query_intents=[_qs_intent],
                )
                self.logger.info(
                    f"[IntentDecomposition] QuickScan shortcut: {[_qs_intent]}"
                )
            else:
                try:
                    import json as _json, re as _re

                    # 組合資料場景上下文
                    _data_desc = getattr(state, "data_description", "") or ""
                    _data_summ = getattr(state, "data_summary", "") or ""
                    _term_map = getattr(state, "term_mappings", {}) or {}

                    _context_parts = []
                    if _data_desc:
                        _context_parts.append(f"資料描述: {_data_desc}")
                    if _data_summ:
                        _context_parts.append(f"資料概要: {_data_summ}")
                    if _term_map:
                        # 傳全部中文名 (不傳代碼, 節省空間)
                        _all_cn = list(set(v for v in _term_map.values() if v))
                        _col_hint = ", ".join(_all_cn)
                        _context_parts.append(
                            f"資料包含的參數 ({len(_all_cn)} 個): {_col_hint}"
                        )

                    _data_context = "\n".join(_context_parts) if _context_parts else ""

                    _intent_prompt = (
                        "你是工業數據分析的意圖拆解器。\n"
                        "用戶正在對一份工業製程數據進行分析, 請將以下問題拆解為 2-6 個"
                        "與「數據分析」相關的獨立子問題。\n\n"
                        "注意:\n"
                        "- 這是數據分析場景, 不是通用知識問答\n"
                        "- 子問題應該是「可以用數據回答的」分析任務\n"
                        "- 例如「溫度跟壓力的關係」→ 拆解為:\n"
                        '  ["意圖1: 找出所有溫度相關參數的數值趨勢", '
                        '"意圖2: 找出所有壓力相關參數的數值趨勢", '
                        '"意圖3: 分析溫度參數與壓力參數之間的相關性"]\n\n'
                    )
                    if _data_context:
                        _intent_prompt += f"[資料場景]\n{_data_context}\n\n"

                    _intent_prompt += (
                        f"用戶問題: {start_event.query}\n\n"
                        "只回傳 JSON 陣列, 每個元素是一個字串:\n"
                        '["意圖1: ...", "意圖2: ...", ...]\n'
                    )

                    _resp = await self.llm.acomplete(_intent_prompt)
                    _resp_text = str(_resp.text).strip()
                    if "```" in _resp_text:
                        _m = _re.search(r"\[.*\]", _resp_text, _re.DOTALL)
                        if _m:
                            _resp_text = _m.group(0)
                    _intents = _json.loads(_resp_text)
                    if isinstance(_intents, list) and _intents:
                        state = state.update(
                            role_name="IntentDecomposition",
                            query_intents=[str(i) for i in _intents[:6]],
                        )
                        self.logger.info(
                            f"[IntentDecomposition] {len(state.query_intents)} intents: "
                            f"{state.query_intents}"
                        )
                        # 發送前端事件: 意圖分解結果
                        _intents_str = "\n".join(
                            f"  {i + 1}. {intent}"
                            for i, intent in enumerate(state.query_intents)
                        )
                        yield ProgressEvent(
                            msg=f"問題分解為 {len(state.query_intents)} 個子分析任務"
                        )
                        yield MonologueEvent(
                            monologue=(
                                f"【問題分解】\n"
                                f"將用戶問題拆解為 {len(state.query_intents)} 個子分析任務:\n"
                                f"{_intents_str}"
                            ),
                            tool_name="IntentDecomposition",
                            tool_params={"count": len(state.query_intents)},
                            query=state.original_query,
                            file_id=state.file_id,
                            session_id=session_id,
                            history="",
                        )
                except Exception as e:
                    self.logger.warning(
                        f"[IntentDecomposition] Failed: {e}, will use fallback"
                    )

            yield ProgressEvent(
                msg=f"🚀 啟動 V2 批量分析引擎 (模式: {mode_label}, 最多 {max_turns} 個 Turn)..."
            )

        def _is_stopped():
            return (
                self.analysis_service
                and self.analysis_service.is_generation_stopped(session_id)
            )

        while True:
            # [STOP CHECK]
            if self.analysis_service and self.analysis_service.is_generation_stopped(
                session_id
            ):
                yield ProgressEvent(msg="🛑 收到停止信號。")
                break

            if state.step_count >= max_turns:
                yield MonologueEvent(
                    monologue="【達到最大步數】強制結案。",
                    tool_name="force_finish",
                    tool_params={},
                    query=state.original_query,
                    file_id=state.file_id,
                    session_id=session_id,
                    history="",
                )
                break

            self.logger.info(f"--- Turn {state.step_count} ---")

            # --- Phase 1: Strategist (統一入口, 所有 Turn 都經過) ---
            # 每個 Turn 都完整執行: Strategist → [Planner] → Executor → Synthesizer
            _scene_tag = ""
            if state.scene_queue and 0 <= state.current_scene_index < len(
                state.scene_queue
            ):
                _active = state.scene_queue[state.current_scene_index]
                _scene_tag = f" [{_active.scene_id}: {_active.label}]"
            yield ProgressEvent(
                msg=f"[Turn {state.step_count}]{_scene_tag} 策略思考中...",
                turn=state.step_count,
            )

            strat_in = RoleInput(state_machine=state)
            strat_out = await self.roles["strategist"].execute(strat_in)
            directive = strat_out.directive
            strat_decision = strat_out.decision
            strat_experiments = strat_out.experiments or []

            # --- [AutoTarget] 從 Strategist 消費自動抽取結果 ---
            # 僅處理 knowledge_addon / context / summary_injection
            # ProgressEvents + current_knowledge 組裝由 Synthesizer 負責
            _auto_target = (strat_out.structured_log or {}).get("auto_target_data")
            if _auto_target and not state.auto_target_raw:
                _k_addon = _auto_target.get("knowledge_addon", "")
                _ctx = _auto_target.get("context_update")
                _s_inj = _auto_target.get("summary_injection", "")

                _updates = {"auto_target_raw": _auto_target}
                if _k_addon:
                    _updates["current_knowledge"] = append_routing(
                        state.current_knowledge, _k_addon
                    )
                if _ctx:
                    _updates["current_context"] = _ctx
                if _s_inj:
                    _updates["current_knowledge"] = inject_to_section(
                        _updates.get("current_knowledge", state.current_knowledge),
                        "SUMMARY",
                        "自動目標",
                        _s_inj,
                        module="Strategist",
                    )
                state = state.update(role_name="AutoTarget", **_updates)

            # --- [SCENE] 處理場景切換 (Strategist 透過 structured_log 傳遞) ---
            _scene_updates = (strat_out.structured_log or {}).get("_scene_updates")
            _scene_switched = False  # [Direction B] 追蹤是否發生場景切換
            if _scene_updates:
                # [GUARD] 禁止切換尚未使用過 tool 的場景
                _prev_idx_guard = _scene_updates.get(
                    "_prev_scene_index", state.current_scene_index
                )
                _guard_reject = False
                if state.scene_queue and 0 <= _prev_idx_guard < len(state.scene_queue):
                    _prev_scene = state.scene_queue[_prev_idx_guard]
                    if (
                        _prev_scene.status in ("ACTIVE", "DONE")
                        and not _prev_scene.has_executed_tools
                    ):
                        _guard_reject = True
                        self.logger.warning(
                            f"[SceneGuard] 拒絕切換: {_prev_scene.scene_id} "
                            f"尚未執行任何分析工具，強制繼續分析"
                        )
                        yield ProgressEvent(
                            msg=f"[場景保護] {_prev_scene.scene_id} 尚未執行任何工具，繼續分析",
                            turn=state.step_count,
                        )
                        if _prev_scene.status == "DONE":
                            _prev_scene.status = "ACTIVE"
                        _scene_updates = None  # 丟棄切換請求

            if _scene_updates:
                new_queue = _scene_updates.get("scene_queue", state.scene_queue)
                new_idx = _scene_updates.get(
                    "current_scene_index", state.current_scene_index
                )

                _knowledge_addon = ""
                if not state.scene_queue and new_queue:
                    # [初始場景創建] 所有場景轉為 follow_up_items, 由用戶選擇
                    # Resume dedup 仍需執行
                    if self._resume_excluded_targets and new_queue:
                        _before = len(new_queue)
                        new_queue = [
                            s
                            for s in new_queue
                            if not s.targets
                            or not set(s.targets).issubset(
                                self._resume_excluded_targets
                            )
                        ]
                        _removed = _before - len(new_queue)
                        if _removed:
                            print(
                                f"[Resume DEDUP] 移除 {_removed} 個已分析場景, "
                                f"排除參數: {sorted(self._resume_excluded_targets)[:5]}"
                            )
                        self._resume_excluded_targets.clear()

                    # 轉為 follow_up_items (不放入 scene_queue)
                    _followup_items = [
                        {
                            "scene_id": s.scene_id,
                            "label": s.label,
                            "scene_type": s.scene_type,
                            "targets": s.targets,
                        }
                        for s in new_queue
                    ]
                    _existing_fu = getattr(state, "pending_follow_up_items", []) or []
                    state = state.update(
                        role_name="SceneToFollowUp",
                        pending_follow_up_items=_existing_fu + _followup_items,
                    )
                    scene_labels = [f"{s.scene_id}: {s.label}" for s in new_queue]
                    print(
                        f"[SceneToFollowUp] {len(new_queue)} 個場景轉為後續建議: "
                        + ", ".join(scene_labels)
                    )
                    yield ProgressEvent(
                        msg=f"[場景規劃] 生成 {len(new_queue)} 個分析建議",
                        turn=state.step_count,
                    )
                    # 不載入 scene_queue, 也不需 knowledge_addon
                    new_queue = state.scene_queue  # 保持空
                    new_idx = state.current_scene_index

                state = state.update(
                    role_name="SceneTransition",
                    scene_queue=new_queue,
                    current_scene_index=new_idx,
                    **(
                        {
                            "current_knowledge": append_routing(
                                state.current_knowledge, _knowledge_addon
                            )
                        }
                        if _knowledge_addon
                        else {}
                    ),
                )
                # Emit scene transition ProgressEvent
                _prev_idx = _scene_updates.get(
                    "_prev_scene_index", state.current_scene_index
                )
                if new_queue and new_idx != _prev_idx and new_idx < len(new_queue):
                    _new_scene = new_queue[new_idx]
                    _done_label = ""
                    if 0 <= _prev_idx < len(new_queue):
                        _done_label = f"{new_queue[_prev_idx].scene_id} 完成 → "
                    _cov = _scene_updates.get("coverage_pct", 0.0)
                    _cov_tag = f" [覆蓋率:{_cov:.0%}]" if _cov > 0 else ""
                    yield ProgressEvent(
                        msg=f"[場景切換] {_done_label}"
                        f"進入 {_new_scene.scene_id}: {_new_scene.label}"
                        f"{_cov_tag}",
                        turn=state.step_count,
                    )
                    _scene_switched = True  # 標記已發生真正的場景切換

                self.logger.info(
                    f"[Scene] Transition: index={state.current_scene_index}, "
                    f"queue={[s.scene_id + ':' + s.status for s in state.scene_queue]}"
                )

                # --- [AUTO CONCEPT EXPANSION] 場景切換時自動展開參數 ---
                if new_queue and 0 <= new_idx < len(new_queue):
                    _new_scene = new_queue[new_idx]
                    _need_expand = (
                        _new_scene.status == "ACTIVE"
                        and len(_new_scene.targets or []) < 5
                        and _new_scene.label
                    )
                    if _need_expand:
                        _strategist = self.roles.get("strategist")
                        _all_columns = summary_data.get("parameters", [])
                        _term_mappings = summary_data.get("mappings", {})
                        if _strategist and _all_columns:
                            try:
                                yield ProgressEvent(
                                    msg=f"[{_new_scene.scene_id}] 正在展開相關參數...",
                                    turn=state.step_count,
                                )
                                import asyncio as _asyncio_exp

                                _exp_progress_queue = _asyncio_exp.Queue()

                                _exp_targets, _ = await _strategist._expand_concepts(
                                    query=state.original_query,
                                    all_columns=_all_columns,
                                    term_mappings=_term_mappings,
                                    existing_targets=_new_scene.targets or [],
                                    intents=[_new_scene.label],
                                    progress_callback=_exp_progress_queue.put_nowait,
                                )

                                # 輸出進度到 AI 思考流程
                                while not _exp_progress_queue.empty():
                                    _pmsg = _exp_progress_queue.get_nowait()
                                    yield MonologueEvent(
                                        monologue=f"[概念展開] {_new_scene.scene_id} {_pmsg}",
                                        tool_name="concept_expand",
                                        tool_params={},
                                        query=state.original_query or "",
                                        file_id=state.file_id,
                                        session_id=session_id,
                                        history="",
                                    )

                                if _exp_targets:
                                    _merged = list(
                                        dict.fromkeys(
                                            (_new_scene.targets or []) + _exp_targets
                                        )
                                    )
                                    _new_scene.targets = _merged
                                    yield ProgressEvent(
                                        msg=f"[{_new_scene.scene_id}] 從 {len(_all_columns)} 個欄位"
                                        f"篩選出 {len(_merged)} 個相關參數",
                                        turn=state.step_count,
                                    )
                                    print(
                                        f"[AutoExpand] {_new_scene.scene_id} "
                                        f"展開完成: {len(_exp_targets)} 新參數, "
                                        f"總計 {len(_merged)}"
                                    )
                            except Exception as e:
                                print(
                                    f"[AutoExpand] {_new_scene.scene_id} "
                                    f"展開失敗: {e}, 保留原始 targets"
                                )
                    else:
                        # targets 已充足, 不需概念展開, 但通知用戶參數數量
                        _t_count = len(_new_scene.targets or [])
                        if _t_count > 0:
                            yield ProgressEvent(
                                msg=f"[{_new_scene.scene_id}] 鎖定 {_t_count} 個"
                                f"參數進行分析: {_new_scene.label}",
                                turn=state.step_count,
                            )

                # [Direction B] 場景切換後, 跳過本 Turn 的 Planner/Executor/Synthesizer
                # 回到循環頂部讓 Strategist 為新場景重新規劃策略
                if _scene_switched:
                    self.logger.info(
                        "[SceneSwitch] 場景已切換, 跳過本 Turn 分析管線, "
                        "回到循環頂部重新規劃"
                    )
                    continue

            # --- Monologue 輸出 ---
            yield MonologueEvent(
                monologue=(
                    f"[Turn {state.step_count}] 【策略指揮】\n"
                    f"{strat_out.reasoning}\n\n"
                    f"決定: {strat_out.decision}\n"
                    f"指令: {strat_out.directive}"
                ),
                tool_name="Strategist",
                tool_params={
                    "decision": strat_out.decision,
                    "directive": strat_out.directive,
                },
                query=state.original_query,
                file_id=state.file_id,
                session_id=session_id,
                history="",
            )

            # --- 收集 follow_up_items 和 turn1_type → 存到 state 正式欄位 ---
            _follow_up = (strat_out.structured_log or {}).get("follow_up_items", [])
            _turn1_type = (strat_out.structured_log or {}).get("turn1_type", "")
            _state_updates = {}
            if _follow_up:
                _state_updates["pending_follow_up_items"] = _follow_up
            if _turn1_type and not getattr(state, "turn1_path_type", ""):
                _state_updates["turn1_path_type"] = _turn1_type

            # --- [PATH S] 所有場景作為 follow_up_items (用戶自行選擇) ---
            _raw_scene_queue = (strat_out.structured_log or {}).get("scene_queue", [])
            if _raw_scene_queue and not getattr(state, "scene_queue", []):
                _all_scene_items = []
                for i, sq in enumerate(_raw_scene_queue):
                    _all_scene_items.append(
                        {
                            "scene_id": sq.get("scene_id", f"S{i + 1}"),
                            "label": sq.get("label", f"場景 {i + 1}"),
                            "scene_type": sq.get("scene_type", "parameter"),
                            "targets": sq.get("targets", []),
                        }
                    )
                if _all_scene_items:
                    _existing_followup = _state_updates.get(
                        "pending_follow_up_items", []
                    )
                    _state_updates["pending_follow_up_items"] = (
                        _existing_followup + _all_scene_items
                    )
                    _scene_labels = [
                        f"{s['scene_id']}: {s['label']}" for s in _all_scene_items
                    ]
                    self.logger.info(
                        f"[Path S] {len(_all_scene_items)} 個場景作為後續建議: "
                        + ", ".join(_scene_labels)
                    )
                    _scene_list_str = "\n".join(
                        f"  {s['scene_id']}. [{s['scene_type']}] {s['label']}"
                        for s in _all_scene_items
                    )
                    yield ProgressEvent(
                        msg=f"場景規劃: 生成 {len(_all_scene_items)} 個分析建議",
                        turn=state.step_count,
                    )
                    yield MonologueEvent(
                        monologue=(
                            f"【場景規劃】\n"
                            f"根據分析結果, 規劃 {len(_all_scene_items)} 個可深入調查的方向:\n"
                            f"{_scene_list_str}\n\n"
                            f"請選擇您感興趣的場景進行深入分析"
                        ),
                        tool_name="ScenePlanner",
                        tool_params={"scene_count": len(_all_scene_items)},
                        query=state.original_query,
                        file_id=state.file_id,
                        session_id=session_id,
                        history="",
                    )

            if _state_updates:
                state = state.update(
                    role_name="Orchestrator_FollowUp", **_state_updates
                )

            # --- FINISH 處理: 直接結束 → Humanizer ---
            if strat_decision == "FINISH":
                # AutoTarget 數據已在 Turn 1 的 Strategist 輸出後
                # 寫入 current_knowledge，不再需要額外注入 history
                self.logger.info("[Orchestrator] FINISH — break to Humanizer")
                break

            # [STOP CHECK] Phase 2 前
            if _is_stopped():
                yield ProgressEvent(msg="收到停止信號。")
                break

            # --- Phase 2: Planner (The Architect) ---
            if strat_experiments:
                # Strategist 直接回傳 experiments (Turn 1 硬編碼), 跳過 Planner
                experiments = strat_experiments
                yield MonologueEvent(
                    monologue=(
                        f"[Turn {state.step_count}] 【硬編碼掃描】Strategist 直接指定 {len(experiments)} 個實驗, 跳過 Planner"
                    ),
                    tool_name="Planner",
                    tool_params={"skipped": True, "count": len(experiments)},
                    query=state.original_query,
                    file_id=state.file_id,
                    session_id=session_id,
                    history="",
                )
            else:
                # 一般路徑: Planner 根據 Strategist directive 規劃實驗
                yield ProgressEvent(msg="正在規劃實驗清單...", turn=state.step_count)

                plan_in = RoleInput(state_machine=state, directive=directive)
                plan_out = await self.roles["planner"].execute(plan_in)

                experiments = plan_out.experiments

                # [Fix 5] Planner returned FINISH
                # 但不能讓 Planner 越權: 如果 scene_queue 還有 PENDING/ACTIVE 場景,
                # 忽略 Planner 的 FINISH, 改為空實驗回退 (讓 Strategist 下個 Turn 重新指派)
                if plan_out.decision == "FINISH" and not experiments:
                    _has_pending = any(
                        s.status in ("PENDING", "ACTIVE")
                        for s in getattr(state, "scene_queue", [])
                    )
                    if _has_pending:
                        # 場景未完成, 不允許 Planner 結案
                        _pending_ids = [
                            s.scene_id
                            for s in state.scene_queue
                            if s.status in ("PENDING", "ACTIVE")
                        ]
                        yield ProgressEvent(
                            msg=f"Planner 建議結案, 但仍有待辦場景 {_pending_ids}, 繼續分析。",
                            turn=state.step_count,
                        )
                        self.logger.warning(
                            f"[Planner FINISH overridden] "
                            f"Pending scenes: {_pending_ids}"
                        )
                        # 不 break, 走下面 empty plan 回退邏輯
                    else:
                        yield ProgressEvent(
                            msg="Planner 判斷已無需繼續分析，準備結案。",
                            turn=state.step_count,
                        )
                        break

                if not experiments:
                    # [Fix 6] Track consecutive empty plans
                    empty_plan_count = getattr(self, "_empty_plan_count", 0) + 1
                    self._empty_plan_count = empty_plan_count
                    _has_pending_scenes = any(
                        s.status in ("PENDING", "ACTIVE")
                        for s in getattr(state, "scene_queue", [])
                    )
                    # 有待辦場景時門檻提高到 3 次, 給 Strategist 更多重試機會
                    _threshold = 3 if _has_pending_scenes else 2
                    if empty_plan_count >= _threshold:
                        yield ProgressEvent(
                            msg="連續多次無法規劃實驗，結束分析。",
                            turn=state.step_count,
                        )
                        break
                    yield MonologueEvent(
                        monologue=f"[Turn {state.step_count}] 【規劃受阻】沒有可行的實驗方案，將回報給策略師。",
                        tool_name="Planner",
                        tool_params={},
                        query=state.original_query,
                        file_id=state.file_id,
                        session_id=session_id,
                        history="",
                    )
                    state.history.append(
                        StepResult(
                            role="Planner",
                            conclusion="Failed to generate experiments. Data might be insufficient.",
                            timestamp=0.0,
                        )
                    )
                    state.step_count += 1
                    continue
                else:
                    # Reset empty plan counter on successful planning
                    self._empty_plan_count = 0

                # 提取 Planner 的方法論思考 (Step 1-3)
                _planner_thought = ""
                if plan_out.structured_log:
                    _planner_thought = plan_out.structured_log.get("thought", "")

                exp_list_str = "\n".join(
                    [
                        f"- {exp.technique} on {exp.target_columns}"
                        for exp in experiments
                    ]
                )

                _step_prefix = f"[Turn {state.step_count}] "
                _monologue_parts = []
                if _planner_thought:
                    _monologue_parts.append(
                        f"{_step_prefix}【方法論思考】\n{_planner_thought}"
                    )
                _monologue_parts.append(f"【實驗規劃】\n{plan_out.reasoning}")
                _monologue_parts.append(f"\n計畫執行:\n{exp_list_str}")

                yield MonologueEvent(
                    monologue="\n\n".join(_monologue_parts),
                    tool_name="Planner",
                    tool_params={"count": len(experiments)},
                    query=state.original_query,
                    file_id=state.file_id,
                    session_id=session_id,
                    history="",
                )

                # [NEW] Surface missing_capabilities to frontend
                missing_caps_raw = (plan_out.structured_log or {}).get(
                    "missing_capabilities", ""
                )
                if missing_caps_raw:
                    caps_lines = [
                        c.strip() for c in missing_caps_raw.split("\n") if c.strip()
                    ]
                    caps_str = "\n".join([f"  - {cap}" for cap in caps_lines])
                    yield ProgressEvent(
                        msg=f"[系統建議] Planner 認為需要但尚未擁有的能力:\n{caps_str}",
                        turn=state.step_count,
                    )

            # --- Phase 3: Executor (The Builder) ---
            # Parallel Execution
            yield ProgressEvent(
                msg=f"批量執行 {len(experiments)} 個實驗中 (Async)...",
                turn=state.step_count,
            )

            exec_in = RoleInput(state_machine=state, experiments=experiments)
            exec_out = await self.roles["executor"].execute(exec_in)
            evidences = exec_out.evidences

            # [SCENE TOOL TRACKING] 標記當前場景已執行過工具
            if state.scene_queue and 0 <= state.current_scene_index < len(
                state.scene_queue
            ):
                state.scene_queue[state.current_scene_index].has_executed_tools = True

            # Show progress for each evidence (with brief key metrics)
            for ev in evidences:
                status_icon = "✅" if ev.status == "SUCCESS" else "❌"
                # Extract brief summary from result
                brief = ev.observation[:80]
                if ev.status == "SUCCESS" and isinstance(ev.result, dict):
                    # Try to extract key Z-Score or anomaly info
                    top_params = ev.result.get("top_abnormal_parameters", {})
                    if top_params and isinstance(top_params, dict):
                        first_key = list(top_params.keys())[0]
                        first_z = (
                            top_params[first_key].get("stats", {}).get("max_z", 0)
                            if isinstance(top_params[first_key], dict)
                            else 0
                        )
                        brief = f"Top: {first_key} (Z={first_z:.1f})"
                    elif "anomaly_indices" in ev.result:
                        indices = ev.result["anomaly_indices"][:3]
                        brief = f"異常樣本: Row {indices}"
                    elif "top_correlations" in ev.result:
                        corrs = ev.result["top_correlations"]
                        if corrs and isinstance(corrs, list) and len(corrs) > 0:
                            top_c = corrs[0]
                            brief = f"最強關聯: {top_c.get('parameter', '?')} (r={top_c.get('correlation', 0):.2f})"
                yield ProgressEvent(
                    msg=f"{status_icon} [{ev.tool_name}] {brief}", turn=state.step_count
                )

                # [Multimodal] 把圖表送到前端顯示
                chart_b64 = getattr(ev, "chart_base64", None)
                if chart_b64:
                    yield MonologueEvent(
                        monologue=f"[EVIDENCE_IMG]{ev.tool_name}|{chart_b64}",
                        tool_name=ev.tool_name,
                        tool_params=ev.tool_params,
                        query=state.original_query,
                        file_id=state.file_id,
                        session_id=session_id,
                        history="",
                    )

            # --- Phase 4: Synthesizer (The Reviewer) ---
            # (Charts already generated by Executor in _run_experiment)
            # Review & Update Dashboard

            if state.is_quick_scan and state.step_count <= 1:
                # [QUICK_SCAN] 規則基 Synthesizer: 不調 LLM, 直接提取
                yield ProgressEvent(
                    msg=f"快速提取 {len(evidences)} 項證據摘要...",
                    turn=state.step_count,
                )
                syn_out = self._quick_scan_synthesize(state, experiments, evidences)
            else:
                yield ProgressEvent(
                    msg=f"綜合分析師正在驗收 {len(evidences)} 項證據...",
                    turn=state.step_count,
                )
                syn_in = RoleInput(
                    state_machine=state, experiments=experiments, evidences=evidences
                )
                syn_out = await self.roles["synthesizer"].execute(syn_in)
            report = syn_out.analysis_report

            # Broadcast Synthesis
            findings_str = "\n".join([f"- {f}" for f in report.key_findings])
            yield MonologueEvent(
                monologue=f"[Turn {state.step_count}] 【綜合驗收】\n邏輯: {report.synthesis_logic}\n\n關鍵發現:\n{findings_str}\n\n建議: {report.next_step_suggestion}",
                tool_name="Synthesizer",
                tool_params={},
                query=state.original_query,
                file_id=state.file_id,
                session_id=session_id,
                history="",
            )

            # Summary progress line for user visibility
            n_findings = len(report.key_findings)
            top_finding = report.key_findings[0][:60] if report.key_findings else "無"
            decision_label = (
                "繼續深入" if syn_out.decision == "CONTINUE" else "準備結案"
            )
            _sum_scene_tag = ""
            if state.scene_queue and 0 <= state.current_scene_index < len(
                state.scene_queue
            ):
                _s = state.scene_queue[state.current_scene_index]
                _sum_scene_tag = f" [{_s.scene_id}]"
            yield ProgressEvent(
                msg=f"📊 Turn {state.step_count}{_sum_scene_tag} 小結: {n_findings} 項發現 | 最關鍵: {top_finding} | {decision_label}",
                turn=state.step_count,
            )

            # [NEW] Surface Synthesizer's analysis gaps (post-execution perspective)
            analysis_gaps = (syn_out.structured_log or {}).get("analysis_gaps", [])
            if analysis_gaps and isinstance(analysis_gaps, list):
                gaps_str = "\n".join([f"  - {gap}" for gap in analysis_gaps])
                yield ProgressEvent(
                    msg=f"[分析缺口] Synthesizer 識別的工具缺口:\n{gaps_str}",
                    turn=state.step_count,
                )

            # --- [AutoTarget] 從 Synthesizer updates 輸出 ProgressEvents ---
            _syn_at = (syn_out.updates or {}).get("_auto_target_data")
            if _syn_at:
                _atg = _syn_at.get("anomaly_type_groups", [])
                _t2s = _syn_at.get("t2_summary", {})
                _ar = _syn_at.get("auto_row_ranges", [])
                _at = _syn_at.get("auto_targets", [])

                # --- 統一輸出: 將所有 AutoTarget 摘要合成一條 ProgressEvent ---
                _summary_parts = []

                # (1) 異常類型分組
                if _atg:
                    _type_lines = []
                    for _tg in _atg[:6]:
                        _tcn = _tg.get("type_cn", _tg.get("type", ""))
                        _pc = _tg.get("param_count", 0)
                        _params_list = _tg.get("parameters", [])
                        _params_str = ", ".join(_params_list[:4])
                        if len(_params_list) > 4:
                            _params_str += f" ...等{_pc}個"
                        _type_lines.append(f"  - {_tcn}({_pc}個參數): {_params_str}")
                    _summary_parts.append(
                        f"異常類型分析 ({len(_atg)} 種):\n" + "\n".join(_type_lines)
                    )

                # (2) T2 概要 (純文字, 不再繪製 MINI_CHART)
                if _t2s:
                    _n_comp = _t2s.get("n_components", 0)
                    _var_exp = _t2s.get("variance_explained", "")
                    _threshold = _t2s.get("t2_threshold", 0)
                    _summary_parts.append(
                        f"PCA-T2 分析: {_n_comp} 個主成分, "
                        f"解釋力 {_var_exp}, "
                        f"異常閾值 T2={_threshold}"
                    )

                # (3) T2 異常區段
                if _ar:
                    _zone_lines = []
                    for _rr in _ar[:7]:
                        _rr_range = _rr.get("range", "")
                        _t2_max = _rr.get("t2_max", _rr.get("t2_mean", 0))
                        _n_params = _rr.get(
                            "affected_params_count", len(_rr.get("params", []))
                        )
                        _top_params = ", ".join(_rr.get("params", [])[:3])
                        _zone_lines.append(
                            f"  - {_rr_range} (T2_max={_t2_max}, {_n_params}個主因): {_top_params}"
                        )
                    _summary_parts.append(
                        f"T2 異常區段 ({len(_ar)} 個):\n" + "\n".join(_zone_lines)
                    )

                # 發送統一的 ProgressEvent
                if _summary_parts:
                    yield ProgressEvent(
                        msg="[AutoTarget 四合一掃描摘要]\n"
                        + "\n\n".join(_summary_parts),
                        turn=state.step_count,
                    )

                self.logger.info(
                    f"[AutoTarget] Synthesizer extracted targets: {_at}, "
                    f"row_ranges: {[r.get('range', '') for r in _ar]}"
                )

                # 將 AutoTarget 數據存入 state (供 Strategist Turn 2 使用)
                if not state.auto_target_raw:
                    state = state.update(
                        role_name="AutoTarget_Syn",
                        auto_target_raw=_syn_at,
                    )

            if state.scene_queue and 0 <= state.current_scene_index < len(
                state.scene_queue
            ):
                _active_sc = state.scene_queue[state.current_scene_index]
                if _active_sc.status == "ACTIVE" and report.key_findings:
                    for _kf in report.key_findings:
                        if _kf and _kf not in _active_sc.findings:
                            _active_sc.findings.append(_kf)
                    self.logger.info(
                        f"[SceneFindings] {_active_sc.scene_id} 累計 "
                        f"{len(_active_sc.findings)} 項發現"
                    )

            # --- Update State (Dashboard) ---
            new_history = state.history + [
                StepResult(
                    role="Synthesizer",
                    conclusion=f"Turn {state.step_count} Findings: {findings_str}",
                    timestamp=0.0,
                    evidence={
                        "raw_evidences": evidences,
                        "analysis_report": report,
                        "structured_log": syn_out.structured_log,
                    },
                )
            ]

            # Track used tools + parameters for diversity (tool::param pairs)
            turn_tools = []
            turn_failed = []
            for ev in evidences:
                if ev.tool_name:
                    # Extract the target parameter from experiment context
                    exp = next(
                        (e for e in experiments if e.id == ev.experiment_id), None
                    )
                    target = (
                        exp.target_columns[0] if exp and exp.target_columns else "all"
                    )
                    key = f"{ev.tool_name}::{target}"
                    turn_tools.append(key)
                    # [Fix 3] Track failures with error detail for LLM feedback
                    if ev.status == "FAIL" or (
                        isinstance(ev.result, dict) and "error" in ev.result
                    ):
                        # Store error reason for Planner context
                        error_msg = ""
                        if isinstance(ev.result, str):
                            error_msg = ev.result[:100]
                        elif isinstance(ev.result, dict):
                            error_msg = str(ev.result.get("error", ""))[:100]
                        failed_key = f"{key}|{error_msg}" if error_msg else key
                        turn_failed.append(failed_key)
            new_tools_history = state.used_tools_history + turn_tools
            new_failed = list(set(state.failed_experiments + turn_failed))

            # Synthesizer 已在 updates 中組裝好完整的 current_knowledge
            # Orchestrator 只負責加入任務管理字段
            final_updates = syn_out.updates.copy() if syn_out.updates else {}
            # 移除 Synthesizer 暫態鍵 (已在 ProgressEvents 輸出中消費)
            final_updates.pop("_auto_target_data", None)
            final_updates.update(
                {
                    "history": new_history,
                    "step_count": state.step_count + 1,
                    "used_tools_history": new_tools_history,
                    "failed_experiments": new_failed,
                }
            )

            # Trigger Immutable Update with Snapshot
            state = state.update(role_name="Orchestrator_V2", **final_updates)

            self.logger.info(
                f"State Version: {state.version}, Tools used: {Counter(new_tools_history).most_common(3)}"
            )

            # (finish_after_turn 已移除 — FINISH 在 Strategist 回傳時直接 break)

            # Respect Synthesizer convergence decision (no SceneGuard)
            if syn_out.decision == "FINISH":
                self.logger.info(
                    "Convergence triggered FINISH from Synthesizer — stopping loop"
                )
                break

        # End of Loop -> Final Result
        # [FIX] Build structured step history for humanizer
        all_steps = []
        for i, step in enumerate(state.history):
            step_data = {
                "step": i + 1,
                "tool": getattr(step, "role", "Unknown"),
                "monologue": getattr(step, "conclusion", ""),
                "result": {},
            }
            # Extract evidence data from step results
            if hasattr(step, "evidence") and step.evidence:
                ev_data = step.evidence
                # Handle new dict format: {raw_evidences: [...], analysis_report: ...}
                if isinstance(ev_data, dict):
                    raw_evidences = ev_data.get("raw_evidences", [])
                    analysis_rpt = ev_data.get("analysis_report", None)

                    # Extract raw evidence details
                    if raw_evidences:
                        for ev in raw_evidences:
                            tool_result = {}
                            if hasattr(ev, "result") and isinstance(ev.result, dict):
                                # [FIX] 過濾掉 Chart.js 渲染配置，已在 all_charts 中單獨提取
                                # chart 字段包含大量 labels/datasets 數組，會嚴重膨脹 Humanizer prompt
                                tool_result = {
                                    k: v
                                    for k, v in ev.result.items()
                                    if k != "chart"
                                    and not (
                                        isinstance(v, dict) and v.get("type") == "chart"
                                    )
                                }
                            step_data["result"][ev.tool_name] = {
                                "status": ev.status,
                                "observation": ev.observation,
                                "data": tool_result,
                            }

                    # Extract analysis report findings
                    if analysis_rpt:
                        step_data["key_findings"] = getattr(
                            analysis_rpt, "key_findings", []
                        )
                        step_data["rejected_hypotheses"] = getattr(
                            analysis_rpt, "rejected_hypotheses", []
                        )
                        step_data["next_step_suggestion"] = getattr(
                            analysis_rpt, "next_step_suggestion", ""
                        )

                    # Extract causal_chain and isolated_observations from structured_log
                    s_log = ev_data.get("structured_log", {})
                    if isinstance(s_log, dict):
                        step_data["causal_chain"] = s_log.get("causal_chain", [])
                        step_data["isolated_observations"] = s_log.get(
                            "isolated_observations", []
                        )
                else:
                    # Legacy: evidence is a list of Evidence objects
                    try:
                        for ev in ev_data:
                            tool_result = {}
                            if hasattr(ev, "result") and isinstance(ev.result, dict):
                                # [FIX] 同上：過濾掉 chart 渲染數據
                                tool_result = {
                                    k: v
                                    for k, v in ev.result.items()
                                    if k != "chart"
                                    and not (
                                        isinstance(v, dict) and v.get("type") == "chart"
                                    )
                                }
                            step_data["result"][getattr(ev, "tool_name", "unknown")] = {
                                "status": getattr(ev, "status", "UNKNOWN"),
                                "observation": getattr(ev, "observation", ""),
                                "data": tool_result,
                            }
                    except (TypeError, AttributeError):
                        step_data["result"]["raw"] = str(ev_data)[:500]
            all_steps.append(step_data)

        # [FIX] Extract chart objects from all evidence results
        all_charts = []
        for step in state.history:
            if not hasattr(step, "evidence") or not step.evidence:
                continue
            ev_data = step.evidence
            raw_evidences = []
            if isinstance(ev_data, dict):
                raw_evidences = ev_data.get("raw_evidences", [])
            elif isinstance(ev_data, list):
                raw_evidences = ev_data
            for ev in raw_evidences:
                if hasattr(ev, "result") and isinstance(ev.result, dict):
                    chart_obj = ev.result.get("chart")
                    if isinstance(chart_obj, dict) and chart_obj.get("type") == "chart":
                        all_charts.append(chart_obj)

        # Build scene summary for Humanizer
        _scene_summary = []
        if state.scene_queue:
            for sc in state.scene_queue:
                # 使用 SceneItem 自身的 findings (由 Strategist 在場景切換時填入)
                sc_findings = list(getattr(sc, "findings", []))

                # 如果場景自身沒有 findings, 嘗試從 targets 相關的 history 中提取
                if not sc_findings and sc.targets:
                    target_set = set(sc.targets)
                    for h in state.history:
                        ev_data = getattr(h, "evidence", None)
                        if isinstance(ev_data, dict):
                            rpt = ev_data.get("analysis_report")
                            if rpt:
                                for kf in getattr(rpt, "key_findings", []):
                                    # 只加入與此場景 targets 相關的 findings
                                    if any(t in str(kf) for t in target_set):
                                        sc_findings.append(kf)

                sc_dict = {
                    "scene_id": sc.scene_id,
                    "label": sc.label,
                    "status": sc.status,
                    "targets": sc.targets or [],
                    "findings": sc_findings,
                }
                _scene_summary.append(sc_dict)

        # --- 收集 follow_up_items ---
        _final_follow_up = getattr(state, "pending_follow_up_items", [])

        # ── [Path S] 延伸場景: 從分析發現生成新的分析場景按鈕 ──
        _is_path_s = any(
            getattr(s, "source", "").startswith("Path_S_intent")
            for s in (state.scene_queue or [])
        )
        if _is_path_s and scene_continue:
            _strategist = self.roles.get("strategist")
            _key_findings_list = []
            for h in state.history:
                ev = getattr(h, "evidence", None)
                if isinstance(ev, dict):
                    rpt = ev.get("analysis_report")
                    if rpt:
                        for kf in getattr(rpt, "key_findings", []):
                            if kf and kf not in _key_findings_list:
                                _key_findings_list.append(kf)
            if _strategist and _key_findings_list:
                try:
                    _ext_scenes = await _strategist._generate_extension_scenes(
                        key_findings=_key_findings_list,
                        original_query=state.original_query or "",
                        state=state,
                    )
                    if _ext_scenes:
                        _final_follow_up = _ext_scenes
                        print(
                            f"[Path S] 延伸場景: 從 {len(_key_findings_list)} 個發現"
                            f"生成 {len(_ext_scenes)} 個延伸分析場景"
                        )
                except Exception as e:
                    print(f"[Path S] 延伸場景生成失敗: {e}, 保留原始 follow_up")

        # --- 收集分析上下文用於持久化 ---
        _analysis_context = {
            "auto_targets": [],
            "auto_row_ranges": [],
            "anomaly_type_groups": [],
            "t2_summary": {},
            "follow_up_items": _final_follow_up,
            "scene_summary": _scene_summary,
            "turn1_path_type": getattr(state, "turn1_path_type", ""),
            "key_findings": [],
        }
        # 從 history 中提取 auto_target_data 和 key_findings
        for h in state.history:
            ev = getattr(h, "evidence", None)
            if isinstance(ev, dict):
                # 提取 auto_target_data (由 FINISH 區塊注入)
                slog = ev.get("structured_log", {})
                if isinstance(slog, dict):
                    _ats = slog.get("auto_target_summary", "")
                    if _ats and not _analysis_context["key_findings"]:
                        _analysis_context["key_findings"].extend(_ats.split("\n"))
                rpt = ev.get("analysis_report")
                if rpt:
                    for kf in getattr(rpt, "key_findings", []):
                        if kf and kf not in _analysis_context["key_findings"]:
                            _analysis_context["key_findings"].append(kf)

        # 從最後一個 strategist structured_log 提取 auto_target_data
        if hasattr(state, "_last_strat_structured_log"):
            _at_data = getattr(state, "_last_strat_structured_log", {}).get(
                "auto_target_data", {}
            )
        else:
            _at_data = {}
        # 備案: 遍歷 all_steps 找含 auto_target_data 的記錄
        if not _at_data:
            for step in reversed(all_steps):
                _ev = getattr(step, "evidence", {})
                if isinstance(_ev, dict):
                    _sl = _ev.get("structured_log", {})
                    if isinstance(_sl, dict) and "auto_target_data" in _sl:
                        _at_data = _sl["auto_target_data"]
                        break
        if _at_data and isinstance(_at_data, dict):
            _analysis_context["auto_targets"] = _at_data.get("auto_targets", [])
            _analysis_context["auto_row_ranges"] = _at_data.get("auto_row_ranges", [])
            _analysis_context["anomaly_type_groups"] = _at_data.get(
                "anomaly_type_groups", []
            )
            _analysis_context["t2_summary"] = _at_data.get("t2_summary", {})

        # [DEBUG] 確認 follow_up_items 內容
        print(
            f"[RESPONSE YIELD] follow_up_items count={len(_final_follow_up)}, "
            f"items={[item.get('scene_id', '?') if isinstance(item, dict) else str(item)[:30] for item in _final_follow_up[:5]]}"
        )

        yield {
            "response": f"V2 Analysis Completed (Steps: {state.step_count - 1}).",
            "final_decision": state.current_knowledge,
            "all_steps_results": all_steps,
            "chart": all_charts,
            "state_version": state.version,
            "scene_summary": _scene_summary,
            "follow_up_items": _final_follow_up,
            "analysis_context": _analysis_context,
        }

        # [DEBUG] 確認 persist 前 scene_queue 狀態
        _sq = getattr(state, "scene_queue", None)
        print(
            f"[STATE PERSIST] session={session_id}, file={file_id}, "
            f"scene_queue={len(_sq) if _sq else 0} scenes, "
            f"pending={sum(1 for s in (_sq or []) if s.status == 'PENDING')}"
        )
        self._persist_state(
            session_id,
            file_id,
            {
                "state": state,
                "summary_data": summary_data,
                "is_deep": is_deep,
                "max_turns": max_turns,
            },
        )

    # --- [QUICK_SCAN] 規則基 Synthesizer ---

    def _quick_scan_synthesize(
        self,
        state: "AnalysisState",
        experiments: list,
        evidences: list,
    ) -> "RoleOutput":
        """
        [QUICK_SCAN] 不調 LLM 的規則基 Synthesizer。
        直接從 evidences 提取結構化結果, 組裝 current_knowledge,
        回傳 CONTINUE 讓 Turn 2 Strategist 建場景。
        """
        from backend.services.analysis.agents.roles_v2.synthesizer import Synthesizer
        from backend.services.analysis.knowledge_utils import (
            set_summary as _set_summary,
            append_dashboard as _append_dashboard,
            append_routing as _append_routing,
        )

        # 1. 提取 AutoTarget
        _at_data = Synthesizer._extract_auto_targets_from_evidence(evidences)

        # 2. 從 evidences 提取關鍵發現 (規則基)
        key_findings = []
        for ev in evidences:
            if ev.status != "SUCCESS":
                continue
            result = ev.result if isinstance(ev.result, dict) else {}

            if ev.tool_name == "detect_outliers":
                top_params = result.get("top_abnormal_parameters", {})
                if isinstance(top_params, dict):
                    for param, z_info in list(top_params.items())[:3]:
                        # z_info 可能是 dict (含 stats.max_z) 或 float
                        if isinstance(z_info, dict):
                            _stats = z_info.get("stats", {})
                            z_val = _stats.get("max_z", _stats.get("max_sigma", 0))
                        elif isinstance(z_info, (int, float)):
                            z_val = z_info
                        else:
                            z_val = 0
                        key_findings.append(
                            f"[参数统计][已验证] {param} Z-Score={z_val}"
                        )

            elif ev.tool_name == "hotelling_t2_analysis":
                n_comp = result.get("n_components_used", 0)
                var_exp = result.get("variance_explained", "")
                anomaly_zones = result.get("anomaly_zones", [])
                if anomaly_zones:
                    top_zone = anomaly_zones[0]
                    zone_range = top_zone.get("zone_range", "")
                    t2_max = top_zone.get("t2_max", 0)
                    key_findings.append(
                        f"[T2分析][已驗證] PCA {n_comp} 主成分 (解釋力 {var_exp}), "
                        f"最大異常區段 {zone_range} T2={t2_max:.1f}"
                    )

            elif ev.tool_name == "scan_anomaly_segments":
                atg = result.get("anomaly_type_groups", [])
                if atg:
                    type_summary = ", ".join(
                        f"{tg.get('type_cn', '')}({tg.get('param_count', 0)})"
                        for tg in atg[:4]
                    )
                    key_findings.append(
                        f"[異常分類][已驗證] {len(atg)} 種異常類型: {type_summary}"
                    )

            elif ev.tool_name == "get_top_correlations":
                top_corrs = result.get("top_correlations", [])
                if top_corrs:
                    key_findings.append(
                        f"[相關性][已驗證] 找到 {len(top_corrs)} 組高相關參數對"
                    )

        if not key_findings:
            key_findings = ["四合一掃描完成，等待進一步分析"]

        # 3. 組裝 current_knowledge
        _ck = state.current_knowledge

        # SUMMARY
        _summary = {
            "total_findings": len(key_findings),
            "top_finding": key_findings[0] if key_findings else "",
            "scan_type": "quick_scan",
        }
        _ck = _set_summary(_ck, _summary)

        # DASHBOARD
        _dashboard = (
            f"[Quick Scan] 四合一掃描完成\n"
            f"Findings: {'; '.join(key_findings[:3])}\n"
            f"Next: 建立追蹤場景"
        )
        _ck = _append_dashboard(_ck, _dashboard)

        # AutoTarget 段落
        if _at_data and (
            _at_data.get("auto_targets") or _at_data.get("auto_row_ranges")
        ):
            _at_lines = []
            _at_targets = _at_data.get("auto_targets", [])
            _atg = _at_data.get("anomaly_type_groups", [])
            _t2s = _at_data.get("t2_summary", {})
            _ar = _at_data.get("auto_row_ranges", [])

            if _at_targets:
                _at_lines.append(
                    f"自動識別 {len(_at_targets)} 個異常參數: "
                    + ", ".join(_at_targets[:10])
                    + (f" ...等{len(_at_targets)}個" if len(_at_targets) > 10 else "")
                )
            if _atg:
                for tg in _atg[:6]:
                    tcn = tg.get("type_cn", tg.get("type", ""))
                    pc = tg.get("param_count", 0)
                    params = tg.get("parameters", [])
                    ps = ", ".join(params[:5])
                    if len(params) > 5:
                        ps += f" ...等{pc}個"
                    _at_lines.append(f"  {tcn}({pc}個參數): {ps}")
            if _t2s:
                nc = _t2s.get("n_components", 0)
                ve = _t2s.get("variance_explained", "")
                th = _t2s.get("t2_threshold", 0)
                _at_lines.append(f"PCA-T2: {nc} 主成分, 解釋力 {ve}, 閾值 T2={th}")
                for az in (_t2s.get("anomaly_zones", []) or [])[:7]:
                    sr = az.get("zone_range", az.get("range", ""))
                    st2 = az.get("t2_max", 0)
                    sp = ", ".join(
                        [
                            c.get("parameter", "")
                            for c in az.get("top_contributors", [])[:3]
                        ]
                    )
                    _at_lines.append(f"  T2 異常區段 {sr} (T2_max={st2}): {sp}")
            if _ar:
                for rr in _ar[:5]:
                    _at_lines.append(
                        f"  異常區段 {rr.get('range', '')} "
                        f"(severity={rr.get('severity', '')}) "
                        + ", ".join(rr.get("params", [])[:3])
                    )
            if _at_lines:
                _at_block = "\n\n## [AutoTarget 全局掃描結果] ##\n" + "\n".join(
                    _at_lines
                )
                _ck = _append_routing(_ck, _at_block)

        # 4. 組裝 RoleOutput
        report = AnalysisReport(
            key_findings=key_findings,
            rejected_hypotheses=[],
            next_step_suggestion="建立追蹤場景，供用戶選擇深入分析",
            synthesis_logic="[Quick Scan] 規則基提取，無 LLM 評估",
        )

        updates = {"current_knowledge": _ck}
        if _at_data and (
            _at_data.get("auto_targets") or _at_data.get("auto_row_ranges")
        ):
            updates["_auto_target_data"] = _at_data

        print(
            f"[QuickScan] 規則基 Synthesizer 完成: "
            f"{len(key_findings)} 項發現, AutoTarget={bool(_at_data)}"
        )

        return RoleOutput(
            decision="CONTINUE",
            reasoning="[Quick Scan] 四合一掃描完成，規則基提取結果，繼續建立場景",
            analysis_report=report,
            structured_log={
                "thought": "快速掃描模式: 規則基提取, 無 LLM 評估",
                "causal_chain": [],
                "isolated_observations": [],
                "analysis_gaps": [],
            },
            updates=updates,
        )

    # --- Follow-up Mode ---

    def classify_followup(
        self, query: str, session_id: str, file_id: str = ""
    ) -> "str | None":
        """
        統一追問分類器。回傳追問類型或 None (非追問)。

        Returns:
            "scene_select" → 場景選擇型: 上次是 interactive 場景選單, 用戶選了場景
            "summary"      → 摘要型: 整理現有結果, 不做新分析
            "explore"      → 探索型: 找其他線索, 排除舊結果
            "drilldown"    → 深入型: 針對已有發現的參數深挖
            "supplement"   → 補充型: 用戶提出新參數假設
            None           → 不是追問, 需要全新分析
        """
        if not self.has_saved_state(session_id, file_id):
            return None

        q = query.strip()

        # ── 0. 場景選擇型: S1/S2/全部執行 (上次是 interactive scene_menu) ──
        _fk = self._state_key(session_id, file_id)
        if _fk not in self._last_states:
            self._load_state_from_disk(session_id, file_id)
        _cached = self._last_states.get(_fk)
        if _cached:
            _state = _cached["state"]

            # 場景來源: scene_queue (SceneItem) 或 pending_follow_up_items (dict)
            _has_pending_scenes = any(
                s.status == "PENDING" for s in (_state.scene_queue or [])
            )
            _pending_fu = getattr(_state, "pending_follow_up_items", []) or []
            _fu_scene_ids = {
                item["scene_id"].upper()
                for item in _pending_fu
                if isinstance(item, dict) and item.get("scene_id")
            }
            _has_followup_scenes = len(_fu_scene_ids) > 0

            if _has_pending_scenes or _has_followup_scenes:
                import re as _re_sc

                # [SCENE_SELECT:S2] 格式 (前端按鈕點擊)
                _scene_select_match = _re_sc.match(r"\[SCENE_SELECT:(S\d+)\]", q)
                if _scene_select_match:
                    _sid = _scene_select_match.group(1).upper()
                    print(f"[classify_followup] scene_select (button): {_sid}")
                    return "scene_select"

                # 檢查「全部執行」
                _q_stripped = q.strip()
                if _q_stripped in ("全部執行", "全部", "all", "ALL", "All"):
                    print(f"[classify_followup] scene_select (all): '{q}'")
                    return "scene_select"

                # 用 findall 提取所有 S 編號
                _found_ids = _re_sc.findall(r"S(\d+)", q, _re_sc.IGNORECASE)
                if _found_ids:
                    # 在 scene_queue 中找
                    _scene_ids = {
                        s.scene_id.upper() for s in (_state.scene_queue or [])
                    }
                    # 合併 follow_up_items 中的 scene_ids
                    _all_scene_ids = _scene_ids | _fu_scene_ids
                    _matched = [
                        f"S{sid}" for sid in _found_ids if f"S{sid}" in _all_scene_ids
                    ]
                    if _matched:
                        print(
                            f"[classify_followup] scene_select "
                            f"(matched {len(_matched)} scenes): {_matched}"
                        )
                        return "scene_select"

                # 場景標籤文字比對 (scene_queue)
                _q_norm = q.strip().lower()
                for _sc in _state.scene_queue or []:
                    _label_norm = (_sc.label or "").strip().lower()
                    if _label_norm and (
                        _q_norm == _label_norm
                        or _label_norm in _q_norm
                        or _q_norm in _label_norm
                    ):
                        print(
                            f"[classify_followup] scene_select (label match): "
                            f"'{q[:40]}' -> {_sc.scene_id}"
                        )
                        return "scene_select"

                # 場景標籤文字比對 (pending_follow_up_items)
                for _fu_item in _pending_fu:
                    if not isinstance(_fu_item, dict):
                        continue
                    _fu_label = (_fu_item.get("label") or "").strip().lower()
                    if _fu_label and (
                        _q_norm == _fu_label
                        or _fu_label in _q_norm
                        or _q_norm in _fu_label
                    ):
                        print(
                            f"[classify_followup] scene_select (fu label): "
                            f"'{q[:40]}' -> {_fu_item.get('scene_id')}"
                        )
                        return "scene_select"

        # ── 1. 摘要型: 整理/總結 (不做新分析) ──
        _summary_kw = [
            "總結",
            "摘要",
            "整理",
            "歸納",
            "列出重點",
            "總結一下",
            "總結重點",
            "幫我整理",
            "簡單說明",
            "簡單解釋",
            "白話文",
            "懶人包",
            "一句話",
            "精簡",
            "換個方式",
            "換句話說",
        ]
        if any(kw in q for kw in _summary_kw):
            return "summary"

        # ── 2. 探索型: 還有其他的嗎 (排除舊結果) ──
        _explore_kw = [
            "還有其他",
            "有沒有其他",
            "其他案例",
            "其他原因",
            "有沒有遺漏",
            "遺漏",
            "還有沒有",
            "有沒有別的",
            "其他可能",
            "是否還有",
            "還有什麼",
        ]
        if any(kw in q for kw in _explore_kw):
            return "explore"

        # ── 3/4. 深入型 vs 補充型: 需要提取參數名 ──
        cached = self._last_states.get(self._state_key(session_id, file_id))
        if cached:
            state = cached["state"]
            # 收集上次分析的目標參數
            _prev_targets = set()
            for scene in state.scene_queue or []:
                for t in scene.targets or []:
                    _prev_targets.add(t.upper())
            for step in state.history or []:
                if step.tool_params:
                    for key in ("target", "targets", "parameter"):
                        val = step.tool_params.get(key, "")
                        if val:
                            for p in str(val).split(","):
                                p = p.strip()
                                if p:
                                    _prev_targets.add(p.upper())

            # 嘗試從 query 中提取參數名稱
            # 規則: 全大寫+底線+數字的 token (e.g., KAPPA_IN, FORMULA-DCS_A15)
            import re

            _param_pattern = re.compile(
                r"[A-Z][A-Z0-9_\-]*(?:_[A-Z0-9]+)+", re.IGNORECASE
            )
            _mentioned = set(m.upper() for m in _param_pattern.findall(q))

            if _mentioned:
                _in_prev = _mentioned & _prev_targets
                _new = _mentioned - _prev_targets

                if _new:
                    # 用戶提到了新參數 → 補充型
                    return "supplement"
                elif _in_prev:
                    # 用戶提到了舊參數 → 深入型
                    return "drilldown"

        # ── 5. 通用追問模式 (無法明確分類但看起來是追問) ──
        _generic_followup = [
            "為什麼",
            "为什么",
            "具體",
            "更詳細",
            "展開",
            "可以再",
            "幫我看",
            "進一步",
            "深入分析",
            "怎麼做",
            "補充",
            "舉例",
            "解釋",
            "這個參數",
            "上面提到",
            "剛才",
        ]
        if any(kw in q for kw in _generic_followup):
            # 預設為深入型 (針對上次分析的主題深挖)
            return "drilldown"

        return None

    def _is_followup(self, query: str) -> bool:
        """向後相容: 判斷是否為追問"""
        # 使用 dummy session_id 做基本模式匹配
        _generic_followup = [
            "那",
            "然後",
            "接下來",
            "續",
            "剛才",
            "上面提到",
            "這個參數",
            "為什麼",
            "为什么",
            "具體",
            "更詳細",
            "展開",
            "可以再",
            "幫我看",
            "進一步",
            "深入分析",
            "總結",
            "補充",
        ]
        return any(p in query for p in _generic_followup)

    def _is_chat_only(self, query: str) -> bool:
        """向後相容: 判斷是否為純對話"""
        _summary_kw = [
            "簡單說明",
            "簡單解釋",
            "白話文",
            "用比較簡單",
            "總結一下",
            "總結重點",
            "列出重點",
            "幫我整理",
            "換個方式",
            "換句話說",
            "能不能簡化",
            "精簡一點",
            "一句話",
            "懶人包",
        ]
        tail = query[-200:] if len(query) > 200 else query
        return any(p in tail for p in _summary_kw)

    async def run_chat_only(self, start_event: StartEvent) -> AsyncGenerator[Any, None]:
        """
        Pure Chat Mode: 不跑任何工具，直接用 LLM 回答對話性質的請求。
        例如「簡單說明」「總結重點」「用白話文解釋」
        若有 cached state，注入 SUMMARY 段落作為分析上下文。
        """
        self.logger.info("[CHAT_ONLY] Handling as pure chat (no tools)")
        yield ProgressEvent(msg="正在整理回覆...")

        # 組合 prompt: 歷史對話 + 用戶當前請求
        history_section = ""
        if start_event.history:
            history_section = f"\n\n以下是最近的對話歷史:\n{start_event.history}"

        # [NEW] 注入 cached state 的分析結果摘要
        analysis_context = ""
        _chat_key = self._state_key(
            start_event.session_id, getattr(start_event, "file_id", "")
        )
        # [PERSIST] 嘗試從磁碟載入
        if _chat_key not in self._last_states:
            self._load_state_from_disk(
                start_event.session_id, getattr(start_event, "file_id", "")
            )
        cached = self._last_states.get(_chat_key)
        if cached:
            state = cached["state"]
            from backend.services.analysis.knowledge_utils import get_summary

            _raw_summary = get_summary(state.current_knowledge)
            if _raw_summary:
                from backend.services.analysis.agents.roles_v2.synthesizer import (
                    format_rolling_summary,
                )

                _formatted = format_rolling_summary(_raw_summary)
                analysis_context = f"\n\n以下是之前分析的結果摘要:\n{_formatted}"

            # 場景發現
            _scene_findings = []
            for scene in state.scene_queue or []:
                if scene.findings:
                    _scene_findings.append(
                        f"- {scene.label}: " + "; ".join(scene.findings[:3])
                    )
            if _scene_findings:
                analysis_context += "\n\n場景發現:\n" + "\n".join(_scene_findings)

        chat_prompt = f"""你是一個友善的工業數據分析助手。
用戶正在對之前的分析結果提出對話性的請求（例如簡化說明、總結重點等）。
請根據分析結果和對話歷史直接回答用戶，不需要執行任何工具或分析。
用繁體中文回答，語氣要自然且易懂。{analysis_context}{history_section}

用戶的訊息:
{start_event.query}

請直接回答:"""

        try:
            response = await self.llm.ainvoke(chat_prompt)
            resp_text = (
                response.content if hasattr(response, "content") else str(response)
            )

            yield TextChunkEvent(content=resp_text)
            yield {
                "response": resp_text,
                "is_chat_only": True,
            }
        except Exception as e:
            self.logger.error(f"[CHAT_ONLY] LLM error: {e}")
            yield {
                "response": f"抱歉，回答時發生錯誤: {str(e)}",
                "is_chat_only": True,
            }

    async def run_followup(
        self,
        start_event: StartEvent,
        summary_data: Dict,
        followup_type: str = "drilldown",
    ) -> AsyncGenerator[Any, None]:
        """
        Follow-up Mode: 繼承上次分析狀態，只跑 1 Turn 針對性分析。

        followup_type:
            "drilldown"  → 深入型: 針對已有發現的參數深挖
            "supplement" → 補充型: 用戶提出新參數假設, 交叉驗證
        """
        session_id = start_event.session_id
        _file_id = getattr(start_event, "file_id", "")
        _fk = self._state_key(session_id, _file_id)
        # [PERSIST] 嘗試從磁碟載入
        if _fk not in self._last_states:
            self._load_state_from_disk(session_id, _file_id)
        cached = self._last_states.get(_fk)

        if not cached:
            yield ProgressEvent(msg="沒有找到上一次分析的狀態，將執行完整分析。")
            async for event in self.run_analysis(start_event, summary_data):
                yield event
            return

        state = cached["state"]
        query = start_event.query or ""

        # ── 提取查詢中提到的參數名稱 ──
        import re

        _param_pattern = re.compile(r"[A-Z][A-Z0-9_\-]*(?:_[A-Z0-9]+)+", re.IGNORECASE)
        _mentioned = [m.upper() for m in _param_pattern.findall(query)]

        # 收集上次分析的目標參數
        _prev_targets = set()
        _prev_findings_str = ""
        for scene in state.scene_queue or []:
            for t in scene.targets or []:
                _prev_targets.add(t.upper())
        for step in state.history or []:
            if step.tool_params:
                for key in ("target", "targets", "parameter"):
                    val = step.tool_params.get(key, "")
                    if val:
                        for p in str(val).split(","):
                            p = p.strip()
                            if p:
                                _prev_targets.add(p.upper())

        # 場景發現摘要
        _findings = []
        for scene in state.scene_queue or []:
            if scene.findings:
                for f in scene.findings[:3]:
                    _findings.append(f)
        _prev_findings_str = "; ".join(_findings[:5]) if _findings else "（無）"

        # ── 根據類型構建上下文指令 ──
        if followup_type == "supplement":
            # 補充型: 用戶提出新參數
            _new_params = [p for p in _mentioned if p not in _prev_targets]
            _target_params = _new_params if _new_params else _mentioned
            _targets_str = ", ".join(_target_params) if _target_params else "用戶指定"

            _type_directive = (
                f"\n[追問模式: 用戶假設驗證]\n"
                f"用戶提出新假設: {_targets_str} 可能與異常有關\n"
                f"上次發現的異常參數: {', '.join(sorted(_prev_targets)[:10])}\n"
                f"上次結論: {_prev_findings_str}\n"
                f"→ 請檢查 {_targets_str} 與已知異常參數的關聯性、交互效應\n"
                f"→ 建議工具: get_top_correlations, correlation_network, compare_data_segments\n"
            )
            _progress_msg = f"補充型追問: 驗證 {_targets_str} 與已知異常的關聯..."
        else:
            # 深入型: 針對已有發現的參數
            _old_params = [p for p in _mentioned if p in _prev_targets]
            _target_params = _old_params if _old_params else list(_prev_targets)[:3]
            _targets_str = ", ".join(_target_params) if _target_params else "主要參數"

            _type_directive = (
                f"\n[追問模式: 深入調查]\n"
                f"用戶要求深入分析已知異常參數: {_targets_str}\n"
                f"上次結論: {_prev_findings_str}\n"
                f"→ 請做更細緻的因果分析、區段比較、上下游參數追蹤\n"
                f"→ 建議工具: scan_anomaly_segments, compare_data_segments, "
                f"analyze_feature_importance\n"
            )
            _progress_msg = f"深入型追問: 深入分析 {_targets_str}..."

        yield ProgressEvent(msg=_progress_msg)
        self.logger.info(
            f"[FOLLOWUP-{followup_type.upper()}] targets={_targets_str}, "
            f"prev_targets_count={len(_prev_targets)}"
        )

        # ── 更新 State: 注入追問上下文 ──
        state = state.update(
            role_name="Followup",
            max_steps=state.step_count + 1,
            original_query=query,
            current_knowledge=state.current_knowledge + _type_directive,
        )

        # ── Single Turn: Planner -> Executor -> Synthesizer ──
        yield ProgressEvent(msg="正在規劃針對性實驗...")

        followup_context = (
            f"## 追問類型: {'補充驗證' if followup_type == 'supplement' else '深入調查'}\n"
            f"## 目標參數: {_targets_str}\n"
            f"## 上次分析摘要\n{_prev_findings_str}\n\n"
            f"## 用戶追問\n{query}\n\n"
            f"請針對用戶的追問，規劃 1-3 個實驗來回答。"
        )

        plan_in = RoleInput(
            state_machine=state,
            directive=followup_context,
        )
        plan_out = await self.roles["planner"].execute(plan_in)
        experiments = plan_out.experiments or []

        if not experiments:
            yield {
                "response": "無法針對您的追問規劃實驗。請嘗試更具體地描述您想了解的內容。",
                "structured_report": None,
                "chart": [],
            }
            return

        yield ProgressEvent(msg=f"執行 {len(experiments)} 個針對性實驗...")

        exec_in = RoleInput(state_machine=state, experiments=experiments)
        exec_out = await self.roles["executor"].execute(exec_in)
        evidences = exec_out.evidences or []

        for ev in evidences:
            status_icon = "OK" if ev.status == "SUCCESS" else "FAIL"
            yield ProgressEvent(
                msg=f"[{status_icon}] [{ev.tool_name}] {ev.observation[:80]}"
            )

        # Synthesize
        yield ProgressEvent(msg="正在綜合回答...")
        syn_in = RoleInput(
            state_machine=state,
            experiments=experiments,
            evidences=evidences,
        )
        syn_out = await self.roles["synthesizer"].execute(syn_in)
        report = syn_out.analysis_report

        # Build concise follow-up response
        findings_str = (
            "; ".join(report.key_findings) if report.key_findings else "未發現新資訊"
        )

        yield {
            "response": findings_str,
            "final_decision": report.synthesis_logic,
            "structured_report": {
                "executive_summary": findings_str,
                "findings": [
                    {"title": f, "severity": "MEDIUM", "detail": f}
                    for f in (report.key_findings or [])
                ],
                "action_items": [],
                "is_followup": True,
                "followup_type": followup_type,
            },
            "chart": [],
        }

        # Update cached state for chaining follow-ups
        new_history = state.history + [
            StepResult(
                role="Followup",
                conclusion=f"[{followup_type}] {findings_str}",
                timestamp=0.0,
                evidence={
                    "raw_evidences": evidences,
                    "analysis_report": report,
                },
            )
        ]
        state = state.update(
            role_name="Followup",
            history=new_history,
            step_count=state.step_count + 1,
        )
        _file_id = getattr(start_event, "file_id", "")
        _key = self._state_key(session_id, _file_id)
        self._persist_state(
            session_id,
            _file_id,
            {
                "state": state,
                "summary_data": cached["summary_data"],
                "is_deep": cached["is_deep"],
                "max_turns": cached["max_turns"],
            },
        )

    async def run_scene_select(
        self,
        start_event: "StartEvent",
        summary_data: Dict,
        selected_query: str,
    ) -> AsyncGenerator[Any, None]:
        """
        場景選擇模式: 用戶在 interactive 場景選單中選了 S1/S2/全部執行,
        或複製了場景標籤文字, 啟動選定場景,
        對場景呼叫 _expand_concepts 展開參數後, 調用 run_analysis(resume=True)。
        """
        session_id = start_event.session_id
        _file_id = getattr(start_event, "file_id", "")
        _fk = self._state_key(session_id, _file_id)

        # 嘗試載入 state
        if _fk not in self._last_states:
            self._load_state_from_disk(session_id, _file_id)
        cached = self._last_states.get(_fk)

        if not cached:
            yield ProgressEvent(msg="沒有找到上一次的場景規劃，將執行完整分析。")
            async for event in self.run_analysis(start_event, summary_data):
                yield event
            return

        state = cached["state"]
        q_raw = selected_query.strip()

        # 解析用戶選擇
        import re as _re_sel
        from ..analysis_types import SceneItem as _SceneItem

        _q_stripped = q_raw.strip()
        _is_all = _q_stripped in ("全部執行", "全部", "全部", "all", "ALL", "All")

        # 從 pending_follow_up_items 中收集場景 dict
        _pending_fu = getattr(state, "pending_follow_up_items", []) or []
        _fu_scene_map = {}
        for item in _pending_fu:
            if isinstance(item, dict) and item.get("scene_id"):
                _fu_scene_map[item["scene_id"].upper()] = item

        def _fu_to_scene_item(fu_dict: dict) -> "_SceneItem":
            """將 follow_up_items 中的 dict 轉換為 SceneItem"""
            return _SceneItem(
                scene_id=fu_dict.get("scene_id", "S1"),
                scene_type=fu_dict.get("scene_type", "parameter"),
                label=fu_dict.get("label", ""),
                targets=fu_dict.get("targets", []),
                status="ACTIVE",
            )

        if _is_all:
            # 全部執行: 啟動所有 PENDING 場景 (scene_queue) + follow_up 場景
            _activated_count = 0
            for s in state.scene_queue or []:
                if s.status == "PENDING":
                    s.status = "ACTIVE"
                    _activated_count += 1
            # 把 follow_up 場景也加入 scene_queue
            for _sid, _fu in _fu_scene_map.items():
                _new_sc = _fu_to_scene_item(_fu)
                if not state.scene_queue:
                    state = state.update(role_name="SceneSelect", scene_queue=[_new_sc])
                else:
                    state.scene_queue.append(_new_sc)
                _activated_count += 1
            _selected_label = f"全部場景 ({_activated_count} 個)"
            print(f"[run_scene_select] 全部執行, 啟動 {_activated_count} 個場景")
        else:
            # 嘗試 [SCENE_SELECT:S2] 格式 (前端按鈕點擊)
            _btn_match = _re_sel.match(r"\[SCENE_SELECT:(S\d+)\]", q_raw)
            # 或用 findall 提取所有 S 編號
            _found_ids = _re_sel.findall(r"S(\d+)", q_raw, _re_sel.IGNORECASE)

            _scene_map = {s.scene_id.upper(): s for s in (state.scene_queue or [])}

            _target_sids = []
            if _btn_match:
                _target_sids = [_btn_match.group(1).upper()]
            elif _found_ids:
                _target_sids = [f"S{sid}" for sid in _found_ids]

            if _target_sids:
                _activated = []
                for _sid_key in _target_sids:
                    # 先在 scene_queue 中找
                    _sc = _scene_map.get(_sid_key)
                    if _sc and _sc.status == "PENDING":
                        _sc.status = "ACTIVE"
                        _activated.append(f"{_sc.scene_id}: {_sc.label}")
                    # 再在 pending_follow_up_items 中找
                    elif _sid_key in _fu_scene_map:
                        _new_sc = _fu_to_scene_item(_fu_scene_map[_sid_key])
                        if not state.scene_queue:
                            state = state.update(
                                role_name="SceneSelect",
                                scene_queue=[_new_sc],
                            )
                        else:
                            state.scene_queue.append(_new_sc)
                        _activated.append(f"{_new_sc.scene_id}: {_new_sc.label}")

                if _activated:
                    _selected_label = " | ".join(_activated)
                    print(
                        f"[run_scene_select] 啟動 {len(_activated)} 個場景: "
                        f"{_selected_label}"
                    )
                else:
                    # 找到 S 編號但不在任何來源中, fallback
                    _fallback = False
                    for s in state.scene_queue or []:
                        if s.status == "PENDING":
                            s.status = "ACTIVE"
                            _fallback = True
                            break
                    if not _fallback and _fu_scene_map:
                        _first_fu = next(iter(_fu_scene_map.values()))
                        _new_sc = _fu_to_scene_item(_first_fu)
                        if not state.scene_queue:
                            state = state.update(
                                role_name="SceneSelect",
                                scene_queue=[_new_sc],
                            )
                        else:
                            state.scene_queue.append(_new_sc)
                    _selected_label = "第一個待執行場景 (指定編號未找到)"
                    print(f"[run_scene_select] 指定場景不存在, 啟動第一個可用場景")
            else:
                # 文字比對: 用戶可能複製了場景描述文字
                _q_norm = q_raw.lower()
                _matched_scene = None

                # 先在 scene_queue 中比對
                for s in state.scene_queue or []:
                    _label_norm = (s.label or "").strip().lower()
                    if _label_norm and (
                        _q_norm == _label_norm
                        or _label_norm in _q_norm
                        or _q_norm in _label_norm
                    ):
                        _matched_scene = s
                        break

                # 再在 pending_follow_up_items 中比對
                _matched_fu = None
                if not _matched_scene:
                    for _fu_item in _pending_fu:
                        if not isinstance(_fu_item, dict):
                            continue
                        _fu_label = (_fu_item.get("label") or "").strip().lower()
                        if _fu_label and (
                            _q_norm == _fu_label
                            or _fu_label in _q_norm
                            or _q_norm in _fu_label
                        ):
                            _matched_fu = _fu_item
                            break

                if _matched_scene:
                    _matched_scene.status = "ACTIVE"
                    _selected_label = (
                        f"{_matched_scene.scene_id}: {_matched_scene.label}"
                    )
                    print(f"[run_scene_select] 文字比對命中: {_selected_label}")
                elif _matched_fu:
                    _new_sc = _fu_to_scene_item(_matched_fu)
                    if not state.scene_queue:
                        state = state.update(
                            role_name="SceneSelect", scene_queue=[_new_sc]
                        )
                    else:
                        state.scene_queue.append(_new_sc)
                    _selected_label = f"{_new_sc.scene_id}: {_new_sc.label}"
                    print(f"[run_scene_select] follow_up 文字比對: {_selected_label}")
                else:
                    # 最終 Fallback
                    _fallback = False
                    for s in state.scene_queue or []:
                        if s.status == "PENDING":
                            s.status = "ACTIVE"
                            _fallback = True
                            break
                    if not _fallback and _fu_scene_map:
                        _first_fu = next(iter(_fu_scene_map.values()))
                        _new_sc = _fu_to_scene_item(_first_fu)
                        if not state.scene_queue:
                            state = state.update(
                                role_name="SceneSelect",
                                scene_queue=[_new_sc],
                            )
                        else:
                            state.scene_queue.append(_new_sc)
                    _selected_label = "第一個待執行場景"
                    print(f"[run_scene_select] 無法匹配, 啟動第一個待執行場景")

        yield ProgressEvent(msg=f"啟動場景分析: {_selected_label}")

        # ── [概念展開] 對已啟動的場景做 _expand_concepts ──
        # interactive 模式跳過了概念展開, 在這裡補上
        _strategist = self.roles.get("strategist")
        _all_columns = summary_data.get("parameters", [])
        _term_mappings = summary_data.get("mappings", {})
        _active_scenes = [s for s in (state.scene_queue or []) if s.status == "ACTIVE"]
        _groups = {}  # 概念展開分組結果, 供後續 _build_scenes_from_intent 使用
        _intent_label = ""

        if _strategist and _all_columns and _active_scenes:
            import math as _math
            import asyncio as _asyncio

            _n_batches = _math.ceil(len(_all_columns) / 50)
            for _asc in _active_scenes:
                _intent_label = _asc.label or ""
                if not _intent_label:
                    continue

                # ── segment 類型場景 (異常區段根因調查) 跳過概念展開 ──
                # 根因調查需要檢查所有參數才能找到異常原因, 提前篩選會遺漏
                _scene_type = getattr(_asc, "scene_type", "") or ""
                if _scene_type == "segment":
                    _asc.targets = list(_all_columns)  # 使用全部欄位
                    print(
                        f"[run_scene_select] {_asc.scene_id} 為 segment 類型, "
                        f"跳過概念展開, 直接使用全部 {len(_all_columns)} 個參數"
                    )
                    yield ProgressEvent(
                        msg=f"場景 {_asc.scene_id} 為區段調查類型, "
                        f"直接使用全部 {len(_all_columns)} 個參數進行根因分析"
                    )
                    continue

                try:
                    yield ProgressEvent(
                        msg=f"正在為場景 {_asc.scene_id} 掃描 "
                        f"{len(_all_columns)} 個欄位中的相關參數..."
                    )

                    # 即時進度: 用 asyncio.Queue 讓批次進度即時發送到前端
                    _progress_queue: _asyncio.Queue = _asyncio.Queue()

                    def _on_batch_progress(msg: str):
                        _progress_queue.put_nowait(msg)

                    async def _run_expand():
                        try:
                            return await _strategist._expand_concepts(
                                query=state.original_query,
                                all_columns=_all_columns,
                                term_mappings=_term_mappings,
                                existing_targets=_asc.targets or [],
                                intents=[_intent_label],
                                progress_callback=_on_batch_progress,
                            )
                        finally:
                            _progress_queue.put_nowait(None)  # sentinel

                    _expand_task = _asyncio.create_task(_run_expand())

                    # 即時 poll queue, 每收到一條就 yield MonologueEvent (AI思考流程)
                    while True:
                        _pmsg = await _progress_queue.get()
                        if _pmsg is None:  # sentinel = 展開完成
                            break
                        yield MonologueEvent(
                            monologue=f"[概念展開] {_asc.scene_id} {_pmsg}",
                            tool_name="concept_expand",
                            tool_params={},
                            query=state.original_query or "",
                            file_id=start_event.file_id,
                            session_id=start_event.session_id,
                            history="",
                        )

                    _expanded, _groups = await _expand_task

                    if _expanded:
                        # 合併展開結果到場景 targets (去重)
                        _merged = list(dict.fromkeys((_asc.targets or []) + _expanded))
                        _asc.targets = _merged
                        print(
                            f"[run_scene_select] {_asc.scene_id} 概念展開完成: "
                            f"{len(_expanded)} 新參數, 總計 {len(_merged)} 個 targets"
                        )
                        yield ProgressEvent(
                            msg=f"場景 {_asc.scene_id}: 從 {len(_all_columns)} 個欄位篩選出 "
                            f"{len(_merged)} 個與「{_intent_label}」相關的參數"
                        )
                    else:
                        print(
                            f"[run_scene_select] {_asc.scene_id} 概念展開無結果, "
                            f"保留原始 targets: {_asc.targets}"
                        )
                except Exception as e:
                    print(
                        f"[run_scene_select] {_asc.scene_id} 概念展開失敗: {e}, "
                        f"保留原始 targets"
                    )

        # ── [Path S] 從概念展開參數做製程領域分群, 再產生分析場景 ──
        _analysis_scenes = []
        _expanded_all = []
        # 收集所有概念展開結果
        for _asc in _active_scenes:
            if _asc.targets:
                _expanded_all.extend(_asc.targets)
        _expanded_all = list(dict.fromkeys(_expanded_all))  # 去重

        if _strategist and len(_expanded_all) >= 4:
            yield ProgressEvent(
                msg=f"正在將 {len(_expanded_all)} 個參數按製程領域分群..."
            )
            try:
                _domain_clusters = await _strategist._cluster_params_by_domain(
                    expanded_params=_expanded_all,
                    term_mappings=_term_mappings,
                    intent_label=_intent_label,
                )
            except Exception as e:
                print(f"[run_scene_select] 參數分群失敗: {e}")
                _domain_clusters = {}

            if _domain_clusters and len(_domain_clusters) >= 2:
                # 通知用戶分群結果
                _cluster_summary = ", ".join(
                    f"{k}({len(v)}個)" for k, v in _domain_clusters.items()
                )
                yield ProgressEvent(msg=f"參數分群完成: {_cluster_summary}")
                yield ProgressEvent(msg="正在規劃分析場景...")
                # 取得父場景 ID, 用於子場景層級命名 (如 A2 → A2.1, A2.2)
                _parent_sid = ""
                if _active_scenes:
                    _parent_sid = _active_scenes[0].scene_id or ""
                try:
                    _analysis_scenes = await _strategist._build_scenes_from_intent(
                        intent_label=_intent_label,
                        intent_groups=_domain_clusters,
                        all_columns=_all_columns,
                        state=state,
                        parent_scene_id=_parent_sid,
                    )
                except Exception as e:
                    print(f"[run_scene_select] 分析場景生成失敗: {e}")
                    _analysis_scenes = []

        if _analysis_scenes:
            # 用分析場景替換 scene_queue
            state = state.update(
                role_name="SceneSelect",
                scene_queue=_analysis_scenes,
                current_scene_index=0,
            )
            # 通知用戶
            _scene_labels = [f"{s.scene_id}: {s.label}" for s in _analysis_scenes]
            yield ProgressEvent(
                msg=f"規劃完成: {len(_analysis_scenes)} 個分析場景 — "
                + " | ".join(_scene_labels)
            )
            print(
                f"[run_scene_select] [Path S] 注入 {len(_analysis_scenes)} 個分析場景, "
                f"取代原場景 {_selected_label}"
            )
        else:
            # Fallback: 無法產生分析場景, 沿用原始流程
            print(
                "[run_scene_select] [Path S] 無分析場景, 退回原始 scene_continue 流程"
            )
            _selected_idx = -1
            for _i, _s in enumerate(state.scene_queue or []):
                if _s.status == "ACTIVE":
                    _selected_idx = _i
                    break
            if _selected_idx < 0 and (state.scene_queue or []):
                _selected_idx = len(state.scene_queue) - 1
            state = state.update(
                role_name="SceneSelect",
                current_scene_index=_selected_idx,
            )

        # 重置 step_count 到 2 (讓 Strategist 走 Turn 2+ 邏輯)
        state = state.update(
            role_name="SceneSelect",
            step_count=2,
        )

        # 更新 cached state
        cached["state"] = state
        self._persist_state(session_id, _file_id, cached)

        # 改寫 query: 移除 [SCENE_SELECT:Sx] 前綴, 加上「分析」前綴
        _active_label = _selected_label or ""
        _rewritten_query = f"分析以下場景: {_active_label}"
        print(
            f"[run_scene_select] query 改寫: {start_event.query!r} → {_rewritten_query!r}"
        )

        from backend.services.analysis.analysis_types import StartEvent as _StartEvent

        _analysis_start = _StartEvent(
            query=_rewritten_query,
            file_id=start_event.file_id,
            session_id=start_event.session_id,
            history=start_event.history,
            suspect_pool=start_event.suspect_pool,
            mode=start_event.mode,
        )

        # 以 scene_continue=True 繼續分析 (從已啟動的場景開始, 不重置場景)
        async for event in self.run_analysis(
            _analysis_start, summary_data, scene_continue=True
        ):
            yield event
