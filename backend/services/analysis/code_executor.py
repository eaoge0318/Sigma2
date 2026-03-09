"""
Code Executor — 安全 Python 程式碼執行沙箱
============================================================
用途: 執行 LLM 生成的 Python 分析程式碼，攔截 matplotlib 圖表轉 base64。
安全: 白名單 import + 超時控制 (適合內網部署)。
"""

import io
import re
import base64
import logging
import traceback
import contextlib
import threading
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ============================================================
# 執行結果
# ============================================================


@dataclass
class CodeResult:
    """Code 執行結果"""

    stdout: str = ""
    stderr: str = ""
    charts: List[Dict[str, str]] = field(default_factory=list)  # [{base64, title}]
    error: Optional[str] = None
    truncated: bool = False


# ============================================================
# 安全限制
# ============================================================

# 白名單: 允許 import 的模組
ALLOWED_MODULES = {
    # data
    "pandas",
    "numpy",
    "scipy",
    # viz
    "matplotlib",
    "matplotlib.pyplot",
    "matplotlib.figure",
    "matplotlib.patches",
    "matplotlib.colors",
    "matplotlib.cm",
    "matplotlib.ticker",
    "matplotlib.gridspec",
    # ml
    "sklearn",
    "sklearn.decomposition",
    "sklearn.ensemble",
    "sklearn.cluster",
    "sklearn.preprocessing",
    "sklearn.metrics",
    "sklearn.model_selection",
    "sklearn.linear_model",
    "sklearn.manifold",
    "sklearn.neighbors",
    "sklearn.feature_selection",
    "sklearn.tree",
    "sklearn.inspection",
    # stats
    "scipy.stats",
    "scipy.signal",
    "scipy.fft",
    "scipy.spatial",
    "scipy.interpolate",
    # utils
    "math",
    "statistics",
    "collections",
    "itertools",
    "functools",
    "operator",
    "textwrap",
    "json",
    "re",
    "datetime",
    "copy",
    "warnings",
    # typing
    "typing",
    # 視覺化
    "seaborn",
    # 統計建模
    "statsmodels",
    "statsmodels.api",
    "statsmodels.formula",
    "statsmodels.formula.api",
    "statsmodels.stats",
    "statsmodels.tsa",
    # sigma 預建分析函式庫 (已預注入 namespace)
    "sigma",
    "sigma_utils",
}

# 黑名單: 絕對禁止的模組
BLOCKED_MODULES = {
    "os",
    "sys",
    "subprocess",
    "shutil",
    "pathlib",
    "socket",
    "http",
    "urllib",
    "requests",
    "importlib",
    "ctypes",
    "multiprocessing",
    "threading",
    "signal",
    "atexit",
    "builtins",
    "__builtin__",
    "pickle",
    "shelve",
    "sqlite3",
    "ftplib",
    "smtplib",
    "telnetlib",
    "webbrowser",
    "tempfile",
    "glob",
}


def _safe_import(name, *args, **kwargs):
    """受限的 __import__ 函數"""
    # Alias mapping: LLM 常用縮寫 → 實際模組名
    _IMPORT_ALIASES = {
        "pd": "pandas",
        "np": "numpy",
        "plt": "matplotlib.pyplot",
        "sns": "seaborn",
    }
    name = _IMPORT_ALIASES.get(name, name)

    # 取得頂層模組名
    top_level = name.split(".")[0]

    if top_level in BLOCKED_MODULES or name in BLOCKED_MODULES:
        raise ImportError(f"模組 '{name}' 被安全策略禁止使用")

    # 白名單檢查: 頂層或完整名稱需在白名單中
    if top_level not in ALLOWED_MODULES and name not in ALLOWED_MODULES:
        raise ImportError(
            f"模組 '{name}' 不在允許清單中。"
            f"允許的模組: pandas, numpy, scipy, sklearn, matplotlib, math, statistics, json, re, datetime"
        )

    return (
        __builtins__["__import__"](name, *args, **kwargs)
        if isinstance(__builtins__, dict)
        else original_import(name, *args, **kwargs)
    )


# 保存原始 __import__
import builtins as _builtins

original_import = _builtins.__import__


# ============================================================
# Matplotlib 圖表攔截器
# ============================================================


class ChartCollector:
    """攔截 matplotlib 的 show/savefig，收集圖表為 base64 PNG"""

    def __init__(self, seen_hashes: set = None, max_charts: int = 15):
        self.charts: List[Dict[str, str]] = []
        self._original_show = None
        self._original_savefig = None
        self._figure_module = None
        self._seen_hashes: set = seen_hashes if seen_hashes is not None else set()
        self._dup_count: int = 0
        self._max_charts: int = max_charts

    def install(self):
        """安裝攔截器"""
        try:
            import matplotlib

            matplotlib.use("Agg")  # 非互動式後端

            # 中文字型配置 (Windows)
            import matplotlib.font_manager as fm

            chinese_fonts = [
                "Microsoft JhengHei",  # 微軟正黑體
                "Microsoft YaHei",  # 微軟雅黑
                "SimHei",  # 黑體
                "Arial Unicode MS",
            ]
            available_font = None
            system_fonts = {f.name for f in fm.fontManager.ttflist}
            for font in chinese_fonts:
                if font in system_fonts:
                    available_font = font
                    break

            if available_font:
                matplotlib.rcParams["font.sans-serif"] = [available_font, "DejaVu Sans"]
                matplotlib.rcParams["axes.unicode_minus"] = False
                logger.info(f"[ChartCollector] 使用中文字型: {available_font}")
            else:
                logger.warning("[ChartCollector] 未找到中文字型，圖表中文可能無法顯示")

            import matplotlib.pyplot as plt
            from matplotlib.figure import Figure

            self._figure_module = Figure
            self._original_show = plt.show
            self._original_savefig = Figure.savefig

            plt.show = self._intercept_show
            Figure.savefig = self._intercept_savefig

        except ImportError:
            logger.warning("matplotlib not installed, chart collection disabled")

    def uninstall(self):
        """還原攔截器"""
        try:
            import matplotlib.pyplot as plt
            from matplotlib.figure import Figure

            if self._original_show:
                plt.show = self._original_show
            if self._original_savefig:
                Figure.savefig = self._original_savefig
        except ImportError:
            pass

    def _intercept_show(self, *args, **kwargs):
        """攔截 plt.show() — 收集所有 open figures，硬上限 15 張"""
        import matplotlib.pyplot as plt

        MAX_CHARTS = 15

        fignums = plt.get_fignums()
        logger.info(
            f"[ChartCollector] plt.show() intercepted, {len(fignums)} figures open"
        )
        for fig_num in fignums:
            fig = plt.figure(fig_num)
            if len(self.charts) < MAX_CHARTS:
                self._capture_figure(fig)
            else:
                logger.warning(f"[ChartCollector] 圖表已達上限 ({MAX_CHARTS})，跳過")
        plt.close("all")

    def _intercept_savefig(self, fig_self, fname, *args, **kwargs):
        """攔截 fig.savefig() — 收集圖表"""
        self._capture_figure(fig_self)

    def _capture_figure(self, fig):
        """將 figure 轉為 base64 PNG，自動去重"""
        try:
            # --- Plot budget 檢查 ---
            if len(self.charts) >= self._max_charts:
                print(f"[CHART] 本輪圖表上限 ({self._max_charts}) 已達，已略過")
                return

            import hashlib
            import struct

            # --- 強制 cap 圖表尺寸（LLM 常生成巨大 figsize）---
            MAX_W, MAX_H = 10, 5  # inches
            fw, fh = fig.get_size_inches()
            if fw > MAX_W or fh > MAX_H:
                scale = min(MAX_W / fw, MAX_H / fh)
                fig.set_size_inches(fw * scale, fh * scale)

            # 先提取標題（含所有子圖標題）
            _all_titles = []
            _suptitle_text = ""
            if fig._suptitle:
                _suptitle_text = fig._suptitle.get_text() or ""
                fig._suptitle.set_text("")  # 清掉避免跟 subplot title 重疊
            if _suptitle_text:
                _all_titles.append(_suptitle_text)
            for ax in fig.axes:
                _ax_title = ax.get_title() or ""
                # 沒有 title 的 subplot → 用 ylabel 自動補 title
                if not _ax_title:
                    _ylabel = ax.get_ylabel() or ""
                    if _ylabel:
                        ax.set_title(_ylabel, fontsize=10)
                        _ax_title = _ylabel
                if _ax_title:
                    _all_titles.append(_ax_title)
            # 合併所有標題（suptitle + 各子圖標題），用空格分隔
            _extracted_title = " ".join(_all_titles).strip()

            buf = io.BytesIO()
            _save_kwargs = dict(
                format="png",
                dpi=120,
                bbox_inches="tight",
                pad_inches=0.3,
                facecolor="white",
                edgecolor="none",
            )
            # 必須使用原始 savefig，否則會觸發 _intercept_savefig → 無限遞迴
            if self._original_savefig:
                self._original_savefig(fig, buf, **_save_kwargs)
            else:
                fig.savefig(buf, **_save_kwargs)
            png_bytes = buf.getvalue()
            buf.close()

            # --- 過濾空白圖表 ---
            if len(png_bytes) < 3000:
                logger.info(
                    f"[ChartCollector] Skipping blank chart ({len(png_bytes)} bytes)"
                )
                return

            # --- 去重: md5 hash ---
            h = hashlib.md5(png_bytes).hexdigest()
            if h in self._seen_hashes:
                self._dup_count += 1
                # 嘗試取標題用於 log
                dup_title = ""
                if fig.axes:
                    dup_title = fig.axes[0].get_title() or ""
                if not dup_title:
                    dup_title = fig._suptitle.get_text() if fig._suptitle else ""
                logger.info(
                    f"[ChartCollector] Duplicate chart suppressed: "
                    f"{dup_title or 'untitled'} (md5={h[:8]})"
                )
                print(f"[CHART] 重複圖表已略過: {dup_title or 'untitled'}")
                return
            self._seen_hashes.add(h)

            b64 = base64.b64encode(png_bytes).decode("utf-8")

            # 使用已提取的標題（在 savefig 前已清掉 matplotlib 內建標題）
            title = _extracted_title

            # 從 PNG bytes 讀取實際像素尺寸（IHDR chunk: offset 16-24）
            try:
                _w, _h = struct.unpack(">II", png_bytes[16:24])
            except Exception:
                _w = int(fig.get_figwidth() * 120)
                _h = int(fig.get_figheight() * 120)

            self.charts.append(
                {
                    "image_base64": b64,
                    "title": title or f"Chart {len(self.charts) + 1}",
                    "width": _w,
                    "height": _h,
                }
            )
            logger.info(f"[ChartCollector] Captured figure: {title or 'untitled'}")
        except Exception as e:
            logger.error(f"Failed to capture figure: {e}")


