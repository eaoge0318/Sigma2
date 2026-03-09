"""
PCA 降維趨勢圖 (PCA Trend)
- 將同概念的大量參數做 PCA 降維
- 畫各主成分的趨勢圖
- 提供各主成分的解釋方差比 + 主要貢獻參數 (loadings)
"""

import numpy as np
import pandas as pd
import logging
from typing import Any, Dict, List
from .base import AnalysisTool

logger = logging.getLogger(__name__)

PC_COLORS = [
    "rgba(59, 130, 246, 1)",  # blue  - PC1
    "rgba(239, 68, 68, 1)",  # red   - PC2
    "rgba(16, 185, 129, 1)",  # green - PC3
    "rgba(245, 158, 11, 1)",  # amber - PC4
    "rgba(139, 92, 246, 1)",  # violet - PC5
]


class PCATrendTool(AnalysisTool):
    """PCA 降維趨勢圖: 大量同概念參數降維後, 畫主成分趨勢圖"""

    @property
    def name(self) -> str:
        return "pca_trend"

    @property
    def description(self) -> str:
        return (
            "PCA 降維趨勢圖: 將大量相關參數做主成分分析, "
            "畫各主成分的時間序列趨勢, 並顯示各主成分的解釋方差與主要貢獻參數。"
            "適合概念(如「溫度」)對應太多欄位時, 用降維壓縮觀察整體趨勢。"
        )

    @property
    def required_params(self) -> List[str]:
        return ["file_id"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        """
        參數:
            parameters: list[str] — 要降維的參數列表
            concept: str — 概念關鍵字 (從 mapping 展開, parameters 優先)
            n_components: int — 主成分數 (預設 3)
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

            # 只保留數值欄位
            numeric_params = [
                p
                for p in target_params
                if p in df.columns and pd.api.types.is_numeric_dtype(df[p])
            ]

            if len(numeric_params) < 2:
                return {
                    "status": "WARNING",
                    "message": f"數值參數不足 ({len(numeric_params)} 個), 需至少 2 個才能做 PCA",
                }

            n_components = min(
                int(params.get("n_components", 3)),
                len(numeric_params),
            )

            # --- PCA ---
            sub_df = df[numeric_params].dropna()
            if len(sub_df) < 10:
                return {
                    "status": "WARNING",
                    "message": f"有效資料列不足 ({len(sub_df)} 筆)",
                }

            from sklearn.preprocessing import StandardScaler
            from sklearn.decomposition import PCA

            scaler = StandardScaler()
            scaled = scaler.fit_transform(sub_df.values)

            pca = PCA(n_components=n_components)
            scores = pca.fit_transform(scaled)  # (n_samples, n_components)

            # --- Loadings: 各主成分的主要貢獻參數 ---
            mappings = summary.get("mappings", {})
            components_info = []
            for i in range(n_components):
                variance_ratio = float(pca.explained_variance_ratio_[i])
                loadings = pca.components_[i]
                abs_loadings = np.abs(loadings)
                top_indices = np.argsort(abs_loadings)[::-1][:5]

                top_contributors = []
                for j in top_indices:
                    param_name = numeric_params[j]
                    cn_name = mappings.get(param_name, "")
                    display = f"{param_name} ({cn_name})" if cn_name else param_name
                    top_contributors.append(
                        {
                            "parameter": display,
                            "loading": round(float(loadings[j]), 4),
                        }
                    )

                components_info.append(
                    {
                        "pc": i + 1,
                        "variance_ratio": round(variance_ratio, 4),
                        "variance_pct": f"{variance_ratio * 100:.1f}%",
                        "cumulative_pct": f"{float(np.sum(pca.explained_variance_ratio_[: i + 1])) * 100:.1f}%",
                        "top_contributors": top_contributors,
                    }
                )

            # --- 建圖: 各主成分趨勢圖 ---
            chart = self._build_pca_chart(scores, n_components, components_info)

            total_var = float(np.sum(pca.explained_variance_ratio_))

            return {
                "status": "OK",
                "total_parameters": len(numeric_params),
                "n_components": n_components,
                "total_variance_explained": f"{total_var * 100:.1f}%",
                "components": components_info,
                "chart": chart,
                "interpretation": self._build_interpretation(
                    components_info, numeric_params, total_var
                ),
            }

        except ImportError:
            return {
                "status": "ERROR",
                "message": "需要 scikit-learn 套件: pip install scikit-learn",
            }
        except Exception as e:
            logger.error(f"PCATrend error: {e}", exc_info=True)
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

    def _build_pca_chart(
        self,
        scores: np.ndarray,
        n_components: int,
        components_info: List[Dict],
    ) -> Dict[str, Any]:
        """建立各主成分的趨勢圖 (Chart.js 格式)"""
        n = scores.shape[0]

        # Downsample
        max_pts = 80
        if n > max_pts:
            step = n // max_pts
            idx = list(range(0, n, step))[:max_pts]
        else:
            idx = list(range(n))

        labels = [str(i) for i in idx]
        datasets = []

        for i in range(n_components):
            pc_scores = scores[:, i]
            data_pts = [round(float(pc_scores[j]), 4) for j in idx]
            color = PC_COLORS[i % len(PC_COLORS)]
            info = components_info[i]

            datasets.append(
                {
                    "label": f"PC{i + 1} ({info['variance_pct']})",
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
            "title": f"PCA 降維趨勢圖 ({n_components} 主成分)",
            "labels": labels,
            "datasets": datasets,
            "options": {
                "scales": {
                    "x": {"display": True, "grid": {"display": False}},
                    "y": {
                        "beginAtZero": False,
                        "title": {"display": True, "text": "主成分分數 (標準化)"},
                    },
                },
            },
        }

    def _build_interpretation(
        self,
        components_info: List[Dict],
        all_params: List[str],
        total_var: float,
    ) -> str:
        """生成 PCA 結果的文字解讀"""
        lines = [
            f"將 {len(all_params)} 個參數做 PCA, "
            f"前 {len(components_info)} 個主成分解釋 {total_var * 100:.1f}% 的總變異量:"
        ]

        for c in components_info:
            top3 = c["top_contributors"][:3]
            contrib_text = ", ".join(
                f"{t['parameter']}({t['loading']:+.2f})" for t in top3
            )
            lines.append(
                f"  PC{c['pc']}: 解釋 {c['variance_pct']} 方差, "
                f"主要貢獻: {contrib_text}"
            )

        if total_var < 0.5:
            lines.append(
                "注意: 總解釋方差較低 (<50%), 表示參數間行為差異較大, "
                "PCA 壓縮效果有限, 建議搭配分群分析。"
            )

        return "\n".join(lines)
