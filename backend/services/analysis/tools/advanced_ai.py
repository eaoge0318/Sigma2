import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest, RandomForestRegressor
from sklearn.linear_model import LassoCV
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from typing import Dict, Any, List
from .base import AnalysisTool
import logging
from scipy import stats  # [NEW] For Chi-Square threshold

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


def _smart_feature_filter(
    df: pd.DataFrame, target_col: str = None, top_k: int = 50
) -> pd.DataFrame:
    """
    智慧特徵篩選 (Smart Feature Selection)
    三道防線：
    1.剔除空值率 > 50% 的欄位
    2.剔除定值 (std=0) 的欄位
    3.如果有 target，剔除與 target 相關性極低 (|corr| < 0.05) 的欄位
    4.最後如果還是太多，保留 Top K (依據相關性或變異數)
    """
    initial_cols = df.columns.tolist()

    # 1. Missing Value Filter
    null_ratio = df.isnull().mean()
    valid_cols = null_ratio[null_ratio <= 0.5].index.tolist()
    df = df[valid_cols]

    # 2. Zero Variance Filter
    numeric_df = df.select_dtypes(include=[np.number])
    stds = numeric_df.std()
    # 保留 std > 0 或者非數值欄位(如果有)
    keep_cols = stds[stds > 0].index.tolist()
    # 把 target 加回來以免誤刪
    if target_col and target_col in df.columns and target_col not in keep_cols:
        keep_cols.append(target_col)

    df = df[keep_cols]

    # 如果已經很精簡，直接返回
    if len(df.columns) <= top_k:
        logger.info(
            f"Smart Filter: Reduced features from {len(initial_cols)} to {len(df.columns)}"
        )
        return df

    # 3. Correlation Filter (Target-based)
    if target_col and target_col in df.columns:
        corrs = df.corrwith(df[target_col]).abs()
        # 濾除低相關 (<0.05)
        # 且必須保留 target 本身
        significant_cols = corrs[corrs > 0.05].index.tolist()
        if target_col not in significant_cols:
            significant_cols.append(target_col)

        df = df[significant_cols]

        # 4. Top-K Selection (Target-based)
        if len(df.columns) > top_k:
            # 重新計算相關性排序
            sorted_cols = df.corrwith(df[target_col]).abs().sort_values(ascending=False)
            top_cols = sorted_cols.head(top_k).index.tolist()
            if target_col not in top_cols:  # 確保 target 在裡面
                top_cols[0] = target_col
            df = df[top_cols]

    # 5. Top-K Selection (Unsupervised / Variance-based)
    else:
        # 如果沒有 target，則優先保留變異數大的 (代表資訊量大)
        start_stds = df.std().sort_values(ascending=False)
        top_cols = start_stds.head(top_k).index.tolist()
        df = df[top_cols]

    logger.info(
        f"Smart Filter: Reduced features from {len(initial_cols)} to {len(df.columns)}"
    )
    return df


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
        return ["file_id"]

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

        # [Smart Filter] No forced truncation here. We rely on smart filtering after reading data.

        # [Cache] Use get_dataframe
        df_full = self.analysis_service.get_dataframe(session_id, file_id)
        if df_full is None:
            return {"error": "無法讀取數據文件"}

        try:
            # Filter params if specific ones requested
            if isinstance(param_list, list) and "all" not in param_list:
                valid_cols = [c for c in param_list if c in df_full.columns]
                # If valid_cols is empty, maybe we should warn, but likely the user just wants anomaly detection
                if valid_cols:
                    df_full = df_full[valid_cols]

            # 確保只讀取數值型欄位進行運算，排除時間戳或字串 ID
            df = df_full.select_dtypes(include=[np.number])

            # [Smart Filter] Apply intelligent reduction
            df = _smart_feature_filter(df, top_k=50)
            df = df.dropna()
        except ValueError as e:
            return {"error": str(e)}
        if len(df) < 20:
            return {"error": "Insufficient data for multivariate analysis."}

        model = IsolationForest(contamination="auto", random_state=42)
        preds = model.fit_predict(df)

        # -1 為異常，1 為正常
        anomalies_idx = np.where(preds == -1)[0]
        anomaly_count = len(anomalies_idx)

        result_data = {
            "total_points": len(df),
            "anomaly_points_count": anomaly_count,
            "anomaly_percentage": f"{(anomaly_count / len(df)) * 100:.2f}%",
            "is_systemic_anomaly": anomaly_count > (len(df) * 0.05),
            "note": "偵測到多維組合異常，建議進一步分析特徵貢獻度 (feature_importance)。",
        }
        # [Compat] Add 'evidence' key
        result_data["evidence"] = result_data
        return result_data


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
        target_raw = params.get("target")
        feature_list = params.get("features")

        # [Smart Filter] No forced truncation on names, we filter data later.

        # 解析多目標輸入 (支援字串逗號分隔或列表)
        if isinstance(target_raw, list):
            candidates = target_raw
        elif isinstance(target_raw, str) and "," in target_raw:
            candidates = [t.strip() for t in target_raw.split(",") if t.strip()]
        else:
            candidates = [target_raw] if target_raw else []

        correlations = self.analysis_service.load_correlations(session_id, file_id)

        # 篩選出有效的 targets (存在於索引中的欄位名)
        valid_targets = [c for c in candidates if c in correlations]
        # 去重保序
        seen = set()
        valid_targets = [t for t in valid_targets if not (t in seen or seen.add(t))]

        if not valid_targets:
            return {
                "error": f"Target 欄位 '{target_raw}' 未被索引或非數值型態。",
                "tip": "機器學習建模 (Feature Importance) 僅能針對「數值型特徵」進行分析。請避免選擇 CONTEXTID 或其他 ID/時間戳欄位作為分析目標。",
                "can_fallback": True,
            }

        # 限制最多 3 個目標以控制運算時間
        valid_targets = valid_targets[:3]

        # [Cache] Load once
        df_cache = self.analysis_service.get_dataframe(session_id, file_id)
        if df_cache is None:
            return {"error": "無法讀取數據文件"}

        # 對每個 target 執行分析
        multi_results = {}
        for target in valid_targets:
            result = self._run_single_target(
                target, correlations, df_cache, feature_list
            )
            multi_results[target] = result

        # 單一目標：維持原輸出格式
        if len(valid_targets) == 1:
            return multi_results[valid_targets[0]]

        # 多目標：匯整聯合影響力排名
        return self._aggregate_multi_target(valid_targets, multi_results)

    def _run_single_target(
        self, target: str, correlations: Dict, df_full: pd.DataFrame, feature_list
    ) -> Dict[str, Any]:
        """對單一 target 執行特徵重要性分析"""
        # 自動選擇 features
        local_features = feature_list
        if (
            not local_features
            or local_features == "all"
            or (
                isinstance(local_features, list)
                and len(local_features) == 1
                and local_features[0] == "all"
            )
        ):
            sorted_corrs = sorted(
                correlations[target].items(),
                key=lambda x: abs(x[1]) if x[1] is not None else 0,
                reverse=True,
            )
            local_features = [
                k for k, v in sorted_corrs if k != target and v is not None
            ][:40]

        try:
            cols_to_read = local_features + [target]
            # 去重
            cols_to_read = list(set(cols_to_read))

            # Use cached df_full
            # Filter columns
            valid_cols = [c for c in cols_to_read if c in df_full.columns]
            df_raw = df_full[valid_cols].select_dtypes(include=[np.number])
            if target not in df_raw.columns:
                return {"error": f"Target {target} not found in file."}

            # [Smart Filter] Apply intelligent reduction with target awareness
            df_filtered = _smart_feature_filter(df_raw, target_col=target, top_k=50)

            # 確保 target 還在
            if target not in df_filtered.columns:
                # Should not happen logic-wise but safe check
                return {"error": "Target was filtered out due to quality issues."}

            clean_features = [c for c in df_filtered.columns if c != target]

            if not clean_features:
                return {"error": f"排除低品質因子後無剩餘可用特徵 (target={target})。"}

            df = df_filtered.fillna(df_filtered.median(numeric_only=True))

            if len(df) < 10:
                return {"error": "數據樣本量嚴重不足(少於10筆)，無法進行機器學習建模。"}

            X = df[clean_features]
            y = df[target]

        except Exception as e:
            return {"error": f"數據讀取失敗: {str(e)}", "can_fallback": True}

        # 智慧演算法選擇
        sample_size = len(df)
        null_ratio = df.isnull().mean().mean()

        if sample_size < 100:
            model = LassoCV(cv=5)
            model_type = "Lasso Regression"
            reasoning = "數據樣本點較少 (<100)，選用 Lasso 回歸以防止過度擬合。"
        elif HAS_XGBOOST and (null_ratio > 0.05 or sample_size > 1000):
            model = xgb.XGBRegressor(
                n_estimators=100, learning_rate=0.1, max_depth=5, random_state=42
            )
            model_type = "XGBoost"
            reasoning = "數據量較大或存在顯著缺失值，選用 XGBoost。"
        else:
            model = RandomForestRegressor(n_estimators=100, random_state=42)
            model_type = "RandomForest"
            reasoning = "數據分佈較穩定且樣本量適中，選用隨機森林。"

        model.fit(X, y)

        if model_type == "Lasso Regression":
            importances = np.abs(model.coef_)
        else:
            importances = model.feature_importances_

        indices = np.argsort(importances)[::-1]

        results = []
        for i in range(min(15, len(clean_features))):
            idx = indices[i]
            param_name = clean_features[idx]
            importance = float(importances[idx])

            # --- [NEW] 角色分類邏輯 ---
            # 計算該特徵與目標的簡單相關係數，用於判斷方向性
            if param_name in correlations.get(target, {}):
                corr = correlations[target][param_name]
            else:
                # 如果緩存中沒有，嘗試現場計算 (fallback)
                try:
                    corr = df[param_name].corr(df[target])
                except Exception:
                    corr = 0

            corr = float(corr) if corr is not None else 0.0

            role = "Secondary Factor"
            if i < 5:  # 只對前 5 名做重要角色定義
                if corr > 0.4:
                    role = "🔥 Main Driver (+) [正向驅動]"
                elif corr < -0.4:
                    role = "❄️ Main Suppressor (-) [負向抑制/控制]"
                else:
                    role = "⚠️ Complex Factor [非線性/複雜關係]"

            results.append(
                {
                    "parameter": param_name,
                    "importance_score": importance,
                    "correlation": corr,
                    "role": role,
                    "rank": i + 1,
                }
            )

        top_3 = []
        for r in results[:3]:
            # 簡化顯示：只顯示參數名和角色
            role_icon = r["role"].split(" ")[0]  # 取出圖標
            top_3.append(f"{role_icon} {r['parameter']} (Corr: {r['correlation']:.2f})")

        top_3_summary = " | ".join(top_3)

        result_data = {
            "target": target,
            "model_used": model_type,
            "selection_reasoning": reasoning,
            "top_features": results,
            "top_3_summary": f"【{model_type} 貢獻度 Top 3】{top_3_summary}",
            "model_r2_score": float(model.score(X, y)),
            "conclusion": f"經 {model_type} 分析，影響 {target} 的最關鍵因素為 {results[0]['parameter']}。",
        }
        # [Compat] Add 'evidence' key
        result_data["evidence"] = result_data
        return result_data

    def _aggregate_multi_target(
        self, targets: list, multi_results: Dict[str, Dict]
    ) -> Dict[str, Any]:
        """匯整多目標分析結果，找出跨目標的共用關鍵因子"""
        # 收集每個成功分析的 target 的 top features
        all_importances = {}  # param -> [scores across targets]
        successful_targets = []

        for target in targets:
            res = multi_results[target]
            if "error" in res:
                continue
            successful_targets.append(target)
            for feat in res.get("top_features", []):
                param = feat["parameter"]
                if param not in all_importances:
                    all_importances[param] = []
                all_importances[param].append(feat["importance_score"])

        if not successful_targets:
            return {
                "error": "所有目標欄位的分析均失敗。",
                "details": multi_results,
            }

        # 計算聯合影響力：出現次數 * 平均重要性
        joint_ranking = []
        for param, scores in all_importances.items():
            joint_ranking.append(
                {
                    "parameter": param,
                    "avg_importance": float(np.mean(scores)),
                    "appears_in_n_targets": len(scores),
                    "joint_score": float(np.mean(scores) * len(scores)),
                }
            )

        joint_ranking.sort(key=lambda x: x["joint_score"], reverse=True)
        for i, item in enumerate(joint_ranking):
            item["rank"] = i + 1

        top_3 = [
            f"第{r['rank']}名: {r['parameter']} (聯合={r['joint_score']:.3f}, 出現={r['appears_in_n_targets']}個目標)"
            for r in joint_ranking[:3]
        ]

        result_data = {
            "analysis_type": "multi_target",
            "targets_analyzed": successful_targets,
            "per_target_results": multi_results,
            "joint_ranking": joint_ranking[:10],
            "top_3_summary": "【多目標聯合貢獻度 Top 3】" + " | ".join(top_3),
            "conclusion": (
                f"跨 {len(successful_targets)} 個目標 ({', '.join(successful_targets)}) 的聯合分析顯示，"
                f"最具影響力的共用因子為 {joint_ranking[0]['parameter']}。"
            ),
        }
        # [Compat] Add 'evidence' key
        result_data["evidence"] = result_data
        return result_data


