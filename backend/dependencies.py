"""
依賴注入
提供服務的單例實例
"""

from backend.services.session_service import SessionService
from backend.services.file_service import FileService
from backend.services.prediction_service import PredictionService
from backend.services.analysis_service import AnalysisService
from backend.services.ai_service import AIService
from backend.services.chart_ai_service import ChartAIService
from backend.services.draft_service import DraftService

# 單例實例
_session_service: SessionService = None
_file_service: FileService = None
_prediction_service: PredictionService = None
_analysis_service: AnalysisService = None
_ai_service: AIService = None
_chart_ai_service: ChartAIService = None


def get_session_service() -> SessionService:
    """取得 Session 服務"""
    global _session_service
    if _session_service is None:
        _session_service = SessionService()
    return _session_service


def get_file_service() -> FileService:
    """取得檔案服務"""
    global _file_service
    if _file_service is None:
        _file_service = FileService()
    return _file_service


def get_prediction_service() -> PredictionService:
    """取得預測服務"""
    global _prediction_service
    if _prediction_service is None:
        _prediction_service = PredictionService()
    return _prediction_service


def get_analysis_service() -> AnalysisService:
    """取得分析服務"""
    global _analysis_service
    if _analysis_service is None:
        _analysis_service = AnalysisService()
    return _analysis_service


def get_ai_service() -> AIService:
    """取得 AI 服務"""
    global _ai_service
    if _ai_service is None:
        _ai_service = AIService()
    return _ai_service


def get_chart_ai_service() -> ChartAIService:
    """取得圖表 AI 服務"""
    global _chart_ai_service
    if _chart_ai_service is None:
        _chart_ai_service = ChartAIService()
    return _chart_ai_service


_draft_service: DraftService = None


def get_draft_service() -> DraftService:
    """取得暫存服務"""
    global _draft_service
    if _draft_service is None:
        _draft_service = DraftService()
    return _draft_service