# ============================================================
# Code Executor
# ============================================================


class StreamingStdout:
    """
    即時串流的 stdout 替代品。
    每次 write() 收到完整一行就呼叫 on_line callback，同時累積 buffer。
    """

    def __init__(self, on_line=None):
        self._buffer = []
        self._line_buffer = ""
        self._on_line = on_line
        self._total_chars = 0
        self._max_chars = 8000
        self._array_suppressed = 0

    def write(self, text):
        if not text:
            return
        self._total_chars += len(text)
        if self._total_chars <= self._max_chars:
            self._buffer.append(text)

        # 逐行觸發 callback
        if self._on_line:
            self._line_buffer += text
            while "\n" in self._line_buffer:
                line, self._line_buffer = self._line_buffer.split("\n", 1)
                line_stripped = line.strip()
                if not line_stripped:
                    continue  # 跳過空行
                # --- Hard guardrail: 偵測 numpy array dump 並自動壓縮 ---
                if self._looks_like_numpy_array_line(line_stripped):
                    self._array_suppressed += 1
                    if self._array_suppressed == 1 and self._on_line:
                        self._on_line("[OUTPUT] numpy array 輸出已自動壓縮（避免爆量）")
                    continue  # 吞掉這行
                else:
                    self._array_suppressed = 0
                # --- 截斷超長行（防止列出所有欄位名）---
                if len(line) > 500:
                    line = line[:500] + "...(已截斷)"
                self._on_line(line)

    def flush(self):
        # 把殘餘不完整行也送出
        if self._on_line and self._line_buffer.strip():
            self._on_line(self._line_buffer)
            self._line_buffer = ""

    def getvalue(self):
        full = "".join(self._buffer)
        if len(full) > self._max_chars:
            return full[: self._max_chars] + "\n... [輸出已截斷]"
        return full

    @property
    def truncated(self):
        return self._total_chars > self._max_chars

    # --- numpy array dump 偵測 (3 層判斷) ---
    _RE_ONLY_NUM_PUNCT = re.compile(r"^[\s\[\]0-9eE.+\-,]{80,}$")
    _RE_MANY_FLOATS = re.compile(r"(?:[-+]?\d*\.\d+|[-+]?\d+\.?\d*[eE][-+]?\d+)\s*[, ]")

    @staticmethod
    def _looks_like_numpy_array_line(s: str) -> bool:
        """偵測看起來像 numpy array dump 的行（避免 stdout 爆量）"""
        # 1) 太短的不管
        if len(s) < 120:
            return False
        # 2) 必須全部是數字/括號/逗號/空白/科學記號字元
        if not StreamingStdout._RE_ONLY_NUM_PUNCT.match(s):
            return False
        # 3) 浮點/科學記號 token 至少 8 個（確認真的像 array）
        float_hits = len(StreamingStdout._RE_MANY_FLOATS.findall(s))
        return float_hits >= 8