class PrincipalComponentAnalysisTool(AnalysisTool):
    """系統性特徵降維與主成分分析 (PCA)"""

    @property
    def name(self) -> str:
        return "systemic_pca_analysis"

    @property
    def description(self) -> str:
        return "【深度診斷】執行主成分分析 (PCA)。支持 target_segments (例如 '30-50') 以分析特定區間。系統會自動處理多重共線性並識別設備的『系統性狀態與群聚效應』。"

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "parameters"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        param_list = params.get("parameters")
        target_segments_str = params.get("target_segments")

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

        # [Smart Filter] No forced truncation here.

        df_full = self.analysis_service.get_dataframe(session_id, file_id)
        if df_full is None:
            return {"error": "無法讀取數據文件"}

        try:
            # 系統診斷需自動排除非數值型欄位
            # Use intersection of requested params and available columns
            if isinstance(param_list, list) and "all" not in param_list:
                valid_cols = [c for c in param_list if c in df_full.columns]
                if not valid_cols:
                    return {"error": "指定的參數在數據中不存在"}
                df_full = df_full[valid_cols]

            df_full = df_full.select_dtypes(include=[np.number])

            # 區間過濾處理
            if target_segments_str:
                target_indices = self.parse_indices(
                    target_segments_str, max_len=len(df_full)
                )
                if target_indices:
                    df = df_full.iloc[target_indices].dropna()
                else:
                    df = df_full.dropna()
            else:
                df = df_full.dropna()

        except ValueError as e:
            return {"error": str(e)}
        if len(df) < 5:  # 調低最低筆數要求，因為區間可能較小
            return {"error": f"數據量不足以進行 PCA 分析 (目前有效筆數: {len(df)})。"}

        # 標準化
        scaler = StandardScaler()
        x_scaled = scaler.fit_transform(df)

        # PCA 轉換
        n_components = min(5, len(df.columns))
        pca = PCA(n_components=n_components)
        scores = pca.fit_transform(x_scaled)  # (n_samples, n_components)

        exp_var = pca.explained_variance_ratio_
        components = []

        # 使用過濾後的 column 名稱
        active_cols = df.columns.tolist()

        for i, ratio in enumerate(exp_var):
            # 找出對該主成分貢獻最大的前 3 個參數
            top_factors_idx = np.argsort(np.abs(pca.components_[i]))[::-1][:3]
            top_factors = [
                {
                    "parameter": active_cols[idx],
                    "weight": float(pca.components_[i][idx]),
                }
                for idx in top_factors_idx
            ]

            components.append(
                {
                    "component": f"PC{i + 1}",
                    "explained_variance": f"{ratio * 100:.2f}%",
                    "top_contributing_parameters": top_factors,
                }
            )

        # --- [NEW] 全域狀態分析 (Global State Analysis) ---
        # 計算每個樣本在 PC 空間的偏離度 (以 PC1-PC2 為主)
        # 這裡使用簡單的歐氏距離作為狀態偏離指標
        # (更嚴謹可用 Mahalanobis distance，但此處做快速掃描)
        pc_dist = np.linalg.norm(scores[:, :2], axis=1)  # 使用前兩個主成分
        dist_mean = np.mean(pc_dist)
        dist_std = np.std(pc_dist, ddof=1)  # [FIX] 統一 ddof=1

        threshold_anomaly = dist_mean + 3 * dist_std
        threshold_transition = dist_mean + 1.0 * dist_std

        # 1. 識別異常點
        anomaly_indices = np.where(pc_dist > threshold_anomaly)[0]

        # 2. 將異常點合併為區間
        anomaly_ranges = []
        if len(anomaly_indices) > 0:
            current_start = anomaly_indices[0]
            current_end = anomaly_indices[0]

            for i in range(1, len(anomaly_indices)):
                if anomaly_indices[i] == current_end + 1:
                    current_end = anomaly_indices[i]
                else:
                    anomaly_ranges.append((current_start, current_end))
                    current_start = anomaly_indices[i]
                    current_end = anomaly_indices[i]
            anomaly_ranges.append((current_start, current_end))

        # 3. 識別過渡區 (Transition Zones)
        # 在主要異常區間結束後的 20 筆內，如果偏離度仍高於 transition 閾值
        transition_zones = []
        for start, end in anomaly_ranges:
            # 這是連續異常區段（大於 3 筆才算主要區段）
            if end - start >= 2:
                # 檢查後續
                check_start = end + 1
                check_end = min(len(pc_dist), check_start + 20)

                t_zone_end = end
                for i in range(check_start, check_end):
                    if pc_dist[i] > threshold_transition:
                        t_zone_end = i
                    else:
                        break  # 一旦回復正常就停止

                if t_zone_end > end:
                    transition_zones.append(
                        f"第 {end + 1}-{t_zone_end} 筆 (過渡震盪區)"
                    )

        # 4. 格式化異常區間報告
        anomaly_report = []
        primary_anomaly = None
        secondary_anomalies = []

        for start, end in anomaly_ranges:
            length = end - start + 1
            if length >= 5:  # 長區段
                range_str = f"第 {start}-{end} 筆 (持續 {length} 筆)"
                anomaly_report.append(f"🔴 主要異常群: {range_str}")
                if not primary_anomaly:
                    primary_anomaly = range_str
            else:  # 短區段或單點
                if start == end:
                    secondary_anomalies.append(str(start))
                else:
                    secondary_anomalies.append(f"{start}-{end}")

        if secondary_anomalies:
            anomaly_report.append(
                f"⚠️ 次要/隱性異常: {', '.join(secondary_anomalies[:10])}"
            )

        if transition_zones:
            anomaly_report.append(f"🌊 狀態過渡/餘震區: {', '.join(transition_zones)}")

        # --- 構建增強版結論 ---
        total_explained = sum(exp_var)
        range_suffix = (
            f" (在區間 {target_segments_str} 內)" if target_segments_str else ""
        )

        state_analysis_text = ""
        if anomaly_report:
            state_analysis_text = " ｜ ".join(anomaly_report)
        else:
            state_analysis_text = "系統狀態穩定，未發現顯著的分群現象。"

        result_data = {
            "total_explained_variance": f"{total_explained * 100:.2f}%",
            "components": components,
            "target_range": target_segments_str or "Full data",
            "sample_count": len(df),
            "state_analysis": {
                "clusters": anomaly_report,
                "primary_anomaly": primary_anomaly,
                "transition_zones": transition_zones,
                "secondary_anomalies": secondary_anomalies,
            },
            # --- [NEW] PCA 偏離度趨勢圖數據 ---
            "pc_distance_trend": [round(float(v), 4) for v in pc_dist],
            "pc_anomaly_threshold": round(float(threshold_anomaly), 4),
            "conclusion": (
                f"PCA 分析顯示數據解釋力為 {total_explained * 100:.2f}%{range_suffix}。"
                f"【系統狀態診斷】：{state_analysis_text}。"
                f"主成分 PC1 由 {components[0]['top_contributing_parameters'][0]['parameter']} 主導。"
            ),
        }
        # [Compat] Add 'evidence' key for Orchestrator compatibility
        result_data["evidence"] = result_data
        return result_data


