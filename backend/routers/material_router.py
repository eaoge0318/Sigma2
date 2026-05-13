"""
Material Analysis Router - /api/material
從 System_TEST/material_api.py (Flask) 移植到 FastAPI。
保留原有回應 JSON 結構，前端不需修改。
"""

import math
import re
import traceback
import logging
from typing import Any

import numpy as np
from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

router = APIRouter(tags=["Material - 原料分析"])
logger = logging.getLogger(__name__)


# ── JavaScript parseFloat 風格的鬆散數值解析（與前端顯示對齊）─────────────
# 例：'727.0 拋光' → 727.0、'5-A' → 5、'abc' → NaN
_NUM_RE = re.compile(r'^\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)')

def _js_parsefloat(v: Any) -> float:
    if v is None:
        return float('nan')
    if isinstance(v, (int, float)):
        try:
            return float('nan') if (isinstance(v, float) and math.isnan(v)) else float(v)
        except Exception:
            return float('nan')
    s = str(v).strip()
    if not s or s == '—':
        return float('nan')
    try:
        return float(s)
    except ValueError:
        pass
    m = _NUM_RE.match(s)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            pass
    return float('nan')


def _err(detail: str, status: int = 400) -> JSONResponse:
    """回傳與 Flask 版相同的 {"error": "..."} 結構"""
    return JSONResponse(content={"error": detail}, status_code=status)


# ── ALE computation ──────────────────────────────────────────────────────
def _compute_ale(model, X_df, factor, feature_names, algorithm, n_bins=30):
    x = X_df[factor].values
    quantiles = np.unique(np.percentile(x, np.linspace(0, 100, n_bins + 1)))
    if len(quantiles) < 2:
        return [], []

    effects, centers = [], []
    for i in range(len(quantiles) - 1):
        lo, hi = quantiles[i], quantiles[i + 1]
        mask = (x >= lo) & (x <= hi)
        if mask.sum() == 0:
            continue
        X_lo = X_df[mask].copy(); X_lo[factor] = lo
        X_hi = X_df[mask].copy(); X_hi[factor] = hi
        if algorithm == 'pls':
            p_lo = model.predict(X_lo[feature_names].values).flatten()
            p_hi = model.predict(X_hi[feature_names].values).flatten()
        else:
            p_lo = model.predict(X_lo[feature_names].values)
            p_hi = model.predict(X_hi[feature_names].values)
        effects.append(float((p_hi - p_lo).mean()))
        centers.append(float((lo + hi) / 2))

    if not effects:
        return [], []
    ale = np.cumsum(effects)
    ale -= ale.mean()
    return [round(c, 4) for c in centers], [round(float(a), 6) for a in ale]


# ── PDP computation ──────────────────────────────────────────────────────
def _compute_pdp(model, X_df, factor, feature_names, algorithm, n_points=30):
    x = X_df[factor].values
    grid = np.linspace(x.min(), x.max(), n_points)
    vals = []
    for val in grid:
        Xc = X_df.copy(); Xc[factor] = val
        if algorithm == 'pls':
            pred = model.predict(Xc[feature_names].values).flatten()
        else:
            pred = model.predict(Xc[feature_names].values)
        vals.append(float(pred.mean()))
    return [round(float(g), 4) for g in grid], [round(v, 6) for v in vals]


