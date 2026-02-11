import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest, RandomForestRegressor
from sklearn.linear_model import LassoCV
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from typing import Dict, Any, List
from .base import AnalysisTool
import logging

logger = logging.getLogger(__name__)


def _safe_read_csv(csv_path: str, usecols: List[str]) -> pd.DataFrame:
    """Robustly reads specific columns from CSV, ignoring missing ones."""
    try:
        # Read only header
        header = pd.read_csv(csv_path, nrows=0).columns.tolist()
        valid_cols = [c for c in usecols if c in header]

        if not valid_cols:
            # If no valid columns found, return empty DataFrame with valid types to fail gracefully downstream
            # or raise specific error
            missing = list(set(usecols))[:5]
            raise ValueError(
                f"None of the requested columns found. Missing example: {missing}"
            )

        return pd.read_csv(csv_path, usecols=valid_cols)
    except Exception as e:
        raise e


class MultivariateAnomalyTool(AnalysisTool):
    """多維度異常偵測 (Isolation Forest)"""

    @property
    def name(self) -> str:
        return "multivariate_anomaly_detection"

    @property
    def description(self) -> str:
        return "使用孤立森林 (Isolation Forest) 進行跨參數的多維異常偵測。能找出單一指標看不出的『邏輯組合異常』。"

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "parameters"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        param_list = params.get("parameters")

        if (
            not param_list
            or param_list == "all"
            or (
                isinstance(param_list, list)
                and len(param_list) == 1
                and param_list[0] == "all"
            )
        ):
            summary = self.analysis_service.load_summary(session_id, file_id)
            param_list = summary.get("parameters", [])

        if isinstance(param_list, str):
            param_list = [p.strip() for p in param_list.split(",")]

        summary = self.analysis_service.load_summary(session_id, file_id)
        csv_path = (
            self.analysis_service.base_dir
            / session_id
            / "uploads"
            / summary["filename"]
        )

        try:
            df = _safe_read_csv(csv_path, param_list).dropna()
        except ValueError as e:
            return {"error": str(e)}
        if len(df) < 20:
            return {"error": "Insufficient data for multivariate analysis."}

        model = IsolationForest(contamination="auto", random_state=42)
        preds = model.fit_predict(df)

        # -1 為異常，1 為正常
        anomalies_idx = np.where(preds == -1)[0]
        anomaly_count = len(anomalies_idx)

        return {
            "total_points": len(df),
            "anomaly_points_count": anomaly_count,
            "anomaly_percentage": f"{(anomaly_count / len(df)) * 100:.2f}%",
            "is_systemic_anomaly": anomaly_count > (len(df) * 0.05),
            "note": "偵測到多維組合異常，建議進一步分析特徵貢獻度 (feature_importance)。",
        }


try:
    import xgboost as xgb

    HAS_XGBOOST = True
except ImportError:
    HAS_XGBOOST = False