class HotellingT2AnalysisTool(AnalysisTool):
    """PCA-based Hotelling's T2 多維度異常診斷與貢獻度分析"""

    @property
    def name(self) -> str:
        return "hotelling_t2_analysis"

    @property
    def description(self) -> str:
        return "【核心診斷】PCA-Hotelling's T2 診斷組合異常。支援 target_segments (例如 '30-50') 鎖定異常區間。建議 parameters 設為 'all' 以啟動自動化全場掃描。"

    @property
    def required_params(self) -> List[str]:
        return ["file_id"]

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

        # [Smart Filter] No forced truncation        # [Cache] Use get_dataframe
        df_full = self.analysis_service.get_dataframe(session_id, file_id)
        if df_full is None:
            return {"error": "無法讀取數據文件"}

        try:
            # [Robustness] Filter out non-numeric columns explicitly
            numeric_cols = df_full.select_dtypes(include=[np.number]).columns.tolist()
            if not numeric_cols:
                return {"error": "No numeric columns found for Hotelling T2 analysis."}
            df_full = df_full[numeric_cols]

            # [Robustness] Replace Infinite with NaN then Impute
            df_full.replace([np.inf, -np.inf], np.nan, inplace=True)

            # Hotelling needs all numeric columns usually
            df_numeric = df_full.select_dtypes(include=[np.number])

            # For Hotelling, usually we analyze ALL numeric columns
            if (
                not param_list
                or param_list == "all"
                or (isinstance(param_list, list) and "all" in param_list)
            ):
                df_selected = df_numeric
            else:
                valid_cols = [c for c in param_list if c in df_numeric.columns]
                df_selected = df_numeric[valid_cols]

            # [Smart Filter] Apply intelligent reduction
            # Hotelling needs variance, so variance-based filtering is perfect
            df_full = _smart_feature_filter(df_selected, top_k=50)

        except ValueError as e:
            return {"error": str(e)}

        # Target Segments Parsing (優先度：row_index > target_segments)
        if target_idx_val is not None:
            target_indices = self.parse_indices(target_idx_val, max_len=len(df_full))
        else:
            target_indices = self.parse_indices(
                target_segments_str, max_len=len(df_full)
            )

        # 智慧過濾：如果欄位空值比例過高 (例如 > 50%)，直接剔除，不進入計算
        null_ratios = df_full.isnull().mean()
        valid_cols = null_ratios[null_ratios <= 0.5].index.tolist()
        df_filtered = df_full[valid_cols]

        # 智慧填補：對剩餘的少量缺失值進行中位數填補
        df_imputed = df_filtered.fillna(df_filtered.median(numeric_only=True))

        # 剔除定值欄位 (變異數為 0)
        # Check standard deviation and drop columns with zero variance
        # (This is already covered by _smart_feature_filter but extra check is fine)
        cols_std = df_imputed.std()
        keep_cols = cols_std[cols_std > 0].index.tolist()
        df_imputed = df_imputed[keep_cols]

        active_params = df_imputed.columns.tolist()

        # --- 健壯性增強：如果 AI 傳入參數太少，自動補齊數據中前 5 個有變異的數值欄位作為背景 ---
        if len(active_params) < 2:
            # Re-read full numerical columns if insufficient params
            # But wait, df_full might already be filtered.
            # If so, we can't easily fetch more without re-reading.
            # But since we use _smart_feature_filter(top_k=50), we should have enough if available.
            # If still < 2, maybe the dataset itself is bad.
            try:
                # Fallback: get ALL numerical columns (without truncation) and pick top 5 variance
                all_numeric_cols = summary.get("numerical_columns", [])
                if not all_numeric_cols:
                    all_numeric_cols = summary.get("parameters", [])  # fallback

                # [Cache] Use get_dataframe for fallback
                df_cache = self.analysis_service.get_dataframe(session_id, file_id)
                if df_cache is not None:
                    # Filter for numeric cols
                    valid_cols = [c for c in all_numeric_cols if c in df_cache.columns]
                    df_fallback = df_cache[valid_cols].select_dtypes(
                        include=[np.number]
                    )
                else:
                    df_fallback = pd.DataFrame()
                fallback_stds = df_fallback.std().sort_values(ascending=False)
                top_5_vars = fallback_stds.head(5).index.tolist()

                for p in top_5_vars:
                    if p not in active_params:
                        active_params.append(p)

                # Re-construct dataframe with added params
                df_imputed = df_fallback[active_params].fillna(
                    df_fallback[active_params].median(numeric_only=True)
                )

            except Exception:
                pass  # If fallback fails, just proceed and fail naturally

        if len(df_imputed) < 3:
            return {
                "error": f"數據筆數過少 (僅 {len(df_imputed)} 筆)，無法建立統計模型。"
            }
        if len(active_params) < 1:
            return {
                "error": "找不到任何具備數值變異的有效參數。請檢查數據是否全為定值或空值。"
            }

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

        # --- [NEW] 異常區間分群 (Anomaly Clustering) ---
        # 計算異常閾值 (Dynamic: Chi-Square or Fallback)
        # Hotelling T2 follows Chi-Square distribution with df = n_components
        try:
            # 1. 統計學閾值 (Strict): 99% Confidence Interval
            threshold_anomaly = stats.chi2.ppf(0.99, df=n_comp)
        except Exception:
            # Fallback if calculation fails
            threshold_anomaly = np.mean(t2_values) + 3 * np.std(
                t2_values, ddof=1
            )  # [FIX] 統一 ddof=1

        # 1. 識別異常點 (Strict)
        anomaly_indices = np.where(t2_values > threshold_anomaly)[0]

        # [Fallback Mechanism]
        # 如果嚴格閾值找到的異常點太少 (<3% 的數據)，
        # 退而求其次，抓取 T2 分數最高的 5% 作為 "相對異常"
        is_fallback_mode = False
        anomaly_ratio = (
            len(anomaly_indices) / len(t2_values) if len(t2_values) > 0 else 0
        )
        if anomaly_ratio < 0.03:
            is_fallback_mode = True
            # Fallback to Top 5%
            threshold_anomaly = np.percentile(t2_values, 95)
            anomaly_indices = np.where(t2_values > threshold_anomaly)[0]

        # 2. 將異常點合併為區間 (容許 gap <= 5 的間隔)
        anomaly_ranges = []
        if len(anomaly_indices) > 0:
            current_start = anomaly_indices[0]
            current_end = anomaly_indices[0]

            for i in range(1, len(anomaly_indices)):
                if anomaly_indices[i] <= current_end + 6:  # gap <= 5
                    current_end = anomaly_indices[i]
                else:
                    anomaly_ranges.append((current_start, current_end))
                    current_start = anomaly_indices[i]
                    current_end = anomaly_indices[i]
            anomaly_ranges.append((current_start, current_end))

        # 3. 構建結構化異常區段 (anomaly_zones)
        anomaly_report = []
        anomaly_zones = []
        primary_anomaly_range = None
        primary_anomaly_text = None

        for start, end in anomaly_ranges:
            length = end - start + 1
            # 超過閾值的點/區段都保留 (含單點突波)
            if length >= 1:
                range_str = f"第 {start}-{end} 筆 (持續 {length} 筆)"
                anomaly_report.append(range_str)
                if not primary_anomaly_range:
                    primary_anomaly_range = (int(start), int(end))
                    primary_anomaly_text = range_str

                # --- 每個 zone 獨立計算 top contributions ---
                zone_indices = list(range(int(start), int(end) + 1))
                zone_t2_mean = float(np.mean(t2_values[zone_indices]))
                zone_t2_max = float(np.max(t2_values[zone_indices]))

                zone_scores = scores[zone_indices]
                zone_scaled = data_scaled[zone_indices]
                zone_weights = zone_scores / eigenvalues
                zone_cont_matrix = np.matmul(zone_weights, loadings) * zone_scaled
                zone_avg_cont = np.mean(zone_cont_matrix, axis=0)

                zone_contributions = []
                for j in range(len(active_params)):
                    zone_contributions.append(
                        {
                            "parameter": active_params[j],
                            "contribution": float(zone_avg_cont[j]),
                        }
                    )
                zone_contributions.sort(
                    key=lambda x: abs(x["contribution"]), reverse=True
                )

                anomaly_zones.append(
                    {
                        "zone_range": f"Row {start}-{end}",
                        "zone_start": int(start),
                        "zone_end": int(end),
                        "length": length,
                        "t2_mean": round(zone_t2_mean, 2),
                        "t2_max": round(zone_t2_max, 2),
                        "top_contributors": [
                            {
                                "parameter": c["parameter"],
                                "contribution": round(c["contribution"], 4),
                                "rank": i + 1,
                            }
                            for i, c in enumerate(zone_contributions[:6])
                        ],
                        "is_fallback": is_fallback_mode,
                    }
                )

        # --- 過大 zone 拆分: 覆蓋 >50% 時用 T2 75th percentile 做二次切割 ---
        total_data = len(t2_values)
        if anomaly_zones:
            refined_zones = []
            for az in anomaly_zones:
                coverage = az["length"] / total_data if total_data > 0 else 0
                if coverage > 0.5:
                    z_start, z_end = az["zone_start"], az["zone_end"]
                    zone_t2 = t2_values[z_start : z_end + 1]
                    secondary_threshold = float(np.percentile(zone_t2, 75))

                    above = np.where(zone_t2 > secondary_threshold)[0]
                    if len(above) > 0:
                        sub_ranges = []
                        s_start = above[0]
                        s_end = above[0]
                        for k in range(1, len(above)):
                            if above[k] <= s_end + 3:  # 容許 gap <= 2
                                s_end = above[k]
                            else:
                                sub_ranges.append((s_start, s_end))
                                s_start = above[k]
                                s_end = above[k]
                        sub_ranges.append((s_start, s_end))

                        for sr_s, sr_e in sub_ranges:
                            abs_start = z_start + int(sr_s)
                            abs_end = z_start + int(sr_e)
                            sr_len = abs_end - abs_start + 1
                            if sr_len >= 3:
                                sr_indices = list(range(abs_start, abs_end + 1))
                                sr_t2_mean = float(np.mean(t2_values[sr_indices]))
                                sr_t2_max = float(np.max(t2_values[sr_indices]))

                                sr_scores = scores[sr_indices]
                                sr_scaled = data_scaled[sr_indices]
                                sr_weights = sr_scores / eigenvalues
                                sr_cont_matrix = (
                                    np.matmul(sr_weights, loadings) * sr_scaled
                                )
                                sr_avg_cont = np.mean(sr_cont_matrix, axis=0)

                                sr_contributions = [
                                    {
                                        "parameter": active_params[j],
                                        "contribution": float(sr_avg_cont[j]),
                                    }
                                    for j in range(len(active_params))
                                ]
                                sr_contributions.sort(
                                    key=lambda x: abs(x["contribution"]), reverse=True
                                )

                                refined_zones.append(
                                    {
                                        "zone_range": f"Row {abs_start}-{abs_end}",
                                        "zone_start": abs_start,
                                        "zone_end": abs_end,
                                        "length": sr_len,
                                        "t2_mean": round(sr_t2_mean, 2),
                                        "t2_max": round(sr_t2_max, 2),
                                        "top_contributors": [
                                            {
                                                "parameter": c["parameter"],
                                                "contribution": round(
                                                    c["contribution"], 4
                                                ),
                                                "rank": i + 1,
                                            }
                                            for i, c in enumerate(sr_contributions[:6])
                                        ],
                                        "is_fallback": az.get("is_fallback", False),
                                        "is_refined": True,
                                    }
                                )
                    if not refined_zones:
                        refined_zones.append(az)
                else:
                    refined_zones.append(az)
            anomaly_zones = refined_zones

        # 5. 貢獻度分析 (Decomposition to original variables)
        # 決定要診斷的範圍或數據
        is_range_mode = False
        if target_indices and len(target_indices) > 1:
            is_range_mode = True
            selected_indices = target_indices
            # 找出區間內最顯著的一點作為參考索引
            sub_t2 = t2_values[target_indices]
            diag_idx = target_indices[np.argmax(sub_t2)]
            summary_range_text = f"第 {min(target_indices)}-{max(target_indices)} 筆區間 (共 {len(target_indices)} 筆)"
        else:
            # 單點模式
            if target_indices:
                diag_idx = target_indices[0]
            else:
                diag_idx = np.argmax(t2_values)
            selected_indices = [diag_idx]
            summary_range_text = f"第 {diag_idx} 筆數據"

        if diag_idx >= len(t2_values):
            diag_idx = np.argmax(t2_values)

        # 計算貢獻度 (向量化處理以應對區間分析)
        # scores: (N, n_comp), eigenvalues: (n_comp,), loadings: (n_comp, n_features), data_scaled: (N, n_features)
        target_scores = scores[selected_indices]
        target_scaled = data_scaled[selected_indices]

        # 樣本在主成分上的權重: score / eigenvalue
        weights = target_scores / eigenvalues  # (K, n_comp)

        # 映射回原始空間並加權原始偏差: (weights @ loadings) * samples_scaled
        # 此矩陣大小為 (K, n_features)，代表每一筆樣本在各欄位上的貢獻
        cont_matrix = np.matmul(weights, loadings) * target_scaled

        # 方案 C：取區間內所有樣本貢獻度的平均值
        avg_cont = np.mean(cont_matrix, axis=0)

        contributions = []
        for j in range(len(active_params)):
            contributions.append(
                {
                    "parameter": active_params[j],
                    "contribution": float(avg_cont[j]),
                    "rank": 0,
                }
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

        # 構建結論
        if is_range_mode:
            display_title = "【PCA-T2 區間平均貢獻度 Top 3】"
        else:
            display_title = f"【PCA-T2 單點貢獻度 Top 3 (Index: {diag_idx})】"

        # 計算 Top 10 異常筆數
        t2_sorted_indices = np.argsort(t2_values)[::-1]  # 降序排列
        top_10_anomalies = []
        for i in range(min(10, len(t2_sorted_indices))):
            idx = t2_sorted_indices[i]
            top_10_anomalies.append(
                {"index": int(idx), "t2_score": float(t2_values[idx]), "rank": i + 1}
            )

        # 構建增強版結論
        if primary_anomaly_text:
            cluster_msg = f"偵測到顯著異常區間：{primary_anomaly_text}"
            if is_fallback_mode:
                cluster_msg += " (基於相對排序 Top 3%)"
            else:
                cluster_msg += " (統計顯著性 > 99%)"
        else:
            cluster_msg = "異常點較分散，無顯著連續區間"

        if is_range_mode:
            final_conclusion = (
                f"經 PCA-T2 區間診斷 ({summary_range_text})，"
                f"主導異常的核心參數為【{contributions[0]['parameter']}】(貢獻度 {contributions[0]['contribution']:.2f})。"
                f" {cluster_msg}。"
            )
        else:
            final_conclusion = (
                f"經 PCA-T2 單點診斷 (Row {diag_idx})，"
                f"主導異常的核心參數為【{contributions[0]['parameter']}】(貢獻度 {contributions[0]['contribution']:.2f})。"
                f" {cluster_msg}。"
            )

        result_data = {
            "method": "PCA-Hotelling T2",
            "n_components_used": n_comp,
            "variance_explained": f"{np.sum(pca.explained_variance_ratio_) * 100:.2f}%",
            "is_range_analysis": is_range_mode,
            "diagnosed_index": int(diag_idx),
            "primary_anomaly_range": primary_anomaly_range,
            "anomaly_clusters_text": anomaly_report,
            "max_t2_value": float(t2_values[diag_idx]),
            "top_contributions": contributions[:15],
            "top_3_summary": display_title + " | ".join(top_3),
            "top_10_anomalies": top_10_anomalies,
            # --- [NEW] T2 趨勢圖數據 + 結構化異常區段 ---
            "t2_trend": [round(float(v), 4) for v in t2_values],
            "t2_threshold": round(float(threshold_anomaly), 4),
            "anomaly_zones": anomaly_zones,
            "conclusion": final_conclusion,
            "top_suspect_parameter": contributions[0]["parameter"],
        }

        # [Compat] Add 'evidence' key for Orchestrator compatibility
        result_data["evidence"] = result_data
        return result_data