# ── 主效應圖分析 ─────────────────────────────────────────────────────────
@router.post('/maineffect')
async def material_maineffect(body: dict = Body(default={})):
    try:
        import pandas as pd
        from sklearn.ensemble import GradientBoostingRegressor
        from sklearn.cross_decomposition import PLSRegression
        from sklearn.metrics import r2_score

        rows            = body.get('rows', [])
        y_targets       = body.get('y_targets', [])
        control_factors = body.get('control_factors', [])
        bg_factors      = body.get('bg_factors', [])
        algorithm       = body.get('algorithm', 'gbm')
        method          = body.get('analysis_method', 'ale')
        hp              = body.get('hyperparams', {})

        if not rows or not y_targets or not control_factors:
            return _err('缺少必要參數（rows / y_targets / control_factors）')

        df = pd.DataFrame(rows)
        y_col_names      = [t['col'] for t in y_targets]
        all_feature_cols = list(dict.fromkeys(control_factors + bg_factors))

        for c in all_feature_cols + y_col_names:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce')

        usable = [c for c in all_feature_cols
                  if c in df.columns and pd.api.types.is_numeric_dtype(df[c])
                  and df[c].notna().sum() >= 3]

        usable_ctrl = [c for c in control_factors if c in usable]

        if not usable_ctrl:
            return _err('控制參數中找不到有效的數值欄位，請確認資料格式。')

        valid_mask = df[usable + y_col_names].notna().all(axis=1)
        train_df   = df[valid_mask].copy().reset_index(drop=True)

        if len(train_df) < 5:
            return _err(f'有效訓練資料不足（{len(train_df)} 筆），至少需要 5 筆。')

        X_train = train_df[usable].values

        n_est  = int(hp.get('n_estimators', 100))
        depth  = int(hp.get('max_depth', 4))
        lr     = float(hp.get('learning_rate', 0.1))
        ss     = float(hp.get('subsample', 0.8))
        n_comp = int(hp.get('n_components', 3))

        col_stats = {}
        for c in usable_ctrl:
            vals = pd.to_numeric(df[c], errors='coerce').dropna().values
            if len(vals):
                col_stats[c] = {
                    'min': round(float(vals.min()), 4),
                    'max': round(float(vals.max()), 4),
                    'mean': round(float(vals.mean()), 4),
                    'std':  round(float(vals.std()),  4),
                    'n_valid': int(len(vals))
                }

        target_stats = {}
        for c in y_col_names:
            vals = pd.to_numeric(df[c], errors='coerce').dropna().values
            if len(vals):
                target_stats[c] = {
                    'min': round(float(vals.min()), 4),
                    'max': round(float(vals.max()), 4),
                    'mean': round(float(vals.mean()), 4),
                    'std':  round(float(vals.std()),  4),
                    'n_valid': int(len(vals))
                }

        models_info = []
        factor_effects = {f: [] for f in usable_ctrl}
        total_weight   = sum(float(t.get('weight', 1.0)) for t in y_targets)

        for yt in y_targets:
            col    = yt['col']
            weight = float(yt.get('weight', 1.0))
            y_train = train_df[col].values

            if algorithm == 'pls':
                nc    = min(n_comp, len(usable), len(y_train) - 1)
                model = PLSRegression(n_components=max(nc, 1))
                model.fit(X_train, y_train)
                y_pred = model.predict(X_train).flatten()
            else:
                model = GradientBoostingRegressor(
                    n_estimators=n_est, max_depth=depth,
                    learning_rate=lr, subsample=ss, random_state=42
                )
                model.fit(X_train, y_train)
                y_pred = model.predict(X_train)

            r2 = float(r2_score(y_train, y_pred))
            models_info.append({'target': col, 'r2': round(r2, 4)})

            X_df_tr = train_df[usable].reset_index(drop=True)
            for factor in usable_ctrl:
                if method == 'pdp':
                    grid, vals = _compute_pdp(model, X_df_tr, factor, usable, algorithm)
                else:
                    grid, vals = _compute_ale(model, X_df_tr, factor, usable, algorithm)

                amp = (max(vals) - min(vals)) if vals else 0.0
                factor_effects[factor].append({
                    'target':    col,
                    'grid':      grid,
                    'values':    vals,
                    'amplitude': amp,
                    'weight':    weight
                })

        results = []
        for factor, effects in factor_effects.items():
            if not effects:
                continue
            wscore = sum(e['amplitude'] * e['weight'] for e in effects) / max(total_weight, 1)
            results.append({
                'factor':         factor,
                'weighted_score': round(float(wscore), 6),
                'effects':        effects
            })
        results.sort(key=lambda x: x['weighted_score'], reverse=True)

        return {
            'ok':              True,
            'n_train':         len(train_df),
            'algorithm':       algorithm,
            'analysis_method': method,
            'models':          models_info,
            'results':         results,
            'col_stats':       col_stats,
            'target_stats':    target_stats
        }

    except Exception as e:
        traceback.print_exc()
        return _err(str(e), status=500)