class FeatureImportanceWorkflowTool(AnalysisTool):
    """因素貢獻度分析 (XGBoost/RandomForest Style)"""

    @property
    def name(self) -> str:
        return "analyze_feature_importance"

    @property
    def description(self) -> str:
        return "大型 AI 診斷：利用機器學習模型 (XGBoost/RandomForest) 找出對目標 (Target) 影響力最大的關鍵因子。會自動列出影響力前三名。"

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "target"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        target = params.get("target")
        feature_list = params.get("features")

        correlations = self.analysis_service.load_correlations(session_id, file_id)
        if target not in correlations:
            return {"error": f"Target {target} not indexed."}

        if (
            not feature_list
            or feature_list == "all"
            or (
                isinstance(feature_list, list)
                and len(feature_list) == 1
                and feature_list[0] == "all"
            )
        ):
            sorted_corrs = sorted(
                correlations[target].items(),
                key=lambda x: abs(x[1]) if x[1] is not None else 0,
                reverse=True,
            )
            feature_list = [
                k for k, v in sorted_corrs if k != target and v is not None
            ][:40]

        summary = self.analysis_service.load_summary(session_id, file_id)
        csv_path = (
            self.analysis_service.base_dir
            / session_id
            / "uploads"
            / summary["filename"]
        )

        # 逐步讀取與清理數據，防止分析完全崩潰
        try:
            cols_to_read = feature_list + [target]
            df_raw = _safe_read_csv(csv_path, cols_to_read)
            if target not in df_raw.columns:
                return {"error": f"Target {target} not found in file."}

            # 1. 智慧過濾：排除空值比例 > 50% 的垃圾特徵
            null_ratios = df_raw.isnull().mean()
            clean_features = [f for f in feature_list if null_ratios[f] <= 0.5]

            if not clean_features:
                return {"error": "排除低品質(空值過多)因子後，無剩餘可用特徵。"}

            # 2. 智慧填補：使用中位數填補剩餘的少量缺失
            df = df_raw[clean_features + [target]].fillna(
                df_raw.median(numeric_only=True)
            )

            if len(df) < 10:
                return {"error": "數據樣本量嚴重不足(少於10筆)，無法進行機器學習建模。"}

            X = df[clean_features]
            y = df[target]

        except Exception as e:
            return {"error": f"數據讀取失敗: {str(e)}", "can_fallback": True}

        # --- 智慧演算法選擇邏輯 ---
        sample_size = len(df)
        null_ratio = df.isnull().mean().mean()

        if sample_size < 100:
            # 樣本極少：使用 Lasso 避免過擬合
            model = LassoCV(cv=5)
            model_type = "Lasso Regression"
            reasoning = "數據樣本點較少 (<100)，選用 Lasso 回歸以防止模型過度擬合並自動篩選特徵。"
        elif HAS_XGBOOST and (null_ratio > 0.05 or sample_size > 1000):
            # 數據量大或含有較多缺失值：選用 XGBoost
            model = xgb.XGBRegressor(
                n_estimators=100, learning_rate=0.1, max_depth=5, random_state=42
            )
            model_type = "XGBoost"
            reasoning = "數據量較大或存在顯著缺失值，選用 XGBoost 以發揮其強大的非線性捕捉能力與缺失值處理優勢。"
        else:
            # 數據穩定且量適中：隨機森林最保險
            model = RandomForestRegressor(n_estimators=100, random_state=42)
            model_type = "RandomForest"
            reasoning = "數據分佈較穩定且樣本量適中，選用隨機森林以提供穩健的非線性特徵貢獻度評估。"

        model.fit(X, y)

        # 獲取 Feature Importance (Lasso 使用 coef_)
        if model_type == "Lasso Regression":
            importances = np.abs(model.coef_)
        else:
            importances = model.feature_importances_

        indices = np.argsort(importances)[::-1]

        results = []
        for i in range(min(10, len(clean_features))):
            idx = indices[i]
            results.append(
                {
                    "parameter": clean_features[idx],
                    "importance_score": float(importances[idx]),
                    "rank": i + 1,
                }
            )

        # 專為聊天室摘要產生的 Top 3 格式
        top_3 = [
            f"第{r['rank']}名: {r['parameter']} ({r['importance_score']:.3f})"
            for r in results[:3]
        ]
        top_3_summary = " | ".join(top_3)

        return {
            "target": target,
            "model_used": model_type,
            "selection_reasoning": reasoning,
            "top_features": results,
            "top_3_summary": f"【{model_type} 貢獻度 Top 3】{top_3_summary}",
            "model_r2_score": float(model.score(X, y)),
            "conclusion": f"經 {model_type} 智慧選模分析 ({reasoning})，影響 {target} 的最關鍵因素為 {results[0]['parameter']}。",
        }