class CodeExecutor:
    """
    安全的 Python 程式碼執行器。

    Usage:
        executor = CodeExecutor()
        result = executor.execute(code, context={"df": my_dataframe})
    """

    MAX_OUTPUT_CHARS = 8000  # stdout/stderr 最大字元數
    TIMEOUT_SECONDS = 30
    _corr_patch_lock = threading.RLock()  # 併發保護: corr guardrail patch/restore

    def __init__(self):
        self._chart_hashes: set = set()  # 跨輪次圖表去重

    @staticmethod
    def _install_corr_guardrails():
        """安裝 n<5 corr guardrail，回傳 restore 函式。"""
        import pandas as pd
        import numpy as np

        orig_df_corr = pd.DataFrame.corr
        orig_s_corr = pd.Series.corr
        orig_corrcoef = np.corrcoef

        def _guarded_df_corr(self, *args, **kwargs):
            if len(self) < 5:
                print(
                    f"[GUARDRAIL] DataFrame.corr() 被攔截: n={len(self)} < 5，相關係數無意義。請改用均值比較或貢獻度分析。"
                )
                return pd.DataFrame(
                    np.nan, index=self.columns, columns=self.columns, dtype=float
                )
            return orig_df_corr(self, *args, **kwargs)

        def _guarded_s_corr(self, other=None, *args, **kwargs):
            if other is None:
                return orig_s_corr(self, other, *args, **kwargs)
            n = min(len(self), len(other))
            if n < 5:
                print(f"[GUARDRAIL] Series.corr() 被攔截: n={n} < 5，相關係數無意義。")
                return np.nan
            return orig_s_corr(self, other, *args, **kwargs)

        def _guarded_corrcoef(*args, **kwargs):
            if not args:
                return orig_corrcoef(*args, **kwargs)
            try:
                a = np.asarray(args[0])
                if a.ndim == 1:
                    n = a.shape[0]
                else:
                    rowvar = kwargs.get("rowvar", True)
                    n = a.shape[1] if rowvar else a.shape[0]
                if n < 5:
                    print(
                        f"[GUARDRAIL] np.corrcoef 被攔截: n={n} < 5，相關係數無意義。"
                    )
                    return np.full((2, 2), np.nan)
            except Exception:
                pass
            return orig_corrcoef(*args, **kwargs)

        pd.DataFrame.corr = _guarded_df_corr
        pd.Series.corr = _guarded_s_corr
        np.corrcoef = _guarded_corrcoef

        def _restore():
            pd.DataFrame.corr = orig_df_corr
            pd.Series.corr = orig_s_corr
            np.corrcoef = orig_corrcoef

        return _restore

    @staticmethod
    def _install_describe_guardrail():
        """安裝 describe() guardrail: 欄位 > 20 時自動縮減，避免 stdout 爆炸。"""
        import pandas as pd
        from scipy.stats import median_abs_deviation as _mad_fn

        # --- 補回 pandas 2.0 移除的 .mad() ---
        def _mad_series(self):
            return _mad_fn(self.dropna(), nan_policy="omit")

        def _mad_df(self, axis=0):
            return self.apply(
                lambda s: _mad_fn(s.dropna(), nan_policy="omit"), axis=axis
            )

        if not hasattr(pd.Series, "mad"):
            pd.Series.mad = _mad_series
            pd.DataFrame.mad = _mad_df

        orig_describe = pd.DataFrame.describe

        def _guarded_describe(self, *args, **kwargs):
            result = orig_describe(self, *args, **kwargs)
            if len(result.columns) > 20:
                print(
                    f"[GUARDRAIL] describe() 被縮減: {len(result.columns)} 欄 → 顯示 std 最大的 Top 10"
                )
                # 取 std 最大的 top 10 欄位
                if "std" in result.index:
                    top_cols = result.loc["std"].nlargest(10).index.tolist()
                else:
                    top_cols = list(result.columns[:10])
                return result[top_cols]
            return result

        pd.DataFrame.describe = _guarded_describe

        def _restore():
            pd.DataFrame.describe = orig_describe

        return _restore

    def execute(self, code: str, context: Dict[str, Any] = None) -> CodeResult:
        """執行 Python 程式碼（同步，stdout 不串流）。"""
        return self._execute_impl(code, context, on_stdout_line=None)

    def execute_streaming(
        self, code: str, context: Dict[str, Any] = None, on_stdout_line=None
    ) -> CodeResult:
        """執行 Python 程式碼，stdout 即時串流。"""
        return self._execute_impl(code, context, on_stdout_line=on_stdout_line)

    # ── Sanitizer ─────────────────────────────────────────────
    @staticmethod
    def _sanitize_code(code: str, round_num: int = 0) -> str:
        """修復常見 LLM 生成錯誤"""
        import re as _re

        out: list[str] = []
        _in_broken_print = False

        # 全形字元 → 半形（LLM 有時混入全形標點，會 SyntaxError）
        _fullwidth_map = str.maketrans(
            {
                "\uff0c": ",",
                "\u3001": ",",
                "\uff1a": ":",
                "\uff1b": ";",
                "\uff08": "(",
                "\uff09": ")",
                "\u300c": '"',
                "\u300d": '"',
                "\u3010": "[",
                "\u3011": "]",
                "\uff5b": "{",
                "\uff5d": "}",
            }
        )
        code = code.translate(_fullwidth_map)

        # 所有 json.dumps 若缺少 ensure_ascii=False 則自動補上（括號配對版）
        def _inject_ensure_ascii(src):
            tag = "json.dumps("
            out_parts, idx = [], 0
            while idx < len(src):
                pos = src.find(tag, idx)
                if pos == -1:
                    out_parts.append(src[idx:])
                    break
                out_parts.append(src[idx:pos])
                # 找到 json.dumps( — 用括號配對找到對應的 )
                depth, j = 1, pos + len(tag)
                while j < len(src) and depth > 0:
                    if src[j] == "(":
                        depth += 1
                    elif src[j] == ")":
                        depth -= 1
                    j += 1
                call = src[pos:j]  # 完整的 json.dumps(...) 呼叫
                if "ensure_ascii" not in call:
                    # 在閉合 ) 前插入 , ensure_ascii=False
                    call = call[:-1] + ", ensure_ascii=False)"
                out_parts.append(call)
                idx = j
            return "".join(out_parts)

        code = _inject_ensure_ascii(code)
        # 清理: ensure_ascii=False 如果誤入 print() 層級則移除
        # ⚠️ 不能用 [^)]* regex：無法跨越 json.dumps() 的巢狀括號
        # 改成逐行偵測：以 print( 開頭且行尾是 ", ensure_ascii=False)" 就剝掉
        _ea_lines = []
        for _ln in code.split("\n"):
            _stripped = _ln.rstrip()
            if _re.match(r"\s*print\(", _stripped):
                for _suffix in (", ensure_ascii=False)", ",ensure_ascii=False)"):
                    if _stripped.endswith(_suffix):
                        _ln = _stripped[: -len(_suffix)] + ")" + (_ln[len(_stripped) :])
                        break
            _ea_lines.append(_ln)
        code = "\n".join(_ea_lines)

        # === Pre-pass: 收集 plt.subplots() 產生的 axes ndarray 變數名 ===
        # 目的: Rule 14 用這份 set 判斷哪些變數名是 axes ndarray
        _axes_ndarray_vars: set = set()
        for _scan_ln in code.split("\n"):
            _scan_s = _scan_ln.strip()
            # 匹配: fig, axes = plt.subplots(rows, cols, ...) 或 fig, axs = ...
            _sp_m = _re.search(
                r"(\w+)\s*,\s*(\w+)\s*=\s*plt\.subplots\(([^)]*)\)", _scan_s
            )
            if _sp_m:
                _axes_varname = _sp_m.group(2)  # 第二個 lhs 變數
                _sp_args_raw = _sp_m.group(3)
                # 只有 2+ subplot 的才是 ndarray (1,1) 除外
                _sp_nums = [a.strip() for a in _sp_args_raw.split(",")]
                try:
                    _rows = int(_sp_nums[0]) if _sp_nums else 1
                    _cols = int(_sp_nums[1]) if len(_sp_nums) > 1 else 1
                    if _rows * _cols > 1:
                        _axes_ndarray_vars.add(_axes_varname)
                except (ValueError, IndexError):
                    # 無法解析數字（例如用變數），保守地加進去
                    _axes_ndarray_vars.add(_axes_varname)

        # common axes array 變數名白名單（LLM 常用）
        _axes_ndarray_vars.update({"axes", "axs", "ax_arr", "ax_list", "ax_grid"})

        for _line in code.split("\n"):
            _s = _line.strip()

            # __FINDINGS__ 殘留引用 → 轉為註解
            if "__FINDINGS__" in _s:
                out.append("# [sanitized] removed legacy __FINDINGS__ ref")
                continue

            # broken print 多行吞噬
            if _in_broken_print:
                if '"' in _s:
                    _in_broken_print = False
                out.append("# [sanitized] removed broken print continuation")
                continue

            # Rule 1: 裸標記 → 包 print
            if _s in ("[ANALYSIS_COMPLETE]", "[NEED_MORE_ANALYSIS]"):
                out.append(f'print("{_s}")')
                continue

            # Rule 2: 未關閉 print → 啟動多行清除
            if _re.match(r"^print\(", _s) and _s.count('"') % 2 == 1:
                _in_broken_print = True
                out.append("# [sanitized] removed broken print (start)")
                continue

            # Rule 3: 移除所有 import
            if _re.match(r"^(import\s+|from\s+\S+\s+import\s+)", _s):
                out.append(f"# [sanitized] removed: {_s[:60]}")
                continue

            # Rule 4: df_active 寫保護 → df_tmp
            if _re.match(r"^df_active\s*\[.*\]\s*[\+\-\*/]?=", _s):
                out.append(_line.replace("df_active", "df_tmp", 1))
                continue
            if _re.match(r"^df_active\.(loc|iloc)\[", _s) and "=" in _s:
                out.append(_line.replace("df_active", "df_tmp", 1))
                continue
            if _re.match(r"^df_active\s*=\s*df_active\.", _s):
                out.append(_line.replace("df_active", "df_tmp", 1))
                continue
            if _re.match(
                r"^df_active\.(drop|assign|insert|rename|fillna|replace)\(", _s
            ):
                out.append("df_tmp" + _line.lstrip()[len("df_active") :])
                continue
            if "inplace" in _s and _re.search(
                r"df_active\.\w+\(.*inplace\s*=\s*True", _s
            ):
                out.append(
                    "df_tmp = " + _line.strip().replace("inplace=True", "inplace=False")
                )
                continue

            # Rule 5: 單點 t-test
            if _re.search(r"ttest_ind\(\s*\[?\s*df_active\.loc\[\d+", _s):
                out.append(
                    'print("[SANITIZER] 偵測到單點 t-test，請改用 window-expand")'
                )
                continue

            # Rule 6: 限制全欄位 loop（不刪除，避免 IndentationError）
            if _re.search(r"for\s+\w+\s+in\s+df_active\.columns", _s):
                _indent = _line[: len(_line) - len(_line.lstrip())]
                out.append(
                    f'{_indent}print("[WARNING] 正在遍歷欄位，已限制為前 10 個")'
                )
                out.append(
                    _line.replace("df_active.columns", "list(df_active.columns)[:10]")
                )
                continue

            # Rule 8: .loc[[colname]] 把欄位名當 row index → 提示
            if _re.search(r"""\.loc\[\[['"][A-Z]""", _s):
                out.append(
                    'print("[SANITIZER] .loc[[col]] 是取 row，若要取欄位請用 df[[col]]")'
                )
                continue

            # Rule 9: group_a_idx=start:end 語法錯誤 → 提示
            if _re.search(r"""=\s*\w+\[['"]?\w+['"]?\]\s*:""", _s):
                out.append(
                    "# [sanitized] slice 不能在 kwarg 中使用，請用 list(range(start, end))"
                )
                continue

            # Rule 10: scalar.to_list() → [scalar]（LLM 常對 int 呼叫 .to_list()）
            _to_list_m = _re.search(r"(\w+)\.to_list\(\)", _s)
            if _to_list_m:
                _var = _to_list_m.group(1)
                # 如果變數名看起來像 scalar（index, idx, i, num 等）
                if any(
                    kw in _var.lower()
                    for kw in ["index", "idx", "anomaly", "row", "num"]
                ):
                    out.append(_line.replace(f"{_var}.to_list()", f"[{_var}]"))
                    continue

            # Rule 11: 只攔截真正錯誤的 tuple 解包
            # ❌ for s, e in report["anomaly_intervals"]   ← list of str，不能 unpack
            # ❌ for s, e in df_intervals                  ← dict 缺 .items()
            # ✅ for key, df_seg in df_intervals.items()   ← 正確，不要攔
            _r11_anom = _re.search(
                r"for\s+\w+\s*,\s*\w+\s+in\s+report\s*\[\s*[\"']anomaly_intervals[\"']\s*\]",
                _s,
            )
            _r11_dict = _re.search(
                r"for\s+\w+\s*,\s*\w+\s+in\s+df_intervals\s*(?!\s*\.\s*items)",
                _s,
            )
            if _r11_anom or _r11_dict:
                # Hard Reject: 讓 retry 機制生效，LLM 才會修正
                raise RuntimeError(
                    "[SANITIZER-R11] anomaly_intervals 元素是字串如 '50-69'，不是 tuple！"
                    " 不能用 for s, e in ... 解包。"
                    " 正確: for key, df_seg in df_intervals.items():"
                )

            # Rule 15: Safe Rewrite — LLM 覆蓋系統保護變數 → 自動 comment 掉，不 raise
            # df_intervals 是 dict（切好的 DataFrame），report["anomaly_intervals"] 是 list（字串）
            # Hard Reject 讓 LLM 連續 retry 失敗，改成靜默移除讓分析繼續
            _protected_vars = ("df_intervals", "df_active", "df_baseline", "report")
            _r15_hit = False
            for _pvar in _protected_vars:
                _r15_m = _re.match(
                    rf"^{_pvar}\s*=\s*(?!{_pvar}(?:\s|#|$))",
                    _s,
                )
                if _r15_m:
                    out.append(
                        f"# [SANITIZER-R15] auto-removed: {_pvar} = ... (read-only)"
                    )
                    _r15_hit = True
                    break
            if _r15_hit:
                continue  # 跳過 out.append(_line)，不把原始行加進去

            # Rule 13: df_active.index.str.contains(...) → index 是整數，不能用 .str
            # 另外也攔截 df_anomaly.index.str / df_baseline.index.str
            if _re.search(
                r"\b(?:df_active|df_anomaly|df_baseline|df_seg|df_intervals)\s*\.index\s*\.str\b",
                _s,
            ):
                raise RuntimeError(
                    "[SANITIZER-R13] .index.str 鍵誤: df_active/df_anomaly 的 index 是整數，沒有 .str！"
                    " 改用 df_active.iloc[start:end+1] 或 df_intervals[key] 取切片。"
                )

            # Rule 14: axes.hist(...) / axs.plot(...) → axes 是 ndarray，需 get_ax(axes, 0)
            # 使用 pre-pass 收集的 _axes_ndarray_vars
            if _axes_ndarray_vars:
                _mpl_direct_re = (
                    r"\b("
                    + "|".join(_re.escape(v) for v in _axes_ndarray_vars)
                    + r")\s*\.\s*(hist|bar(?:h)?|plot|scatter|boxplot|violinplot|set_title|set_xlabel|set_ylabel|axvspan|axvline|axhline|set_xlim|set_ylim|legend|tick_params)\s*\("
                )
                _r14_m = _re.search(_mpl_direct_re, _s)
                if _r14_m:
                    _r14_var = _r14_m.group(1)
                    _r14_method = _r14_m.group(2)
                    _indent = _line[: len(_line) - len(_line.lstrip())]
                    # 自動改寫: axes.hist(x) → get_ax(axes, 0).hist(x)
                    _fixed_line = _line.replace(
                        f"{_r14_var}.{_r14_method}(",
                        f"get_ax({_r14_var}, 0).{_r14_method}(",
                        1,  # 只替換第一個
                    )
                    out.append(
                        f"{_indent}# [sanitizer-r14] axes ndarray: 自動插入 get_ax(axes, 0)"
                    )
                    out.append(_fixed_line)
                    continue

            out.append(_line)

        result = "\n".join(out)

        # === G1: sigma.plot_* vs plt.figure/subplots 互斥檢查 ===
        # 禁止同一段 code 同時出現 sigma 系列和 plt 系列（會導致圖層衝突）
        # 例外: plot_point 和 plot_interval_trend 是我們的 helper，不是 sigma.plot，不算互斥
        _has_sigma_plot = bool(
            _re.search(r"sigma\.plot_(?!point|interval_trend)\w*\s*\(", result)
        )
        _has_plt_figure = bool(
            _re.search(r"(?:plt\.figure|plt\.subplots)\s*\(", result)
        )
        if _has_sigma_plot and _has_plt_figure:
            raise RuntimeError(
                "[SANITIZER-G1] 同一段 code 同時使用 sigma.plot_* 和 plt.figure/subplots！"
                " 請一賫中：頝要用 sigma.plot_* 就全程用；要用 plt.figure 就不要用 sigma.plot_*。"
                " 畫 anomaly 單點用 plot_point(ax, x, y)，它不屬於 sigma.plot_系列。"
            )

        if "df_tmp" in result and "df_tmp = " not in result:
            result = "df_tmp = df_active.copy()\n" + result

        # === A3: Plot Budget ===
        # Round 1: max 1 plt.show(), Round 2: max 2, Round 3+: max 1
        _plot_budget = {1: 1, 2: 2}.get(round_num, 1)  # default 1 for round 3+
        import re as _re2

        _show_positions = [m.start() for m in _re2.finditer(r"plt\.show\(\)", result)]
        if len(_show_positions) > _plot_budget:
            # Drop 超量的 show()，保留前 _plot_budget 個
            _keep = set(_show_positions[:_plot_budget])
            _drop_count = len(_show_positions) - _plot_budget
            _new_result = []
            _last = 0
            for _pos in _show_positions:
                if _pos not in _keep:
                    # Replace this plt.show() with a comment
                    _new_result.append(result[_last:_pos])
                    _new_result.append(
                        f"# [SANITIZER-A3] plt.show() dropped (Round {round_num} budget={_plot_budget}, "
                        f"excess #{_drop_count})"
                    )
                    _last = _pos + len("plt.show()")
                    _drop_count -= 1
            _new_result.append(result[_last:])
            result = "".join(_new_result)
            # Just warn, don't raise — preserve existing output
            print(
                f"[SANITIZER-A3] Round {round_num}: "
                f"{len(_show_positions)} plt.show() 超過上限 {_plot_budget}，"
                f"已刪除 {len(_show_positions) - _plot_budget} 個"
            )

        return result

    @staticmethod
    def _sanitize_fstring_columns(code: str) -> str:
        """
        修正 f-string 中的中文欄位名誤用。
        LLM 常把 column name 放進 f-string {} 裡，如:
          f"{(AD)塗佈量} 的值"  → SyntaxError
        修正為:
          f"(AD)塗佈量 的值"    → OK (literal text)

        規則: 如果 {} 內含中文字元且不像合法 Python expression，
              就去掉大括號變成 literal ({{ → 移除大括號)。
        """
        import re

        def _fix_fstring_expr(match):
            expr = match.group(1)
            # 含中文字元 → 很可能是欄位名不是 Python expression
            if re.search(r"[\u4e00-\u9fff]", expr):
                # 但如果是 f"{var}" 格式的合法 expression 裡引用中文變數,
                # 或像 f"{df['中文']}" 這樣有 [] / . 的, 保留不動
                if re.search(r"[\[\]\'\"\.=]", expr):
                    return match.group(0)  # 保留原樣
                # 純中文欄位名 (可能帶括號): 去掉外層大括號
                return expr
            return match.group(0)

        # 只處理 f-string 內的 {} 表達式
        # 匹配 {非空內容} 但排除 {{ 和 }}(Python 的轉義大括號)
        result = re.sub(r"\{([^{}]+)\}", _fix_fstring_expr, code)
        return result

    # ── 核心執行引擎 ──────────────────────────────────────────
    def _run_code(self, code, namespace, collector, stdout_writer, stderr_buf):
        """共用的程式碼執行核心。回傳 error traceback 或 None。"""
        try:
            code = self._sanitize_fstring_columns(code)
            compiled = compile(code, "<code_interpreter>", "exec")
            with self._corr_patch_lock:
                restore_corr = self._install_corr_guardrails()
                restore_desc = self._install_describe_guardrail()
                try:
                    with (
                        contextlib.redirect_stdout(stdout_writer),
                        contextlib.redirect_stderr(stderr_buf),
                    ):
                        _exec_error = [None]

                        def _run_exec():
                            try:
                                exec(compiled, namespace)
                            except Exception as _e:
                                _exec_error[0] = _e

                        _t = threading.Thread(target=_run_exec, daemon=True)
                        _t.start()
                        _t.join(timeout=self.TIMEOUT_SECONDS)
                        if _t.is_alive():
                            raise TimeoutError(
                                f"程式碼執行超時 ({self.TIMEOUT_SECONDS}s)"
                            )
                        if _exec_error[0]:
                            raise _exec_error[0]
                finally:
                    restore_corr()
                    restore_desc()

            if hasattr(stdout_writer, "flush"):
                stdout_writer.flush()
            try:
                import matplotlib.pyplot as plt

                if plt.get_fignums():
                    collector._intercept_show()
            except ImportError:
                pass
            return None
        except Exception as e:
            if hasattr(stdout_writer, "flush"):
                stdout_writer.flush()
            tb = traceback.format_exc()
            logger.warning(f"Code execution error: {e}")
            return tb[-2000:] if len(tb) > 2000 else tb

    # ── 共用實作 ──────────────────────────────────────────────
    def _execute_impl(self, code, context=None, on_stdout_line=None):
        """execute / execute_streaming 的共用實作。"""
        result = CodeResult()
        _max_charts = (context or {}).get("__max_charts__", 15)
        collector = ChartCollector(
            seen_hashes=self._chart_hashes, max_charts=_max_charts
        )
        namespace = self._build_namespace(context or {})
        collector.install()

        _round_num = (context or {}).get("__round__", 0)
        try:
            code = self._sanitize_code(code, round_num=_round_num)
        except RuntimeError as _san_err:
            # Sanitizer 的 RuntimeError 轉換成 result.error，不能直接射出去崩潰 stream
            result.error = str(
                _san_err
            )  # CodeOutputEvent.error 需要字串，不能是 Exception 物件
            return result
        streaming = on_stdout_line is not None
        # 把 data_summary 以 prepend 方式注入 code（在 exec 內執行才能被 StreamingStdout 截取）
        _data_summary = (context or {}).get("__data_summary__", "")
        if _data_summary:
            code = f"print({repr(_data_summary)})\n" + code
        stdout_writer = (
            StreamingStdout(on_line=on_stdout_line) if streaming else io.StringIO()
        )
        stderr_buf = io.StringIO()

        try:
            result.error = self._run_code(
                code, namespace, collector, stdout_writer, stderr_buf
            )
        finally:
            collector.uninstall()

        result.stdout = stdout_writer.getvalue()
        result.stderr = stderr_buf.getvalue()
        collector.uninstall()  # 還原 Figure.savefig，避免污染後續操作
        result.charts = collector.charts
        if hasattr(stdout_writer, "truncated"):
            result.truncated = stdout_writer.truncated

        if len(result.stdout) > self.MAX_OUTPUT_CHARS:
            result.stdout = (
                result.stdout[: self.MAX_OUTPUT_CHARS] + "\n... [輸出已截斷]"
            )
            result.truncated = True
        if len(result.stderr) > self.MAX_OUTPUT_CHARS:
            result.stderr = (
                result.stderr[: self.MAX_OUTPUT_CHARS] + "\n... [輸出已截斷]"
            )

        stderr_buf.close()
        logger.info(
            f"[CodeExecutor] stdout={len(result.stdout)}c, "
            f"charts={len(result.charts)}, "
            f"error={'YES' if result.error else 'NO'}"
        )
        return result

    def _build_namespace(self, context: Dict[str, Any]) -> dict:
        """建立安全的執行 namespace"""
        import pandas as pd
        import numpy as np

        ns = {
            "__builtins__": {
                # 基本 built-in 函數 (白名單)
                "print": print,
                "len": len,
                "range": range,
                "enumerate": enumerate,
                "zip": zip,
                "map": map,
                "filter": filter,
                "sorted": sorted,
                "reversed": reversed,
                "list": list,
                "dict": dict,
                "set": set,
                "tuple": tuple,
                "str": str,
                "int": int,
                "float": float,
                "bool": bool,
                "type": type,
                "isinstance": isinstance,
                "issubclass": issubclass,
                "hasattr": hasattr,
                "getattr": getattr,
                "setattr": setattr,
                "abs": abs,
                "round": round,
                "min": min,
                "max": max,
                "sum": sum,
                "any": any,
                "all": all,
                "hex": hex,
                "oct": oct,
                "bin": bin,
                "chr": chr,
                "ord": ord,
                "repr": repr,
                "format": format,
                "id": id,
                "hash": hash,
                "callable": callable,
                "iter": iter,
                "next": next,
                "slice": slice,
                "staticmethod": staticmethod,
                "classmethod": classmethod,
                "property": property,
                "super": super,
                "object": object,
                "Exception": Exception,
                "ValueError": ValueError,
                "TypeError": TypeError,
                "KeyError": KeyError,
                "IndexError": IndexError,
                "AttributeError": AttributeError,
                "RuntimeError": RuntimeError,
                "StopIteration": StopIteration,
                "ZeroDivisionError": ZeroDivisionError,
                "ImportError": ImportError,
                "True": True,
                "False": False,
                "None": None,
                "__import__": _safe_import,
                # 常用內建
                "dir": dir,
                "vars": vars,
                "globals": lambda: ns,
                "locals": lambda: ns,
                "input": lambda *a: "",  # 禁用 input
                "open": self._blocked_open,
                "exec": lambda *a: None,  # 禁用巢狀 exec
                "eval": lambda *a: None,  # 禁用 eval
                "exit": lambda *a: None,  # LLM 常呼叫 exit()
                "quit": lambda *a: None,
                "compile": lambda *a: None,
            },
            # 預注入常用模組
            "pd": pd,
            "np": np,
        }

        # 嘗試預注入 matplotlib
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            # Safety wrapper: 限制 subplot 數量，防止 LLM 超出 grid 範圍
            _orig_subplot = plt.subplot

            def _safe_subplot(*args, **kwargs):
                try:
                    return _orig_subplot(*args, **kwargs)
                except ValueError:
                    # subplot num 超出 grid → 用最後一個合法位置
                    if len(args) >= 3:
                        nrows, ncols = args[0], args[1]
                        max_num = nrows * ncols
                        return _orig_subplot(nrows, ncols, max_num, **kwargs)
                    raise

            plt.subplot = _safe_subplot

            _orig_subplots = plt.subplots

            def _safe_subplots(*args, **kwargs):
                # 限制 subplots 最大 3x3
                args = list(args)
                if len(args) >= 1 and isinstance(args[0], int):
                    args[0] = min(args[0], 3)
                if len(args) >= 2 and isinstance(args[1], int):
                    args[1] = min(args[1], 3)
                if "nrows" in kwargs:
                    kwargs["nrows"] = min(kwargs["nrows"], 3)
                if "ncols" in kwargs:
                    kwargs["ncols"] = min(kwargs["ncols"], 3)

                # 強制 cap figsize: 最大 12×8 inches
                MAX_W, MAX_H = 12, 8
                if "figsize" in kwargs:
                    fw, fh = kwargs["figsize"]
                    if fw > MAX_W or fh > MAX_H:
                        scale = min(MAX_W / fw, MAX_H / fh)
                        kwargs["figsize"] = (fw * scale, fh * scale)
                else:
                    # 沒指定 figsize 時給合理預設
                    nrows = kwargs.get("nrows", args[0] if args else 1)
                    kwargs["figsize"] = (10, min(MAX_H, 3 * nrows))

                fig, axes = _orig_subplots(*args, **kwargs)
                return fig, axes

            plt.subplots = _safe_subplots

            ns["plt"] = plt
            ns["matplotlib"] = matplotlib
        except ImportError:
            pass

        # 嘗試預注入 sklearn 及常用子模組
        try:
            import sklearn
            import sklearn.ensemble
            import sklearn.decomposition
            import sklearn.cluster
            import sklearn.preprocessing
            import sklearn.model_selection
            import sklearn.linear_model
            import sklearn.manifold
            import sklearn.neighbors

            ns["sklearn"] = sklearn
        except ImportError:
            pass

        # json 模組 — LLM code 可能用到 json.dumps
        import json

        ns["json"] = json

        # 嘗試預注入 scipy + scipy.stats + 常用統計函數
        try:
            import scipy
            import scipy.stats

            ns["scipy"] = scipy
            ns["stats"] = scipy.stats  # LLM 常寫 from scipy import stats

            # 預載常用 scipy.stats 函數，避免 LLM from-import 失敗
            # G3: ttest_ind 小樣本攔截 wrapper
            _orig_ttest = scipy.stats.ttest_ind

            def _safe_ttest_ind(a, b, *args, **kwargs):
                a_arr, b_arr = np.asarray(a).ravel(), np.asarray(b).ravel()
                if len(a_arr) < 5 or len(b_arr) < 5:
                    print(
                        f"[GUARDRAIL] ttest_ind 被攔截: 樣本數不足 "
                        f"(n_a={len(a_arr)}, n_b={len(b_arr)})，需每組≥5"
                    )
                    print(
                        "請改用 robust_z(value, median, mad) 或 window-expand 取得足夠樣本"
                    )
                    raise ValueError(
                        f"t-test 需要每組至少 5 筆 (got {len(a_arr)}, {len(b_arr)})"
                    )
                return _orig_ttest(a_arr, b_arr, *args, **kwargs)

            ns["ttest_ind"] = _safe_ttest_ind
            # --- spearmanr guardrail: 常數 series 偵測 ---
            _orig_spearmanr = scipy.stats.spearmanr

            # ⚠️ namedtuple 必須只有 2 欄位（statistic, pvalue）
            # scipy.stats.spearmanr 回傳的 SpearmanrResult 也只有 2 個可迭代值
            # 如果用 3 欄位，LLM 做 rho, p = spearmanr(...) 就會 ValueError: too many values to unpack
            class _SpearmanNaN:
                """2-value iterable（符合 rho, p = spearmanr() 的解包語法）+ .correlation 屬性 + 下標存取"""

                statistic = float("nan")
                pvalue = float("nan")
                correlation = float("nan")  # 相容舊版 scipy API

                def __iter__(self):
                    yield float("nan")  # statistic
                    yield float("nan")  # pvalue

                def __getitem__(self, idx):
                    # 支援 result[0] 和 result[1] 的常見用法
                    return float("nan")

            _SPEARMAN_NAN = _SpearmanNaN()

            def _safe_spearmanr(a, b=None, **kwargs):
                a_arr = np.asarray(a).ravel()
                if a_arr.size >= 2 and np.std(a_arr) < 1e-12:
                    print(
                        "[GUARDRAIL] spearmanr: 輸入 a 為常數 (std≈0)，rho=NaN，p=NaN"
                    )
                    print("  ⚠️ 常數欄位無法計算相關係數，結論中禁止引用此數字")
                    return _SPEARMAN_NAN
                if b is not None:
                    b_arr = np.asarray(b).ravel()
                    if b_arr.size >= 2 and np.std(b_arr) < 1e-12:
                        print(
                            "[GUARDRAIL] spearmanr: 輸入 b 為常數 (std≈0)，rho=NaN，p=NaN"
                        )
                        print("  ⚠️ 常數欄位無法計算相關係數，結論中禁止引用此數字")
                        return _SPEARMAN_NAN
                result = _orig_spearmanr(a, b, **kwargs)
                # 如果回傳值包含 NaN，警告 LLM 禁止引用
                try:
                    if np.isnan(result.statistic):
                        print(
                            "[GUARDRAIL] spearmanr: 結果 rho=NaN，可能有常數欄位或資料不足"
                        )
                        print("  ⚠️ 結論中禁止引用 NaN 的統計數字")
                except Exception:
                    pass
                return result

            ns["spearmanr"] = _safe_spearmanr
            ns["pearsonr"] = scipy.stats.pearsonr
            ns["mannwhitneyu"] = scipy.stats.mannwhitneyu
            ns["kstest"] = scipy.stats.kstest
            ns["ks_2samp"] = scipy.stats.ks_2samp
            ns["zscore"] = scipy.stats.zscore

            # --- median_abs_deviation guardrail: scalar/空 array 防護 ---
            _orig_mad = scipy.stats.median_abs_deviation

            def _safe_mad(x, **kwargs):
                x_arr = np.asarray(x, dtype=float)
                # scalar (0-dim) 或空 array
                if x_arr.ndim == 0 or x_arr.size == 0:
                    print(
                        "[GUARDRAIL] median_abs_deviation: 收到 scalar 或空 array，回傳 0.0"
                    )
                    print(
                        "  ⚠️ 可能原因: df_baseline[col].median() 傳給 MAD，應改傳 df_baseline[col]（整欄 Series）"
                    )
                    return 0.0
                # 移除 NaN 再計算
                x_clean = x_arr[~np.isnan(x_arr)]
                if x_clean.size == 0:
                    print("[GUARDRAIL] median_abs_deviation: 全為 NaN，回傳 0.0")
                    print(
                        "  ⚠️ 可能原因: df_baseline 切片錯誤導致資料全是 NaN，請確認 df_baseline 不為空"
                    )
                    return 0.0
                return float(_orig_mad(x_clean, **kwargs))

            ns["median_abs_deviation"] = _safe_mad

            # false_discovery_control (scipy ≥1.11)
            try:
                _real_fdc = scipy.stats.false_discovery_control

                def _fdc_wrapper(ps, method="bh", **kwargs):
                    return _real_fdc(ps, method=method)

                ns["false_discovery_control"] = _fdc_wrapper
            except AttributeError:
                pass  # fallback 在下面統一處理
        except ImportError:
            pass

        # false_discovery_control fallback (scipy 太舊或沒裝)
        if "false_discovery_control" not in ns:

            def _fdc_fallback(ps, method="bh", **kwargs):
                """BH FDR fallback — 回傳 adjusted p-values array (同 scipy API)"""
                import numpy as _np

                ps = _np.asarray(ps, dtype=float)
                n = ps.size
                order = _np.argsort(ps)
                ranked = ps[order]
                adj = ranked * n / _np.arange(1, n + 1)
                adj = _np.minimum.accumulate(adj[::-1])[::-1]
                adj = _np.clip(adj, 0, 1)
                result = _np.empty_like(adj)
                result[order] = adj
                return result

            ns["false_discovery_control"] = _fdc_fallback

        # === fdr_bh: 穩定 FDR API（不依賴任何外部版本） ===
        def _fdr_bh(pvals, alpha=0.05):
            """BH FDR — 回傳 (reject_mask, p_adjusted)"""
            import numpy as _np

            p = _np.asarray(pvals, dtype=float)
            n = p.size
            if n == 0:
                return _np.array([], dtype=bool), _np.array([], dtype=float)
            order = _np.argsort(p)
            ranked = p[order]
            adj = ranked * n / _np.arange(1, n + 1)
            adj = _np.minimum.accumulate(adj[::-1])[::-1]
            adj = _np.clip(adj, 0, 1)
            p_adj = _np.empty_like(adj)
            p_adj[order] = adj
            reject = p_adj <= float(alpha)
            return reject, p_adj

        ns["fdr_bh"] = _fdr_bh

        # === plot_point: 安全畫 anomaly 單點（防 x/y 維度錯配）===
        def _plot_point(ax, x, y, **kw):
            """安全畫單點: 自動把 x/y 壓成 scalar, ax 容錯"""
            import numpy as _np
            import matplotlib.figure as _mfig

            # 容錯: 如果傳入 Figure 而非 Axes，取第一個 axes
            if isinstance(ax, _mfig.Figure):
                if ax.axes:
                    ax = ax.axes[0]
                else:
                    ax = ax.add_subplot(111)
            # 容錯: 如果傳入 (fig, axes) tuple
            if isinstance(ax, tuple) and len(ax) == 2:
                ax = ax[1]  # axes
                if hasattr(ax, "__len__"):
                    ax = ax[0]

            try:
                if hasattr(x, "__len__") and not isinstance(x, (str, bytes)):
                    x = _np.asarray(x).ravel()[-1]
                if hasattr(y, "__len__") and not isinstance(y, (str, bytes)):
                    y = _np.asarray(y).ravel()[-1]
            except Exception:
                pass
            kw.setdefault("marker", "o")
            kw.setdefault("markersize", 8)
            ax.plot([x], [y], **kw)

        ns["plot_point"] = _plot_point

        # === get_ax: 安全取 axes[i]（防 subplot cap 導致 IndexError）===
        def _get_ax(axes, i):
            """安全取 axes[i]: 自動拆 (fig, axes) tuple，超出範圍就回最後一個"""
            import matplotlib.figure as _mfig

            # 容錯: plt.subplots() 回傳 (fig, axes)
            if isinstance(axes, tuple) and len(axes) == 2:
                if isinstance(axes[0], _mfig.Figure):
                    axes = axes[1]
            # 容錯: 傳入 Figure
            if isinstance(axes, _mfig.Figure):
                if axes.axes:
                    axes = axes.axes
                else:
                    return axes.add_subplot(111)
            try:
                if hasattr(axes, "__len__"):
                    if i < len(axes):
                        return axes[i]
                    return axes[-1]
                return axes
            except Exception:
                return axes

        ns["get_ax"] = _get_ax

        # === robust_z: MAD-based robust z-score（防 MAD=0 除零 + NaN 防護）===
        def _robust_z(x, median, mad, eps=1e-9):
            """(x - median) / (mad + eps) → 固定回傳 float"""
            try:
                _x = float(x) if not hasattr(x, "__len__") else x
                _m = float(median)
                _mad = float(mad)
            except (TypeError, ValueError):
                print(
                    f"[GUARDRAIL] robust_z 收到無法轉換的輸入 (x={x}, median={median}, mad={mad})"
                )
                return 0.0
            if np.isnan(_m) or np.isnan(_mad):
                print(
                    f"[GUARDRAIL] robust_z 收到 NaN (median={_m}, mad={_mad})，回傳 0.0"
                )
                return 0.0
            if hasattr(x, "__len__"):
                # array-like x
                x_arr = np.asarray(x, dtype=float)
                if np.all(np.isnan(x_arr)):
                    print("[GUARDRAIL] robust_z: x 全為 NaN")
                    return 0.0
                z = (x_arr - _m) / (_mad + eps)
                return float(np.nanmean(z))
            if np.isnan(_x):
                print("[GUARDRAIL] robust_z: x 為 NaN")
                return 0.0
            z = (_x - _m) / (_mad + eps)
            return float(z)

        ns["robust_z"] = _robust_z

        # ============================================================
        # 高層 Helper Functions（封裝 LLM 最容易寫錯的 pattern）
        # LLM 直接呼叫這些 helper，不需要自己組 MAD + robust_z + 存在性檢查
        # ============================================================

        def _analyze_interval(key, df_seg, df_baseline, top_n=3, report=None):
            """
            逐區間標準分析：Marginal Drop 主導 + compare_groups 對比 + plot_trend 趨勢圖。
            自動產生圖表（透過底層 sigma 工具的 auto_chart）。
            report 參數已棄用（保留相容性，不再使用）。
            """
            # 使用 closure 中的 _prep（已從 context 取出）
            _report = _prep if _prep else {}
            t2c = _report.get("t2_contrib", {})
            # Marginal Drop (主導)
            marginal = t2c.get("marginal_scores_by_interval", {}).get(key, [])
            # T² contribution (輔助)
            contribs = t2c.get("top_contributors_by_interval", {}).get(key, [])

            print(f"--- 異常區間 #{key} ({len(df_seg)} 筆) ---")

            # 主導: Marginal Drop
            if marginal:
                print("  Marginal Drop (主導):")
                for col, score in marginal[:top_n]:
                    print(f"    {col}: T²_drop={score:.4f}")

            # 輔助: T² contribution + z-score
            analyze_cols = (
                [c for c, _ in marginal[:top_n]] if marginal else contribs[:top_n]
            )
            if contribs:
                print(f"  T² 貢獻 (輔助): {contribs[:top_n]}")

            results = []
            for col in analyze_cols:
                if col not in df_seg.columns or col not in df_baseline.columns:
                    print(f"  {col}: 欄位不存在，跳過")
                    continue
                bl = df_baseline[col].dropna()
                seg_vals = df_seg[col].dropna()
                if len(bl) == 0 or len(seg_vals) == 0:
                    print(f"  {col}: 資料不足，跳過")
                    continue
                _mad_fn = ns.get("median_abs_deviation", lambda x: 0.0)
                _rz_fn = ns.get("robust_z", lambda x, m, s: 0.0)
                _mad = _mad_fn(bl)
                z = _rz_fn(seg_vals.mean(), bl.median(), _mad)
                print(
                    f"  {col}: 均值={seg_vals.mean():.2f}, baseline中位數={bl.median():.2f}, z={z:.2f}"
                )
                results.append(
                    {
                        "col": col,
                        "z": z,
                        "seg_mean": seg_vals.mean(),
                        "bl_median": bl.median(),
                    }
                )

            # === 自動圖表：呼叫底層 sigma 工具 ===
            _sigma = ns.get("sigma")
            if _sigma and analyze_cols:
                # 1. compare_groups — 分組對比圖
                try:
                    _df_all = ns.get("df_active", ns.get("df_numeric"))
                    if _df_all is not None:
                        seg_indices = list(df_seg.index)
                        bl_indices = list(df_baseline.index)
                        _a_name = f"異常 #{key} ({len(seg_indices)}筆)"
                        _b_name = f"Baseline ({len(bl_indices)}筆)"
                        _sigma.compare_groups(
                            _df_all,
                            group_a_indices=seg_indices,
                            group_b_indices=bl_indices,
                            top_n=top_n,
                            group_a_name=_a_name,
                            group_b_name=_b_name,
                        )
                except Exception as _e:
                    print(f"  [compare_groups 失敗: {_e}]")

                # 2. plot_trend — 趨勢圖 (用 df_active 全域)
                try:
                    _df_all = ns.get("df_active", ns.get("df_numeric"))
                    if _df_all is not None:
                        _valid = [c for c in analyze_cols if c in _df_all.columns][:3]
                        if _valid:
                            _anom_idx = list(df_seg.index)
                            _sigma.plot_trend(
                                _df_all,
                                _valid,
                                anomaly_indices=_anom_idx,
                                title=f"區間 #{key} ({len(df_seg)}筆) 趨勢",
                            )
                except Exception as _e:
                    print(f"  [plot_trend 失敗: {_e}]")

            return contribs

        ns["analyze_interval"] = _analyze_interval

        def _plot_interval_trend(
            df_active, cols, anomaly_indices=None, title="", round_num=None
        ):
            """
            時序趨勢圖 + 異常區段標紅，自動處理最多 3 欄。
            - df_active: 全資料 DataFrame
            - cols: list[str]，最多顯示 3 個欄位
            - anomaly_indices: list[int]，異常點位置（用於 axvspan）
            - title: 圖表標題前綴
            - round_num: 輪次數字（用於標題 [RN]）
            """
            try:
                import matplotlib.pyplot as _plt

                valid = [c for c in cols if c in df_active.columns][:3]
                if not valid:
                    print(f"[plot_interval_trend] 無有效欄位，跳過")
                    return
                fig, ax = _plt.subplots(figsize=(10, 4))
                for col in valid:
                    ax.plot(df_active[col].values, label=col)
                # 標記異常區段
                if anomaly_indices:
                    # 把 indices 轉成連續區段並 axvspan
                    _sorted = sorted(set(int(i) for i in anomaly_indices))
                    if _sorted:
                        _s = _sorted[0]
                        _e = _s
                        for _v in _sorted[1:]:
                            if _v <= _e + 2:
                                _e = _v
                            else:
                                ax.axvspan(_s, _e, color="red", alpha=0.2)
                                _s = _v
                                _e = _v
                        ax.axvspan(_s, _e, color="red", alpha=0.2, label="異常區段")
                r_tag = f"[R{round_num}] " if round_num else ""
                ax.set_title(f"{r_tag}{title}")
                ax.set_xlabel("樣本序號")
                ax.legend(fontsize=8)
                _plt.tight_layout()
                _plt.show()
            except Exception as _e:
                print(f"[plot_interval_trend] 繪圖失敗: {_e}")

        ns["plot_interval_trend"] = _plot_interval_trend

        # 嘗試預注入 statsmodels FDR (LLM 常用但不一定裝了)
        try:
            from statsmodels.stats.multitest import multipletests

            ns["multipletests"] = multipletests
        except ImportError:
            # statsmodels 沒安裝，提供 fallback
            def _multipletests_fallback(pvals, method="fdr_bh", **kw):
                """簡易 BH FDR fallback（statsmodels 未安裝時）"""
                import numpy as _np

                pvals = _np.asarray(pvals)
                n = len(pvals)
                ranked = _np.argsort(pvals)
                adjusted = _np.empty(n)
                for i, idx in enumerate(ranked):
                    adjusted[idx] = pvals[idx] * n / (i + 1)
                adjusted = _np.minimum.accumulate(adjusted[::-1])[::-1]
                adjusted = _np.clip(adjusted, 0, 1)
                reject = adjusted < 0.05
                return reject, adjusted, None, None

            ns["multipletests"] = _multipletests_fallback

        # 嘗試預注入 seaborn（加 ax guardrail wrapper 防止 LLM 傳 axes-array）
        try:
            import seaborn as sns
            import types as _types

            def _make_sns_wrapper(fn):
                """自動把 ax=ndarray 降維成 ax=ndarray.flat[0]，防止 seaborn 崩潰"""

                def _wrapped(*args, **kwargs):
                    if "ax" in kwargs and isinstance(kwargs["ax"], np.ndarray):
                        flat = kwargs["ax"].flat
                        kwargs["ax"] = next(flat)
                        print(
                            "[GUARDRAIL] sns: ax 是 ndarray，自動取 flat[0] 作為目標 axes"
                        )
                    return fn(*args, **kwargs)

                _wrapped.__name__ = getattr(fn, "__name__", "sns_fn")
                return _wrapped

            # 建立 proxy，只包裝常爆炸的畫圖函數
            _sns_proxy = _types.SimpleNamespace(
                **{k: getattr(sns, k) for k in dir(sns) if not k.startswith("_")}
            )
            for _sns_fn in (
                "violinplot",
                "boxplot",
                "stripplot",
                "swarmplot",
                "barplot",
                "pointplot",
                "lineplot",
                "scatterplot",
            ):
                if hasattr(sns, _sns_fn):
                    setattr(
                        _sns_proxy, _sns_fn, _make_sns_wrapper(getattr(sns, _sns_fn))
                    )

            # heatmap guardrail: object dtype corr matrix → float
            _orig_heatmap = sns.heatmap

            def _safe_heatmap(data=None, *args, **kwargs):
                if data is not None:
                    try:
                        import pandas as _pd

                        if (
                            isinstance(data, _pd.DataFrame)
                            and data.dtypes.eq(object).any()
                        ):
                            data = data.apply(_pd.to_numeric, errors="coerce")
                            print(
                                "[GUARDRAIL] sns.heatmap: object dtype 已自動轉換為 float"
                            )
                        elif hasattr(data, "dtype") and data.dtype == object:
                            data = np.array(data, dtype=float)
                            print(
                                "[GUARDRAIL] sns.heatmap: object dtype ndarray 已自動轉換為 float"
                            )
                    except Exception:
                        pass
                return _orig_heatmap(data, *args, **kwargs)

            _sns_proxy.heatmap = _safe_heatmap
            ns["sns"] = _sns_proxy
        except ImportError:
            pass

        # 注入 warnings (允許 suppress)
        import warnings

        ns["warnings"] = warnings

        # 注入 sigma_utils 預建分析函式庫
        try:
            from backend.services.analysis import sigma_utils as _sigma

            ns["sigma"] = _sigma
            logger.info("[CodeExecutor] sigma_utils 注入成功")
        except ImportError:
            try:
                from . import sigma_utils as _sigma

                ns["sigma"] = _sigma
                logger.info("[CodeExecutor] sigma_utils 注入成功 (相對 import)")
            except ImportError:
                _sigma = None
                logger.warning(
                    "[CodeExecutor] sigma_utils 注入失敗, Code Interpreter 將無預建函式"
                )

        # 註冊到 sys.modules（用 proxy，避免跨 request 污染）
        if _sigma is not None:
            import sys

            # === sigma proxy: 不直接改原始模組，避免多 request 交叉污染 ===
            import types

            _sigma_proxy = types.SimpleNamespace(
                **{k: getattr(_sigma, k) for k in dir(_sigma) if not k.startswith("_")}
            )

            # plot_trend safe wrapper: 強制 cols 分批 ≤3
            _original_plot_trend = _sigma.plot_trend

            def _safe_plot_trend(df, cols, anomaly_indices=None, window=None, title=""):
                if isinstance(cols, str):
                    cols = [cols]
                valid = [c for c in cols if c in df.columns]
                if not valid:
                    print("[sigma.plot_trend] 無有效欄位，跳過")
                    return
                CHUNK = 3
                MAX_BATCHES = 2  # 最多畫 2 批 (6 欄)
                for i in range(0, len(valid), CHUNK):
                    if i // CHUNK >= MAX_BATCHES:
                        print(
                            f"[sigma.plot_trend] 已畫 {MAX_BATCHES} 批，略過剩餘 {len(valid) - i} 欄"
                        )
                        break
                    batch = valid[i : i + CHUNK]
                    btitle = (
                        f"{title} ({i // CHUNK + 1})" if len(valid) > CHUNK else title
                    )
                    try:
                        _original_plot_trend(
                            df,
                            batch,
                            anomaly_indices=anomaly_indices,
                            window=window,
                            title=btitle,
                        )
                    except Exception as e:
                        print(f"[sigma.plot_trend] batch failed: {btitle} err={e}")

            _sigma_proxy.plot_trend = _safe_plot_trend
            ns["sigma"] = _sigma_proxy
            sys.modules["sigma"] = _sigma_proxy

        # 預定義 LLM 常用的標記常數 (防止忘記加引號)
        ns["ANALYSIS_COMPLETE"] = "[ANALYSIS_COMPLETE]"
        ns["NEED_MORE_ANALYSIS"] = "[NEED_MORE_ANALYSIS]"

        # 注入用戶 context (df, file_path, etc.)
        # 先提取 _prep（系統用，不注入 LLM namespace）
        _prep = context.pop("_prep", None) or {}
        ns.update(context)

        # === 從 _prep 擷取預建 DataFrame，供 LLM 直接使用 ===
        # report 已不注入 namespace，LLM 只能用 df_anomaly/df_baseline/df_intervals + sigma tools
        _fallback_df = ns.get("df_active", pd.DataFrame())
        _da = _prep.get("_df_anomaly") if _prep else None
        if _da is not None:
            ns["df_anomaly"] = _da
            logger.info(
                f"[CodeExecutor] df_anomaly 注入成功: {len(_da)} 筆, index range [{_da.index.min()}-{_da.index.max()}]"
            )
        else:
            ns["df_anomaly"] = _fallback_df
            logger.warning(
                f"[CodeExecutor] ⚠️ df_anomaly fallback 到 df_active ({len(_fallback_df)} 筆) — preprocess 可能失敗!"
            )
        _db = _prep.get("_df_baseline") if _prep else None
        if _db is not None:
            ns["df_baseline"] = _db
            logger.info(f"[CodeExecutor] df_baseline 注入成功: {len(_db)} 筆")
        else:
            ns["df_baseline"] = _fallback_df
            logger.warning(
                f"[CodeExecutor] ⚠️ df_baseline fallback 到 df_active ({len(_fallback_df)} 筆)"
            )

        # df_intervals: 安全 dict，key 不存在回空 DataFrame
        _raw_intervals = _prep.get("_df_intervals", {}) if _prep else {}
        _df_active = _fallback_df

        class _SafeIntervalDict(dict):
            """KeyError 時自動 parse key 並返回切片，避免 LLM code 炸掉"""

            def __missing__(self, key):
                if isinstance(key, str) and "-" in key:
                    parts = key.split("-")
                    try:
                        s, e = int(parts[0]), int(parts[1])
                        df_slice = _df_active.iloc[s : e + 1]
                        self[key] = df_slice  # cache
                        return df_slice
                    except (ValueError, IndexError):
                        pass
                return pd.DataFrame()  # 真的找不到就回空

        ns["df_intervals"] = _SafeIntervalDict(_raw_intervals)
        # === STATE: run-level 持久 namespace（跨輪次共享計算結果）===
        _ci_state = context.get("__ci_state__")
        if _ci_state is None:
            _ci_state = {}
        ns["STATE"] = _ci_state

        return ns

    @staticmethod
    def _blocked_open(*args, **kwargs):
        raise PermissionError(
            "檔案操作被安全策略禁止。請使用預載入的 df (DataFrame) 存取資料。"
        )