# ── 階段 1：欄位盤點 + 關聯初篩 ──────────────────────────────────────────
@router.post('/stage1')
async def material_stage1(body: dict = Body(default={})):
    def _s(v, n=4):
        """NaN/Inf-safe round → JSON-safe (None instead of NaN)."""
        if v is None:
            return None
        try:
            fv = float(v)
            if math.isnan(fv) or math.isinf(fv):
                return None
            return round(fv, n)
        except (TypeError, ValueError):
            return None
    try:
        import pandas as pd

        rows         = body.get('rows', [])
        y_target     = body.get('y_target', '')
        user_col_types = body.get('user_col_types', {}) or {}   # 由 STEP 01 欄位分類傳入

        if not rows or not y_target:
            return _err('缺少 rows 或 y_target')

        df = pd.DataFrame(rows)
        if y_target not in df.columns:
            return _err(f'欄位 {y_target} 不存在')

        for c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')

        y_mask = df[y_target].notna()
        n_y    = int(y_mask.sum())
        if n_y < 3:
            return _err(f'Y「{y_target}」有效資料僅 {n_y} 筆，至少需要 3 筆。')

        ydf    = df[y_mask].copy().reset_index(drop=True)
        y_vals = ydf[y_target]
        y_mean = float(y_vals.mean()); y_std = float(y_vals.std()) if n_y > 1 else 0.0
        y_min  = float(y_vals.min());  y_max = float(y_vals.max())
        y_med  = float(y_vals.median())

        high_mask = y_vals >= y_med
        low_mask  = y_vals <  y_med
        full_mask = y_vals >= (y_max - 1e-9)
        n_full    = int(full_mask.sum())

        META_KEYS = ['編號', 'no.', '案件', '型號', '原膜', '膜厚', '表面', 'recipe000']
        _ROLE_LABEL = {'X': 'X', 'Y': 'Y', 'meta': 'Meta', 'ignore': 'Ignore'}
        def detect_type(col):
            # 優先使用使用者在 STEP 01 設定的角色
            role = user_col_types.get(col)
            if role in _ROLE_LABEL:
                return _ROLE_LABEL[role]
            # Fallback：英文檔名 pattern
            c = col.lower()
            if 'solute'    in c: return 'Solute'
            if 'solv'      in c: return 'Solv'
            if 'condition' in c: return 'Condition'
            if 'power'     in c: return 'Power'
            if 'recipe'    in c: return 'Recipe'
            if any(k in c for k in META_KEYS): return 'Meta'
            return 'Other'

        results = []
        for col in df.columns:
            if col == y_target: continue
            col_type = detect_type(col)
            if col_type == 'Meta': continue
            if not pd.api.types.is_numeric_dtype(df[col]): continue

            cvals  = ydf[col].fillna(0)
            used   = cvals != 0
            n_used = int(used.sum())
            n_not  = n_y - n_used
            if n_used == 0: continue

            mu_u  = _s(y_vals[used].mean())  if n_used > 0 else None
            mu_n  = _s(y_vals[~used].mean()) if n_not  > 0 else None
            lift  = (mu_u - mu_n) if (mu_u is not None and mu_n is not None) else None

            n_full_u = int((used & full_mask).sum())
            n_full_n = int((~used & full_mask).sum())
            rate_u   = (n_full_u / n_used) if n_used > 0 else 0.0
            rate_n   = (n_full_n / n_not)  if n_not  > 0 else 0.0
            rate_d   = rate_u - rate_n

            try:
                col_vals = ydf[col].fillna(0)
                if float(col_vals.std() or 0) < 1e-12 or float(y_vals.std() or 0) < 1e-12:
                    corr = None
                else:
                    corr = _s(col_vals.corr(y_vals))
            except Exception:
                corr = None

            hi_u  = _s(ydf.loc[high_mask, col].fillna(0).mean()) if high_mask.any() else None
            lo_u  = _s(ydf.loc[low_mask,  col].fillna(0).mean()) if low_mask.any()  else None
            u_dif = (hi_u - lo_u) if (hi_u is not None and lo_u is not None) else None

            if n_used < 3:
                confidence = 'low'
                rec        = '樣本不足，建議補 3~5 筆實驗'
            elif n_used < 6:
                confidence = 'mid-low'
                if lift and lift > (y_std * 0.3):    rec = '初步正向訊號，可觀察'
                elif lift and lift < -(y_std * 0.3): rec = '初步負向訊號，可觀察'
                else: rec = '訊號不明顯，可保留觀察'
            else:
                signs = []
                if lift is not None and abs(lift) > y_std * 0.2:
                    signs.append(1 if lift > 0 else -1)
                if u_dif is not None and abs(u_dif) > 1e-6:
                    signs.append(1 if u_dif > 0 else -1)
                if corr is not None and abs(corr) >= 0.25:
                    signs.append(1 if corr > 0 else -1)

                pos = sum(1 for s in signs if s > 0)
                neg = sum(1 for s in signs if s < 0)
                if   len(signs) >= 2 and pos == len(signs):
                    confidence = 'high'; rec = '多重正向訊號，建議優先觀察'
                elif len(signs) >= 2 and neg == len(signs):
                    confidence = 'high'; rec = '多重負向訊號，建議優先觀察'
                elif len(signs) >= 1:
                    confidence = 'mid';  rec = '單一訊號，需進一步驗證'
                else:
                    confidence = 'mid';  rec = '訊號方向不一致或不明顯'

            results.append({
                'col':            col,
                'type':           col_type,
                'n_used':         n_used,
                'mean_used':      _s(mu_u),
                'mean_not_used':  _s(mu_n),
                'lift':           _s(lift),
                'rate_used':      _s(rate_u * 100, 1),
                'rate_not':       _s(rate_n * 100, 1),
                'rate_diff':      _s(rate_d * 100, 1),
                'corr':           _s(corr),
                'high_usage':     _s(hi_u),
                'low_usage':      _s(lo_u),
                'usage_diff':     _s(u_dif),
                'confidence':     confidence,
                'recommendation': rec,
            })

        order = {'high': 3, 'mid': 2, 'mid-low': 1, 'low': 0}
        results.sort(key=lambda r: (order.get(r['confidence'], 0), abs(r.get('lift') or 0)), reverse=True)

        return {
            'ok':         True,
            'y_target':   y_target,
            'n_y_valid':  n_y,
            'n_full':     n_full,
            'y_stats': {
                'mean':   _s(y_mean),
                'std':    _s(y_std),
                'min':    _s(y_min),
                'max':    _s(y_max),
                'median': _s(y_med),
            },
            'rows': results,
        }

    except Exception as e:
        traceback.print_exc()
        return _err(str(e), status=500)