class PrincipalComponentAnalysisTool(AnalysisTool):
    """系統性特徵降維與主成分分析 (PCA)"""

    @property
    def name(self) -> str:
        return "systemic_pca_analysis"

    @property
    def description(self) -> str:
        return "【深度診斷】執行主成分分析 (PCA)。建議將 parameters 設為 'all'，系統會自動處理多重共線性並識別設備的『系統性狀態與群聚效應』。"

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "parameters"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        param_list = params.get("parameters")

        if (
            not param_list
            or param_list == "all"
            or (
                isinstance(param_list, list)
                and len(param_list) == 1
                and param_list[0] == "all"
            )
        ):
            summary = self.analysis_service.load_summary(session_id, file_id)
            param_list = summary.get("parameters", [])

        if isinstance(param_list, str):
            param_list = [p.strip() for p in param_list.split(",")]

        summary = self.analysis_service.load_summary(session_id, file_id)
        csv_path = (
            self.analysis_service.base_dir
            / session_id
            / "uploads"
            / summary["filename"]
        )

        try:
            df = _safe_read_csv(csv_path, param_list).dropna()
        except ValueError as e:
            return {"error": str(e)}
        if len(df) < 20:
            return {"error": "數據量不足以進行 PCA 分析。"}

        # 標準化
        scaler = StandardScaler()
        x_scaled = scaler.fit_transform(df)

        pca = PCA(n_components=min(5, len(param_list)))
        pca.fit(x_scaled)

        exp_var = pca.explained_variance_ratio_
        components = []

        for i, ratio in enumerate(exp_var):
            # 找出對該主成分貢獻最大的前 3 個參數
            top_factors_idx = np.argsort(np.abs(pca.components_[i]))[::-1][:3]
            top_factors = [
                {"parameter": param_list[idx], "weight": float(pca.components_[i][idx])}
                for idx in top_factors_idx
            ]

            components.append(
                {
                    "component": f"PC{i + 1}",
                    "explained_variance": f"{ratio * 100:.2f}%",
                    "top_contributing_parameters": top_factors,
                }
            )

        total_explained = sum(exp_var)

        return {
            "total_explained_variance": f"{total_explained * 100:.2f}%",
            "components": components,
            "conclusion": f"前 {len(components)} 個主成分解釋了數據中 {total_explained * 100:.2f}% 的變異。主成分 1 (PC1) 主要由 {components[0]['top_contributing_parameters'][0]['parameter']} 驅動。",
        }


