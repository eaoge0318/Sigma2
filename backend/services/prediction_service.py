"""
預測服務
封裝 AgenticReasoning 的業務邏輯
"""

import numpy as np
from typing import Dict, Any
import logging
from core_logic.agent_logic import AgenticReasoning

# 获取 logger
logger = logging.getLogger(__name__)


class PredictionService:
    """預測服務，負責 IQL 推理和建議生成 (多租戶版)"""

    def __init__(self):
        self._agents: Dict[str, AgenticReasoning] = {}

    def get_agent(self, session_id: str) -> AgenticReasoning:
        """取得特定使用者的 Agent 實例"""
        print(f"[DEBUG] PredictionService.get_agent called for session: {session_id}")
        print(f"[DEBUG] PredictionService instance ID: {id(self)}")
        print(f"[DEBUG] Existing agents: {list(self._agents.keys())}")

        if session_id not in self._agents:
            print(f"[DEBUG] Creating new agent for session: {session_id}")
            try:
                # 傳入 session_id 以載入該使用者最近的模型
                self._agents[session_id] = AgenticReasoning(session_id)
                print(f"PredictionService: Agent for session {session_id} initialized")
            except Exception as e:
                print(
                    f"PredictionService: Session {session_id} agent load failed - {e}"
                )
                return None
        else:
            print(f"[DEBUG] Reusing existing agent for session: {session_id}")
        return self._agents[session_id]

    def is_ready(self, session_id: str = "default") -> bool:
        """檢查特定使用者的服務是否就緒"""
        return self.get_agent(session_id) is not None

    async def predict(
        self, row: Dict[str, Any], measure_value: float, session_id: str = "default"
    ) -> Dict[str, Any]:
        """執行預測並返回建議"""
        # logger.debug("=" * 60)
        # logger.debug("🎯 PredictionService.predict() 被调用")
        # logger.debug("=" * 60)
        # logger.debug(f"Session ID: {session_id}")
        # logger.debug(f"Measure Value: {measure_value}")
        # logger.debug(f"Row data keys: {list(row.keys())[:10]}...")

        agent = self.get_agent(session_id)
        if not agent:
            logger.error(f"❌ Agent not available for session {session_id}")
            raise RuntimeError(f"PredictionService not ready for session {session_id}")

        # logger.debug("✅ Agent found, calling get_reasoned_advice()...")

        # 執行推理
        agent_out = agent.get_reasoned_advice(row, float(measure_value))

        # 格式化輸出
        recommendations = {}

        # 檢查是否有有效的動作建議
        has_valid_actions = (
            agent_out.get("iql_action_delta") is not None
            and agent_out.get("iql_action_delta_smoothed") is not None
        )

        for i, feat in enumerate(agent.action_features):
            display_name = feat  # 直接使用原始特徵名稱

            # 安全獲取建議值
            delta = agent_out["iql_action_delta"][i] if has_valid_actions else 0.0
            delta_smoothed = (
                agent_out["iql_action_delta_smoothed"][i] if has_valid_actions else 0.0
            )

            current_val = float(row[feat])

            recommendations[display_name] = {
                "current": current_val,
                "suggested_delta": delta,
                "suggested_delta_smoothed": delta_smoothed,
                "suggested_next": float(current_val + delta),
                "suggested_next_smoothed": float(current_val + delta_smoothed),
            }

        feature_snapshots = {}
        for feat in agent.bg_features + agent.action_features:
            chn_name = feat  # 直接使用原始特徵名稱
            raw_val = row.get(feat)
            final_val = (
                float(raw_val)
                if raw_val is not None
                and not (isinstance(raw_val, float) and np.isnan(raw_val))
                else 0.0
            )
            feature_snapshots[chn_name] = final_val

        # 從 agent 中讀取 target_range (從 JSON 配置載入)
        target_range = [agent.y_low, agent.y_high]

        # 嘗試從 session 中獲取 goalSettings
        from backend.dependencies import get_session_service

        session_service = get_session_service()
        dashboard_session = session_service.get_dashboard_session(session_id)
        if (
            hasattr(dashboard_session, "current_model_config")
            and dashboard_session.current_model_config
        ):
            goal_settings = dashboard_session.current_model_config.get(
                "goalSettings"
            ) or dashboard_session.current_model_config.get("goal_settings")
            if goal_settings:
                try:
                    lsl = float(goal_settings.get("lsl", agent.y_low))
                    usl = float(goal_settings.get("usl", agent.y_high))
                    target_range = [lsl, usl]
                    logger.info(f"Using target_range from model config: {target_range}")
                except (ValueError, TypeError) as e:
                    logger.warning(f"Failed to parse goalSettings, using default: {e}")

        # 從 session 中獲取 measure_name (goal)
        measure_name = "目標值"  # 預設值
        if (
            hasattr(dashboard_session, "current_model_config")
            and dashboard_session.current_model_config
        ):
            measure_name = dashboard_session.current_model_config.get("goal", "目標值")

        return {
            "status": agent_out["status"],
            "current_measure": float(measure_value),
            "measure_name": measure_name,  # 加入 measure_name
            "target_range": target_range,
            "recommendations": recommendations,
            "feature_snapshots": feature_snapshots,
            "predicted_y_next": agent_out["predicted_y_next"]
            if agent_out["status"] != "HOLD"
            else None,
            "top_influencers": agent_out["top_influencers"],
            "current_top_influencers": agent_out["current_top_influencers"],
            "smoothed_top_influencers": agent_out["smoothed_top_influencers"],
            "diagnosis": agent_out["diagnosis"],
        }
