import numpy as np
import pandas as pd
from scipy import stats
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler
from typing import Dict, Any, List
from .base import AnalysisTool
import logging

logger = logging.getLogger(__name__)


class DistributionShiftTool(AnalysisTool):
    """分佈差異檢定 (K-S Test & F-Test)"""

    @property
    def name(self) -> str:
        return "distribution_shift_test"

    @property
    def description(self) -> str:
        return "深度診斷：使用 K-S 檢定與 F 檢定對比異常區間與正常基準的『分佈形狀』與『穩定度』差異。"

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "target_segments"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        target_input = params.get("target_segments")
        baseline_input = params.get("baseline_segments")
        parameters = params.get("parameters")

        summary = self.analysis_service.load_summary(session_id, file_id)
        csv_path = (
            self.analysis_service.base_dir
            / session_id
            / "uploads"
            / summary["filename"]
        )
        df = pd.read_csv(csv_path)

        # 簡單解析邏輯
        def parse(data):
            idx = set()
            if isinstance(data, list):
                for i in data:
                    idx.add(int(i))
            elif isinstance(data, str):
                for p in data.split(","):
                    p = p.strip()
                    if not p:
                        continue
                    if "-" in p:
                        try:
                            s, e = map(int, p.split("-"))
                            idx.update(range(s, e + 1))
                        except:
                            pass
                    else:
                        try:
                            idx.add(int(p))
                        except:
                            pass
            return list(idx)

        t_idx = parse(target_input)
        if baseline_input:
            b_idx = parse(baseline_input)
        else:
            b_idx = [i for i in range(len(df)) if i not in t_idx]

        if not parameters:
            parameters = df.select_dtypes(include=[np.number]).columns.tolist()
        elif isinstance(parameters, str):
            parameters = [p.strip() for p in parameters.split(",")]

        results = []
        for col in parameters:
            if col not in df.columns:
                continue
            try:
                t_data = df.iloc[t_idx][col].dropna()
                b_data = df.iloc[b_idx][col].dropna()

                if len(t_data) < 3 or len(b_data) < 3:
                    continue

                # 1. K-S Test
                ks_stat, ks_p = stats.ks_2samp(t_data, b_data)

                # 2. F-Test
                var_t = np.var(t_data)
                var_b = np.var(b_data)
                f_stat = var_t / var_b if var_b != 0 else 0

                df1, df2 = len(t_data) - 1, len(b_data) - 1
                p_val = stats.f.cdf(f_stat, df1, df2) if f_stat > 0 else 1.0
                f_p = 2 * min(p_val, 1 - p_val)

                # 3. 判定顯著性
                is_dist_shifted = ks_p < 0.05
                is_variance_changed = f_p < 0.05

                if is_dist_shifted or is_variance_changed:
                    results.append(
                        {
                            "parameter": col,
                            "ks_p_value": float(ks_p),
                            "f_p_value": float(f_p),
                            "is_dist_shifted": bool(is_dist_shifted),
                            "is_stability_changed": bool(is_variance_changed),
                            "severity": 1 - min(ks_p, f_p),
                        }
                    )
            except:
                continue

        results = sorted(results, key=lambda x: x["severity"], reverse=True)

        if not results:
            return {"method": "K-S & F Test", "conclusion": "未偵測到顯著的分佈偏離。"}

        return {
            "method": "K-S & F Test",
            "findings": results[:10],
            "conclusion": f"分佈檢定顯示，有 {len(results)} 個參數發生了顯著統計特性改變。最顯著的是 {results[0]['parameter']}。",
        }


class LocalOutlierFactorTool(AnalysisTool):
    """局部離群因子分析 (LOF)"""

    @property
    def name(self) -> str:
        return "local_outlier_factor_analysis"

    @property
    def description(self) -> str:
        return "深度診斷：偵測局部組合異常。找出那些『單看數值正常，但與鄰居規律不合』的邏輯異常點。"

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "parameters"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        param_list = params.get("parameters")
        if isinstance(param_list, str):
            param_list = [p.strip() for p in param_list.split(",")]

        summary = self.analysis_service.load_summary(session_id, file_id)
        csv_path = (
            self.analysis_service.base_dir
            / session_id
            / "uploads"
            / summary["filename"]
        )
        df = pd.read_csv(csv_path, usecols=param_list).dropna()

        if len(df) < 50:
            return {"error": "數據量不足以進行 LOF 鄰域分析。"}

        scaler = StandardScaler()
        data_scaled = scaler.fit_transform(df)

        lof = LocalOutlierFactor(n_neighbors=20, contamination="auto")
        preds = lof.fit_predict(data_scaled)
        negative_outlier_factor = -lof.negative_outlier_factor_

        max_idx = np.argmax(negative_outlier_factor)

        return {
            "method": "Local Outlier Factor (LOF)",
            "max_lof_score": float(negative_outlier_factor[max_idx]),
            "max_lof_index": int(max_idx),
            "anomaly_indices": np.where(preds == -1)[0].tolist()[:10],
            "conclusion": f"LOF 分析顯示，第 {max_idx} 筆數據最不符合局部規律，LOF 分數為 {negative_outlier_factor[max_idx]:.2f}。",
        }


class CausalRelationshipTool(AnalysisTool):
    """因果與關聯打破偵測 (Granger Causality)"""

    @property
    def name(self) -> str:
        return "causal_relationship_analysis"

    @property
    def description(self) -> str:
        return "深度診斷：分析參數間的因果先行關係，協助判斷『誰是起因，誰是受害者』。"

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "target_parameter", "reference_parameters"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        target = params.get("target_parameter")
        refs = params.get("reference_parameters")
        if isinstance(refs, str):
            refs = [r.strip() for r in refs.split(",")]

        summary = self.analysis_service.load_summary(session_id, file_id)
        csv_path = (
            self.analysis_service.base_dir
            / session_id
            / "uploads"
            / summary["filename"]
        )
        df = pd.read_csv(csv_path, usecols=[target] + refs).dropna()

        try:
            from statsmodels.tsa.stattools import grangercausalitytests
        except ImportError:
            return {"error": "環境未安裝 statsmodels，無法執行因果檢定。"}

        causal_results = []
        for ref in refs:
            if ref == target:
                continue
            try:
                test_result = grangercausalitytests(
                    df[[target, ref]], maxlag=3, verbose=False
                )
                min_p = 1.0
                for lag in test_result:
                    p = test_result[lag][0]["ssr_ftest"][1]
                    if p < min_p:
                        min_p = p

                causal_results.append(
                    {
                        "cause": ref,
                        "effect": target,
                        "p_value": float(min_p),
                        "is_causal": min_p < 0.05,
                    }
                )
            except:
                continue

        causal_results = sorted(causal_results, key=lambda x: x["p_value"])

        if not causal_results:
            return {
                "method": "Granger Causality",
                "conclusion": "未偵測到顯著的先行因果關係。",
            }

        return {
            "method": "Granger Causality",
            "findings": causal_results[:5],
            "conclusion": f"因果分析顯示，{causal_results[0]['cause']} 對 {target} 具有顯著影響 (p={causal_results[0]['p_value']:.4f})。",
        }