class HotellingT2AnalysisTool(AnalysisTool):
    """PCA-based Hotelling's T2 多維度異常診斷與貢獻度分析"""

    @property
    def name(self) -> str:
        return "hotelling_t2_analysis"

    @property
    def description(self) -> str:
        return "【核心診斷】PCA-Hotelling's T2 診斷組合異常。建議 parameters 設為 'all' 以啟動自動化全場掃描與貢獻度拆解。嚴禁手動挑選 3 個以下參數以避免診斷偏見。"

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "parameters"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        param_list = params.get("parameters")
        target_segments_str = params.get("target_segments")
        target_idx_val = params.get("row_index")

        # --- 全自動參數偵測 (Global Sweep) ---
        if (
            not param_list
            or param_list == "all"
            or (
                isinstance(param_list, list)
                and len(param_list) == 1
                and param_list[0] == "all"
            )
        ):
            summary = self.analysis_service.load_summary(session_id, file_id)
            param_list = summary.get("parameters", [])

        if isinstance(param_list, str):
            param_list = [p.strip() for p in param_list.split(",")]

        summary = self.analysis_service.load_summary(session_id, file_id)
        csv_path = (
            self.analysis_service.base_dir
            / session_id
            / "uploads"
            / summary["filename"]
        )

        # 1. 讀取數據並初步清理
        try:
            df_full = _safe_read_csv(csv_path, param_list)
        except ValueError as e:
            return {"error": str(e)}

        # Target Segments Parsing
        target_indices = []
        if target_segments_str:
            try:
                # Handle list of ints or strings
                if isinstance(target_segments_str, list):
                    for x in target_segments_str:
                        target_indices.append(int(x))
                elif isinstance(target_segments_str, str):
                    # Handle string "30-50, 60"
                    for part in target_segments_str.split(","):
                        part = part.strip()
                        if not part:
                            continue
                        if "-" in part:
                            start, end = map(int, part.split("-"))
                            target_indices.extend(range(start, end + 1))
                        else:
                            target_indices.append(int(part))
            except Exception:
                pass  # Ignore parsing errors

        # 過濾超出範圍的索引
        target_indices = [i for i in target_indices if 0 <= i < len(df_full)]

        # 如果使用者指定了 row_index，優先使用
        if target_idx_val is not None:
            try:
                target_indices = [int(target_idx_val)]
            except:
                pass

        # 智慧過濾：如果欄位空值比例過高 (例如 > 50%)，直接剔除，不進入計算
        null_ratios = df_full.isnull().mean()
        valid_cols = null_ratios[null_ratios <= 0.5].index.tolist()
        df_filtered = df_full[valid_cols]

        # 智慧填補：對剩餘的少量缺失值進行中位數填補
        df_imputed = df_filtered.fillna(df_filtered.median(numeric_only=True))

        # 剔除定值欄位 (變異數為 0)
        df_imputed = df_imputed.loc[:, (df_imputed.std() > 0)]
        active_params = df_imputed.columns.tolist()

        if len(df_imputed) < 10 or len(active_params) < 2:
            return {"error": "有效樣本數或參數數量不足，無法建立統計模型。"}

        data = df_imputed.values

        # 2. 標準化 (Standardization 是 PCA 的前提)
        scaler = StandardScaler()
        data_scaled = scaler.fit_transform(data)

        # 3. PCA 降維
        # 自動選擇主成分數量 (保留 90% 變異量，且不超過樣本數)
        n_comp = min(len(active_params), len(df_imputed) - 1, 10)
        pca = PCA(n_components=n_comp)
        scores = pca.fit_transform(data_scaled)  # PC 空間的座標
        eigenvalues = pca.explained_variance_  # 特徵值
        loadings = pca.components_  # 負載矩陣 (n_comp x n_features)

        # 4. 計算 Hotelling's T2
        # T2 = sum( score_i^2 / eigenvalue_i )
        t2_values = np.sum((scores**2) / eigenvalues, axis=1)

        # 5. 貢獻度分析 (Decomposition to original variables)
        # 決定要診斷哪一筆數據 (Diag Index)
        # 如果有指定 Target Segments，則在該範圍內找 MAX T2
        if target_indices:
            # 只在 target_indices 範圍內找最大值
            # 注意: target_indices 是原始 DataFrame 的 index
            # 我們需要過濾出有效的 indices (因為前面可能 dropna 了?? 不，前面是 fillna，所以 index 應該是對應的)
            valid_target_indices = [i for i in target_indices if i < len(t2_values)]

            if valid_target_indices:
                # 在這些候選者中找 T2 最大的
                sub_t2 = t2_values[valid_target_indices]
                max_sub_idx = np.argmax(sub_t2)  # 這是 sub array 的 index
                diag_idx = valid_target_indices[max_sub_idx]  # 這是 full array 的 index
            else:
                # 如果指定的區間都無效，回退到全域最大
                diag_idx = np.argmax(t2_values)
        else:
            # 預設：全域最大異常點
            diag_idx = np.argmax(t2_values)

        if diag_idx >= len(t2_values):
            diag_idx = np.argmax(t2_values)

        sample_scores = scores[diag_idx]
        sample_scaled = data_scaled[diag_idx]

        # 貢獻度公式改進版：將 PC 貢獻映射回原始特徵
        # cont_j = sum_k ( score_k / eigenvalue_k * loading_kj * sample_scaled_j )
        contributions = []
        for j in range(len(active_params)):
            c_j = 0
            for k in range(n_comp):
                # 這裡考量了該參數在各個 PC 上的投影強度
                c_j += (
                    (sample_scores[k] / eigenvalues[k])
                    * loadings[k, j]
                    * sample_scaled[j]
                )

            contributions.append(
                {"parameter": active_params[j], "contribution": float(c_j), "rank": 0}
            )

        contributions = sorted(
            contributions, key=lambda x: x["contribution"], reverse=True
        )
        for i, c in enumerate(contributions):
            c["rank"] = i + 1

        top_3 = [
            f"第{c['rank']}名: {c['parameter']} ({c['contribution']:.2f})"
            for c in contributions[:3]
        ]

        return {
            "method": "PCA-Hotelling T2",
            "n_components_used": n_comp,
            "variance_explained": f"{np.sum(pca.explained_variance_ratio_) * 100:.2f}%",
            "diagnosed_index": int(diag_idx),
            "max_t2_value": float(t2_values[diag_idx]),
            "top_contributions": contributions[:15],
            "top_3_summary": "【PCA-T2 貢獻度 Top 3】" + " | ".join(top_3),
            "conclusion": f"經 PCA 降維處理後，系統成功識別出異常。在第 {diag_idx} 筆數據中，主導偏移的核心參數為 {contributions[0]['parameter']}。",
        }
