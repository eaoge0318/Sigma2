"""
分群代表趨勢圖 (Cluster Representative Trend)
- 將同概念的大量參數依相關性分群
- 每群選 CV 最高者為代表
- 畫各代表的趨勢疊圖
"""

import numpy as np
import pandas as pd
import logging
from typing import Any, Dict, List
from .base import AnalysisTool

logger = logging.getLogger(__name__)

# 固定調色盤 (最多 8 群)
CLUSTER_COLORS = [
    "rgba(59, 130, 246, 1)",  # blue
    "rgba(239, 68, 68, 1)",  # red
    "rgba(16, 185, 129, 1)",  # green
    "rgba(245, 158, 11, 1)",  # amber
    "rgba(139, 92, 246, 1)",  # violet
    "rgba(236, 72, 153, 1)",  # pink
    "rgba(6, 182, 212, 1)",  # cyan
    "rgba(107, 114, 128, 1)",  # gray
]


class ClusterTrendTool(AnalysisTool):
    """分群代表趨勢圖: 大量同概念參數分群後, 各群代表畫趨勢疊圖"""

    @property
    def name(self) -> str:
        return "cluster_trend"

    @property
    def description(self) -> str:
        return (
            "分群代表趨勢圖: 將大量相關參數依相關性分群, "
            "每群選 CV 最高的代表參數, 畫趨勢疊圖。"
            "適合概念(如「溫度」)對應太多欄位時使用。"
        )

    @property
    def required_params(self) -> List[str]:
        return ["file_id"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        """
        參數:
            parameters: list[str] — 要分群的參數列表
            concept: str — 概念關鍵字 (從 mapping 展開, parameters 優先)
            n_clusters: int — 分群數 (預設 3)
        """
        try:
            file_id = params.get("file_id")
            summary = self.analysis_service.load_summary(session_id, file_id)
            if not summary:
                return {"status": "ERROR", "message": "No summary data available"}

            filename = summary["filename"]
            csv_path = (
                self.analysis_service.base_dir / session_id / "uploads" / filename
            )
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
            df.columns = [str(c).strip() for c in df.columns]

            # --- 解析參數列表 ---
            target_params = self._resolve_parameters(
                params, df, summary.get("mappings", {})
            )

            if not target_params:
                return {
                    "status": "ERROR",
                    "message": "無法找到匹配的參數。請提供 parameters 列表或 concept 關鍵字。",
                }

            # 單參數 fallback: 直接畫趨勢圖
            if len(target_params) == 1:
                return self._single_param_trend(df, target_params[0], summary)

            # 只保留數值欄位
            numeric_params = [
                p
                for p in target_params
                if p in df.columns and pd.api.types.is_numeric_dtype(df[p])
            ]
            if len(numeric_params) < 2:
                return {
                    "status": "WARNING",
                    "message": f"數值參數不足 ({len(numeric_params)} 個), 需至少 2 個參數才能分群",
                }

            n_clusters = min(int(params.get("n_clusters", 3)), len(numeric_params))

            # --- 分群 ---
            sub_df = df[numeric_params].dropna()
            if len(sub_df) < 10:
                return {
                    "status": "WARNING",
                    "message": f"有效資料列不足 ({len(sub_df)} 筆)",
                }

            # 相關性距離矩陣
            corr = sub_df.corr().fillna(0)
            dist = (1 - corr.abs()).clip(lower=0)

            from sklearn.cluster import AgglomerativeClustering

            clustering = AgglomerativeClustering(
                n_clusters=n_clusters,
                metric="precomputed",
                linkage="average",
            )
            labels = clustering.fit_predict(dist.values)

            # --- 每群選代表 (CV 最高) ---
            cluster_info = []
            representatives = []
            stats = self.analysis_service.load_statistics(session_id, file_id) or {}

            for cid in range(n_clusters):
                members = [
                    numeric_params[i] for i, lbl in enumerate(labels) if lbl == cid
                ]
                if not members:
                    continue

                # CV = std / |mean|
                cv_map = {}
                for m in members:
                    s = stats.get(m, {})
                    mean_v = abs(s.get("mean", 0))
                    std_v = s.get("std", 0)
                    cv_map[m] = std_v / mean_v if mean_v > 1e-9 else std_v

                rep = max(members, key=lambda m: cv_map.get(m, 0))
                representatives.append(rep)

                # 中文名
                mappings = summary.get("mappings", {})
                member_names = [
                    f"{m} ({mappings.get(m, '')})" if mappings.get(m) else m
                    for m in members
                ]
                rep_name = (
                    f"{rep} ({mappings.get(rep, '')})" if mappings.get(rep) else rep
                )

                cluster_info.append(
                    {
                        "cluster_id": cid + 1,
                        "size": len(members),
                        "representative": rep_name,
                        "representative_code": rep,
                        "cv": round(cv_map.get(rep, 0), 4),
                        "members": member_names[:10],  # 最多顯示 10 個
                        "total_members": len(members),
                    }
                )

            # --- 建圖: 各代表的趨勢疊圖 ---
            chart = self._build_cluster_chart(
                df, representatives, summary.get("mappings", {})
            )

            return {
                "status": "OK",
                "total_parameters": len(numeric_params),
                "n_clusters": n_clusters,
                "clusters": cluster_info,
                "chart": chart,
                "interpretation": self._build_interpretation(
                    cluster_info, numeric_params
                ),
            }

        except ImportError:
            return {
                "status": "ERROR",
                "message": "需要 scikit-learn 套件: pip install scikit-learn",
            }
        except Exception as e:
            logger.error(f"ClusterTrend error: {e}", exc_info=True)
            return {"status": "ERROR", "message": str(e)}

    def _resolve_parameters(
        self, params: Dict, df: pd.DataFrame, mappings: Dict
    ) -> List[str]:
        """從 parameters 列表或 concept 關鍵字解析目標參數"""
        # 1. 直接指定 parameters
        explicit = params.get("parameters") or params.get("parameter")
        if explicit:
            if isinstance(explicit, str):
                explicit = [p.strip() for p in explicit.split(",")]
            return [p for p in explicit if p in df.columns]

        # 2. concept 關鍵字展開
        concept = params.get("concept") or params.get("target")
        if concept and mappings:
            matched = []
            for col, cn_name in mappings.items():
                if concept in cn_name or concept.lower() in col.lower():
                    if col in df.columns:
                        matched.append(col)
            return matched

        # 3. 用 target 作為關鍵字搜所有欄位
        if concept:
            return [c for c in df.columns if concept.lower() in c.lower()]

        return []

    def _single_param_trend(
        self, df: pd.DataFrame, param: str, summary: Dict
    ) -> Dict[str, Any]:
        """單參數 fallback: 畫基本趨勢圖"""
        series = df[param].dropna().values.astype(float)
        n = len(series)

        # Downsample
        max_pts = 80
        if n > max_pts:
            step = n // max_pts
            idx = list(range(0, n, step))[:max_pts]
        else:
            idx = list(range(n))

        labels = [str(i) for i in idx]
        data_pts = [round(float(series[i]), 4) for i in idx]

        mappings = summary.get("mappings", {})
        cn_name = mappings.get(param, param)

        chart = {
            "type": "chart",
            "chart_type": "line",
            "title": f"{cn_name} 趨勢圖",
            "labels": labels,
            "datasets": [
                {
                    "label": cn_name,
                    "data": data_pts,
                    "borderColor": CLUSTER_COLORS[0],
                    "backgroundColor": "transparent",
                    "borderWidth": 1.5,
                    "pointRadius": 0,
                    "fill": False,
                }
            ],
        }

        return {
            "status": "OK",
            "total_parameters": 1,
            "n_clusters": 1,
            "message": "僅 1 個參數, 直接繪製趨勢圖",
            "chart": chart,
        }

    def _build_cluster_chart(
        self, df: pd.DataFrame, representatives: List[str], mappings: Dict
    ) -> Dict[str, Any]:
        """建立各群代表的趨勢疊圖"""
        datasets = []
        n = len(df)

        # Downsample
        max_pts = 80
        if n > max_pts:
            step = n // max_pts
            idx = list(range(0, n, step))[:max_pts]
        else:
            idx = list(range(n))

        labels = [str(i) for i in idx]

        for i, rep in enumerate(representatives):
            if rep not in df.columns:
                continue

            series = df[rep].values
            # 標準化到 [0, 1] 便於視覺比較
            s_min, s_max = np.nanmin(series), np.nanmax(series)
            if s_max - s_min > 1e-9:
                normalized = (series - s_min) / (s_max - s_min)
            else:
                normalized = np.zeros_like(series)

            data_pts = [
                round(float(normalized[j]), 4) if not np.isnan(normalized[j]) else None
                for j in idx
            ]
            cn_name = mappings.get(rep, rep)
            color = CLUSTER_COLORS[i % len(CLUSTER_COLORS)]

            datasets.append(
                {
                    "label": f"群{i + 1}: {cn_name}",
                    "data": data_pts,
                    "borderColor": color,
                    "backgroundColor": "transparent",
                    "borderWidth": 1.5,
                    "pointRadius": 0,
                    "fill": False,
                }
            )

        return {
            "type": "chart",
            "chart_type": "line",
            "title": f"分群代表趨勢圖 ({len(representatives)} 群)",
            "labels": labels,
            "datasets": datasets,
            "options": {
                "scales": {
                    "x": {"display": True, "grid": {"display": False}},
                    "y": {
                        "beginAtZero": False,
                        "title": {"display": True, "text": "標準化值 (0~1)"},
                    },
                },
            },
        }

    def _build_interpretation(
        self, cluster_info: List[Dict], all_params: List[str]
    ) -> str:
        """生成分群結果的文字解讀"""
        lines = [f"將 {len(all_params)} 個參數依相關性分為 {len(cluster_info)} 群:"]
        for c in cluster_info:
            lines.append(
                f"  群{c['cluster_id']}: {c['size']} 個參數, "
                f"代表={c['representative']} (CV={c['cv']:.3f})"
            )
        lines.append(
            "圖表顯示各群代表參數的標準化趨勢 (值域 0~1), 可比較不同量綱的參數走勢。"
        )
        return "\n".join(lines)
