"""
Session 管理服務
集中管理所有 Session，避免全域狀態污染
"""

from typing import Dict
from backend.models.session_models import DashboardSession, AnalysisSession, AISession


class SessionService:
    """Session 管理服務，為不同功能提供隔離的 Session"""

    def __init__(self):
        self._dashboard_sessions: Dict[str, DashboardSession] = {}
        self._analysis_sessions: Dict[str, AnalysisSession] = {}
        self._ai_sessions: Dict[str, AISession] = {}

    def get_dashboard_session(self, session_id: str) -> DashboardSession:
        """取得即時看板 Session"""
        print(f"[DEBUG] SessionService.get_dashboard_session called")
        print(f"[DEBUG] Session ID requested: {session_id}")
        print(
            f"[DEBUG] Current _dashboard_sessions keys: {list(self._dashboard_sessions.keys())}"
        )
        print(
            f"[DEBUG] session_id in _dashboard_sessions: {session_id in self._dashboard_sessions}"
        )

        if session_id not in self._dashboard_sessions:
            print(f"[DEBUG] Creating NEW DashboardSession for {session_id}")
            self._dashboard_sessions[session_id] = DashboardSession()
            print(
                f"[DEBUG] New session object ID: {id(self._dashboard_sessions[session_id])}"
            )
        else:
            print(f"[DEBUG] Returning EXISTING DashboardSession for {session_id}")
            print(
                f"[DEBUG] Existing session object ID: {id(self._dashboard_sessions[session_id])}"
            )

        return self._dashboard_sessions[session_id]

    def get_analysis_session(self, session_id: str) -> AnalysisSession:
        """取得數據分析 Session"""
        if session_id not in self._analysis_sessions:
            self._analysis_sessions[session_id] = AnalysisSession()
        return self._analysis_sessions[session_id]

    def get_ai_session(self, session_id: str) -> AISession:
        """取得 AI 對話 Session"""
        if session_id not in self._ai_sessions:
            self._ai_sessions[session_id] = AISession()
        return self._ai_sessions[session_id]

    def clear_dashboard_session(self, session_id: str):
        """清空即時看板 Session 的預測歷史，但保留已載入的數據和模型"""
        if session_id in self._dashboard_sessions:
            session = self._dashboard_sessions[session_id]
            # 只清除预测历史，保留 sim_df 和其他关键数据
            session.prediction_history = []
            session.latest_snapshot = None
            print(
                f"[DEBUG] Cleared prediction history for session {session_id}, but kept sim_df"
            )

    def clear_analysis_session(self, session_id: str):
        """清空數據分析 Session"""
        if session_id in self._analysis_sessions:
            self._analysis_sessions[session_id] = AnalysisSession()