# ── 貝氏優化（保留原功能）──────────────────────────────────────────────
@router.post('/optimize')
async def material_optimize(body: dict = Body(default={})):
    try:
        import pandas as pd
        from sklearn.gaussian_process import GaussianProcessRegressor
        from sklearn.gaussian_process.kernels import Matern, WhiteKernel
        from sklearn.preprocessing import StandardScaler
        from scipy.stats import norm  # noqa: F401

        rows          = body.get('rows', [])
        x_cols        = body.get('x_cols', [])
        y_targets     = body.get('y_targets', [])
        n_suggest     = int(body.get('n_suggestions', 5))
        max_changes   = int(body.get('max_changes', 5))
        anchor_mode   = body.get('anchor_mode', 'best')
        custom_anchor = body.get('custom_anchor_row', None)

        if not rows or not x_cols or not y_targets:
            return _err('缺少必要參數')

        df = pd.DataFrame(rows)
        for c in x_cols + [t['col'] for t in y_targets]:
            if c in df.columns:
                df[c] = df[c].map(_js_parsefloat)

        y_col_names = [t['col'] for t in y_targets if t['col'] in df.columns]
        valid_mask  = df[y_col_names].notna().all(axis=1)
        train_pool  = df[valid_mask].copy()

        if len(train_pool) < 3:
            return _err(f'Y 欄皆有效的資料僅 {len(train_pool)} 筆，至少需要 3 筆。')

        usable_x = []
        seen = set()
        for c in x_cols:
            if c in df.columns and c not in seen:
                usable_x.append(c); seen.add(c)

        for c in usable_x:
            train_pool[c] = train_pool[c].fillna(0)

        usable_x = [c for c in usable_x if float(train_pool[c].std() or 0) > 1e-9]
        if not usable_x:
            return _err('所選 X 欄位填 0 後變異度都是 0（沒人實際用過），請重新選擇。')

        if len(usable_x) > 30:
            usable_x = train_pool[usable_x].var().nlargest(30).index.tolist()

        y_col_unique = list(dict.fromkeys(y_col_names))
        train_df = train_pool[usable_x + y_col_unique].copy()
        if len(train_df) < 3:
            return _err(f'訓練資料僅 {len(train_df)} 筆，至少需要 3 筆。')

        X_train    = train_df[usable_x].values.astype(float)
        scaler     = StandardScaler()
        X_train_sc = scaler.fit_transform(X_train)
        x_min, x_max = X_train.min(axis=0), X_train.max(axis=0)
        margin = (x_max - x_min) * 0.1
        x_lo, x_hi = x_min - margin, x_max + margin
        x_lo = np.maximum(x_lo, 0)
        flat = (x_hi - x_lo) < 1e-9; x_hi[flat] = x_lo[flat] + 1.0

        gps, bests = [], []
        for yt in y_targets:
            y_vals = train_df[yt['col']].values.astype(float)
            gp = GaussianProcessRegressor(
                kernel=Matern(nu=2.5) + WhiteKernel(0.1),
                n_restarts_optimizer=5, normalize_y=True, random_state=42
            )
            gp.fit(X_train_sc, y_vals)
            gps.append(gp)
            d = yt.get('direction', 'maximize')
            if d == 'minimize':
                bests.append(float(y_vals.min()))
            elif d == 'target':
                tv = float(yt.get('target_value') or 0.0)
                idx = int(np.argmin(np.abs(y_vals - tv)))
                bests.append(float(y_vals[idx]))
            else:
                bests.append(float(y_vals.max()))

        np.random.seed(42)
        n_x_dim = len(usable_x)

        anchor_x        = None
        anchor_idx      = None
        anchor_orig_idx = None

        if custom_anchor is not None:
            try:
                ca = int(custom_anchor)
                if 0 <= ca < len(rows):
                    row = rows[ca]
                    vec = []
                    for c in usable_x:
                        v = row.get(c, 0)
                        try: v = float(v)
                        except Exception: v = 0.0
                        if v != v: v = 0.0
                        vec.append(v)
                    anchor_x = np.array(vec, dtype=float)
                    anchor_orig_idx = ca
            except Exception:
                pass

        if anchor_x is None:
            if anchor_mode == 'best' and y_targets:
                p_y    = y_targets[0]
                yvals  = train_df[p_y['col']].values.astype(float)
                p_dir  = p_y.get('direction', 'maximize')
                if p_dir == 'minimize':
                    anchor_idx = int(np.argmin(yvals))
                elif p_dir == 'target':
                    p_tv = float(p_y.get('target_value') or 0.0)
                    anchor_idx = int(np.argmin(np.abs(yvals - p_tv)))
                else:
                    anchor_idx = int(np.argmax(yvals))
                anchor_x   = X_train[anchor_idx].copy()
            elif anchor_mode == 'mean':
                anchor_x   = X_train.mean(axis=0)

        if anchor_x is None or max_changes <= 0 or max_changes >= n_x_dim:
            X_cand = np.random.uniform(x_lo, x_hi, size=(3000, n_x_dim))
        else:
            X_cand = np.tile(anchor_x, (3000, 1)).astype(float)
            k_max  = min(max_changes, n_x_dim)
            for i in range(3000):
                n_vary = np.random.randint(1, k_max + 1)
                dims   = np.random.choice(n_x_dim, n_vary, replace=False)
                for d in dims:
                    X_cand[i, d] = np.random.uniform(x_lo[d], x_hi[d])

        X_cand_sc = scaler.transform(X_cand)
        ei_mat    = np.zeros((3000, len(y_targets)))
        mu_mat    = np.zeros_like(ei_mat)
        std_mat   = np.zeros_like(ei_mat)

        for j, (gp, yt, best) in enumerate(zip(gps, y_targets, bests)):
            from scipy.stats import norm as _norm
            mu, sigma     = gp.predict(X_cand_sc, return_std=True)
            sigma         = np.maximum(sigma, 1e-9)
            mu_mat[:, j]  = mu; std_mat[:, j] = sigma

            d = yt.get('direction', 'maximize')
            if d == 'minimize':
                improvement = best - mu
            elif d == 'target':
                tv = float(yt.get('target_value') or 0.0)
                best_dist  = abs(best - tv)
                cand_dist  = np.abs(mu - tv)
                improvement = best_dist - cand_dist
            else:
                improvement = mu - best

            z             = improvement / sigma
            ei_mat[:, j]  = np.maximum(improvement * _norm.cdf(z) + sigma * _norm.pdf(z), 0)

        combined = (ei_mat / (ei_mat.max(axis=0, keepdims=True) + 1e-9)).mean(axis=1)
        top_idx  = np.argsort(combined)[::-1][:n_suggest]

        suggestions = []
        for rank, idx in enumerate(top_idx):
            suggestions.append({
                'rank':  rank + 1,
                'score': round(float(combined[idx]), 4),
                'x': {col: round(float(X_cand[idx, i]), 4) for i, col in enumerate(usable_x)},
                'predicted': {
                    yt['col']: {'mean': round(float(mu_mat[idx, j]), 4),
                                'std':  round(float(std_mat[idx, j]), 4),
                                'direction':    yt.get('direction', 'maximize'),
                                'target_value': yt.get('target_value')}
                    for j, yt in enumerate(y_targets)
                }
            })

        anchor_payload = None
        if anchor_x is not None:
            orig_idx = None
            full_row = None
            if anchor_orig_idx is not None:
                orig_idx = anchor_orig_idx
                full_row = rows[orig_idx] if 0 <= orig_idx < len(rows) else None
            elif anchor_idx is not None:
                try:
                    orig_idx = int(train_df.index[anchor_idx])
                    full_row = rows[orig_idx] if 0 <= orig_idx < len(rows) else None
                except Exception:
                    pass
            anchor_payload = {
                'mode':         'custom' if anchor_orig_idx is not None else anchor_mode,
                'x':            {col: round(float(anchor_x[i]), 4) for i, col in enumerate(usable_x)},
                'row_in_train': int(anchor_idx) if anchor_idx is not None else None,
                'row_in_data':  orig_idx,
                'full_row':     full_row,
            }

        ranges = {col: {'min': round(float(X_train[:, i].min()), 4),
                        'max': round(float(X_train[:, i].max()), 4)}
                  for i, col in enumerate(usable_x)}

        return {
            'ok': True, 'n_train': len(train_df),
            'n_x_used': len(usable_x), 'x_cols_used': usable_x,
            'suggestions': suggestions,
            'anchor':      anchor_payload,
            'x_ranges':    ranges,
            'max_changes': max_changes,
        }

    except Exception as e:
        traceback.print_exc()
        return _err(str(e), status=500)


# ── BoTorch GP + 分析式 Feasibility-Weighted EI（per-Y + 條件約束）──────
@router.post('/optimize_botorch')
async def material_optimize_botorch(body: dict = Body(default={})):
    try:
        import pandas as pd
        import torch
        from botorch.models import SingleTaskGP, ModelListGP
        from botorch.models.transforms import Standardize, Normalize
        from botorch.fit import fit_gpytorch_mll
        from gpytorch.mlls import SumMarginalLogLikelihood
        from botorch.utils.multi_objective.pareto import is_non_dominated

        rows          = body.get('rows', [])
        x_cols        = body.get('x_cols', [])
        y_targets     = body.get('y_targets', [])
        n_suggest     = int(body.get('n_suggestions', 5))
        max_changes   = int(body.get('max_changes', 5))
        anchor_mode   = body.get('anchor_mode', 'best')
        custom_anchor = body.get('custom_anchor_row', None)

        if not rows or not x_cols or not y_targets:
            return _err('缺少必要參數')

        torch.manual_seed(42)
        _device = 'cuda' if torch.cuda.is_available() else 'cpu'
        tkwargs = {'dtype': torch.double, 'device': _device}
        print(f'[BoTorch] using device: {_device}', flush=True)

        df = pd.DataFrame(rows)
        for c in x_cols + [t['col'] for t in y_targets]:
            if c in df.columns:
                df[c] = df[c].map(_js_parsefloat)

        y_meta = []
        for yt in y_targets:
            col = yt.get('col')
            if not col or col not in df.columns:
                continue
            mode = yt.get('mode') or yt.get('direction') or 'target'
            if mode == 'maximize': mode = 'target'
            if mode == 'minimize': mode = 'target'
            if mode not in ('gt', 'lt', 'between', 'target'):
                return _err(f'未知模式 {mode}')
            tv   = yt.get('target_value')
            tol  = yt.get('target_tol')
            vmin = yt.get('value_min')
            vmax = yt.get('value_max')
            try: tv   = float(tv)   if tv   not in (None, '') else None
            except Exception: tv = None
            try: tol  = float(tol)  if tol  not in (None, '') else None
            except Exception: tol = None
            try: vmin = float(vmin) if vmin not in (None, '') else None
            except Exception: vmin = None
            try: vmax = float(vmax) if vmax not in (None, '') else None
            except Exception: vmax = None
            if mode == 'gt' and vmin is None:
                return _err(f'「{col}」大於模式缺下限值')
            if mode == 'lt' and vmax is None:
                return _err(f'「{col}」小於模式缺上限值')
            if mode == 'between' and (vmin is None or vmax is None):
                return _err(f'「{col}」介於模式缺上下限')
            if mode == 'target' and tv is None:
                return _err(f'「{col}」目標模式缺目標值')
            y_meta.append({
                'col': col, 'mode': mode,
                'target_value': tv, 'target_tol': tol,
                'value_min': vmin, 'value_max': vmax,
                'weight': float(yt.get('weight', 1.0) or 1.0),
            })

        if not y_meta:
            return _err('無有效 Y 目標')

        obj_meta = [m for m in y_meta if m['mode'] == 'target']
        if not obj_meta:
            return _err('至少需要一個「◎ 目標」模式的 Y 作為優化方向')

        per_y_mask = {m['col']: df[m['col']].notna() for m in y_meta}
        for m in y_meta:
            n = int(per_y_mask[m['col']].sum())
            if n < 3:
                return _err(f'Y「{m["col"]}」只有 {n} 筆有效資料，至少需要 3 筆')

        union_mask = pd.concat(list(per_y_mask.values()), axis=1).any(axis=1)
        if union_mask.sum() < 3:
            return _err('有 Y 量測的列不足 3 筆')

        usable_x = []
        seen = set()
        for c in x_cols:
            if c in df.columns and c not in seen:
                usable_x.append(c); seen.add(c)
        for c in usable_x:
            df[c] = df[c].fillna(0)
        union_df = df[union_mask]
        usable_x = [c for c in usable_x if pd.notna(union_df[c].std()) and float(union_df[c].std()) > 1e-9]
        if not usable_x:
            return _err('所選 X 欄位變異度都是 0')
        if len(usable_x) > 30:
            usable_x = union_df[usable_x].var().nlargest(30).index.tolist()

        per_y_train = {}
        all_X_list = []
        for m in y_meta:
            mask = per_y_mask[m['col']]
            sub  = df[mask]
            Xs   = sub[usable_x].values.astype(float)
            ys   = sub[m['col']].values.astype(float)
            per_y_train[m['col']] = {
                'X': Xs, 'y': ys,
                'orig_idx': list(sub.index),
            }
            all_X_list.append(Xs)
        X_union = np.concatenate(all_X_list, axis=0)

        x_min = X_union.min(axis=0); x_max = X_union.max(axis=0)
        margin = (x_max - x_min) * 0.1
        x_lo = np.maximum(x_min - margin, 0.0)
        x_hi = x_max + margin
        flat = (x_hi - x_lo) < 1e-9; x_hi[flat] = x_lo[flat] + 1.0
        bounds = torch.tensor(np.stack([x_lo, x_hi]), **tkwargs)

        anchor_x_np = None; anchor_orig_idx = None
        if custom_anchor is not None:
            try:
                ca = int(custom_anchor)
                if 0 <= ca < len(rows):
                    row = rows[ca]; vec = []
                    for c in usable_x:
                        v = row.get(c, 0)
                        try: v = float(v)
                        except Exception: v = 0.0
                        if v != v: v = 0.0
                        vec.append(v)
                    anchor_x_np = np.array(vec, dtype=float)
                    anchor_orig_idx = ca
            except Exception:
                pass
        if anchor_x_np is None:
            if anchor_mode == 'best' and obj_meta:
                p_m = obj_meta[0]
                p_data = per_y_train[p_m['col']]
                yvals = p_data['y']
                tv = float(p_m['target_value'])
                li = int(np.argmin(np.abs(yvals - tv)))
                anchor_x_np = p_data['X'][li].copy()
                anchor_orig_idx = int(p_data['orig_idx'][li])
            elif anchor_mode == 'mean':
                anchor_x_np = X_union.mean(axis=0)

        models = []
        for m in y_meta:
            p_data = per_y_train[m['col']]
            X_t = torch.tensor(p_data['X'], **tkwargs)
            Y_t = torch.tensor(p_data['y'].reshape(-1, 1), **tkwargs)
            gp = SingleTaskGP(
                train_X=X_t, train_Y=Y_t,
                input_transform=Normalize(d=X_t.shape[-1], bounds=bounds),
                outcome_transform=Standardize(m=1),
            )
            models.append(gp)
        model = ModelListGP(*models)
        mll = SumMarginalLogLikelihood(model.likelihood, model)
        fit_gpytorch_mll(mll)

        obj_metas = [m for m in y_meta if m['mode'] == 'target']

        all_y_mask = pd.concat(list(per_y_mask.values()), axis=1).all(axis=1)
        pareto_original = []
        if int(all_y_mask.sum()) >= 1:
            all_y_df = df[all_y_mask]
            Y_obj = []
            for m in obj_metas:
                yv = all_y_df[m['col']].values.astype(float)
                tv = float(m['target_value']); tol = m.get('target_tol') or 0
                d  = np.abs(yv - tv)
                if tol > 0: d = np.maximum(d - tol, 0)
                Y_obj.append(-d)
            if Y_obj:
                Y_obj_arr = np.column_stack(Y_obj)
                Y_obj_t = torch.tensor(Y_obj_arr, **tkwargs)
                if Y_obj_t.shape[0] >= 1:
                    pmask = is_non_dominated(Y_obj_t)
                    for ridx in torch.where(pmask)[0].tolist():
                        orig_i = int(all_y_df.index[ridx])
                        pareto_original.append({
                            'row_in_train': int(ridx),
                            'row_in_data':  orig_i,
                            'y_values':     {m['col']: float(all_y_df[m['col']].values[ridx]) for m in y_meta},
                        })

        n_x_dim = len(usable_x); n_random = 256
        np.random.seed(42)
        if anchor_x_np is not None and 0 < max_changes < n_x_dim:
            X_pool = np.tile(anchor_x_np, (n_random, 1)).astype(float)
            k_max  = min(max_changes, n_x_dim)
            for i in range(n_random):
                n_vary = np.random.randint(1, k_max + 1)
                dims   = np.random.choice(n_x_dim, n_vary, replace=False)
                for dd in dims:
                    X_pool[i, dd] = np.random.uniform(x_lo[dd], x_hi[dd])
        else:
            X_pool = np.random.uniform(x_lo, x_hi, size=(n_random, n_x_dim))
        X_pool_t = torch.tensor(X_pool, **tkwargs)

        from scipy.stats import norm as _scipy_norm

        with torch.no_grad():
            post_all = model.posterior(X_pool_t)
            mu_all   = post_all.mean.cpu().numpy()
            sd_all   = np.sqrt(np.maximum(post_all.variance.cpu().numpy(), 1e-12))

        feas = np.ones(n_random)
        for j, m in enumerate(y_meta):
            mu_j = mu_all[:, j]; sd_j = np.maximum(sd_all[:, j], 1e-9)
            if m['mode'] == 'gt':
                z = (float(m['value_min']) - mu_j) / sd_j
                feas *= (1 - _scipy_norm.cdf(z))
            elif m['mode'] == 'lt':
                z = (float(m['value_max']) - mu_j) / sd_j
                feas *= _scipy_norm.cdf(z)
            elif m['mode'] == 'between':
                z_hi = (float(m['value_max']) - mu_j) / sd_j
                z_lo = (float(m['value_min']) - mu_j) / sd_j
                feas *= (_scipy_norm.cdf(z_hi) - _scipy_norm.cdf(z_lo))

        obj = np.zeros(n_random); total_w = 0.0
        for j, m in enumerate(y_meta):
            if m['mode'] != 'target': continue
            mu_j = mu_all[:, j]; sd_j = sd_all[:, j]
            tv  = float(m['target_value'])
            tol = float(m.get('target_tol') or 0.0)
            w   = float(m.get('weight') or 1.0)
            dist = np.abs(mu_j - tv)
            if tol > 0: dist = np.maximum(dist - tol, 0.0)
            obj += w * (-dist + 0.3 * sd_j)
            total_w += w
        if total_w > 0: obj /= total_w
        obj_norm = obj - obj.min()
        obj_max  = obj_norm.max()
        if obj_max > 1e-9: obj_norm /= obj_max

        scores_np = feas * (obj_norm + 1e-6)
        order = np.argsort(scores_np)[::-1]

        range_arr = np.maximum(x_hi - x_lo, 1e-9)
        picked = []
        for idx in order:
            ok = True
            for pi in picked:
                diff = (X_pool[idx] - X_pool[pi]) / range_arr
                if np.linalg.norm(diff) < 0.05:
                    ok = False; break
            if ok: picked.append(int(idx))
            if len(picked) >= n_suggest: break

        X_picks_t = torch.tensor(X_pool[picked], **tkwargs)
        with torch.no_grad():
            post = model.posterior(X_picks_t)
            mu = post.mean.cpu().numpy()
            sd = np.sqrt(np.maximum(post.variance.cpu().numpy(), 1e-12))

        suggestions = []
        for rank, pidx in enumerate(picked):
            pred = {}
            for j, m in enumerate(y_meta):
                pred[m['col']] = {
                    'mean':         round(float(mu[rank, j]), 4),
                    'std':          round(float(sd[rank, j]), 4),
                    'mode':         m['mode'],
                    'target_value': m['target_value'],
                    'target_tol':   m['target_tol'],
                    'value_min':    m['value_min'],
                    'value_max':    m['value_max'],
                }
            suggestions.append({
                'rank':  rank + 1,
                'score': round(float(scores_np[pidx]), 6),
                'x':     {col: round(float(X_pool[pidx, i]), 4) for i, col in enumerate(usable_x)},
                'predicted': pred,
            })

        anchor_prediction = None
        if anchor_x_np is not None:
            X_anchor_t = torch.tensor(anchor_x_np.reshape(1, -1), **tkwargs)
            with torch.no_grad():
                post_a = model.posterior(X_anchor_t)
                a_mu   = post_a.mean.cpu().numpy().flatten()
                a_sd   = np.sqrt(np.maximum(post_a.variance.cpu().numpy().flatten(), 1e-12))
            anchor_prediction = {}
            for j, m in enumerate(y_meta):
                anchor_prediction[m['col']] = {
                    'mean': round(float(a_mu[j]), 4),
                    'std':  round(float(a_sd[j]), 4),
                }

        anchor_payload = None
        if anchor_x_np is not None:
            orig_idx = anchor_orig_idx
            full_row = rows[orig_idx] if (orig_idx is not None and 0 <= orig_idx < len(rows)) else None
            anchor_payload = {
                'mode':         'custom' if (custom_anchor is not None and anchor_orig_idx == int(custom_anchor)) else anchor_mode,
                'x':            {col: round(float(anchor_x_np[i]), 4) for i, col in enumerate(usable_x)},
                'row_in_train': None,
                'row_in_data':  orig_idx,
                'full_row':     full_row,
            }

        ranges = {col: {'min': round(float(X_union[:, i].min()), 4),
                        'max': round(float(X_union[:, i].max()), 4)}
                  for i, col in enumerate(usable_x)}

        per_y_counts = {m['col']: int(per_y_mask[m['col']].sum()) for m in y_meta}

        return {
            'ok':                True,
            'algorithm':         'GP-FW-EI',
            'n_train':           int(min(per_y_counts.values())),
            'per_y_train':       per_y_counts,
            'n_x_used':          int(len(usable_x)),
            'x_cols_used':       usable_x,
            'suggestions':       suggestions,
            'anchor':            anchor_payload,
            'anchor_prediction': anchor_prediction,
            'x_ranges':          ranges,
            'max_changes':       max_changes,
            'pareto_front':      pareto_original,
            'n_objectives':      len(obj_meta),
            'n_constraints':     sum(1 for m in y_meta if m['mode'] != 'target'),
        }

    except Exception as e:
        traceback.print_exc()
        return _err(f'BoTorch 錯誤：{str(e)}', status=500)
