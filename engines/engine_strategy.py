import sys
import os
import logging

# 修正導入路徑，確保能找到 root 的 config 與 core_logic
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core_logic import DataPreprocess
from core_logic import reward_engine
from core_logic import model_manager
from core_logic import monitor_utils
import numpy as np
import config  # 匯入全域配置

# 強力封鎖 d3rlpy 及其所有子模組的海量日誌輸出 (必須在匯入 d3rlpy 之前執行)
d3rlpy_logger = logging.getLogger("d3rlpy")
d3rlpy_logger.propagate = False
d3rlpy_logger.setLevel(logging.ERROR)
for handler in d3rlpy_logger.handlers[:]:
    d3rlpy_logger.removeHandler(handler)
d3rlpy_logger.addHandler(logging.NullHandler())

import d3rlpy
import json
from datetime import datetime
from contextlib import contextmanager
import sys


@contextmanager
def silence_stdout():
    """暴力攔截 stdout，徹底關掉第三方套件的強制列印"""
    new_target = open(os.devnull, "w")
    old_stdout = sys.stdout
    sys.stdout = new_target
    try:
        yield new_target
    finally:
        sys.stdout = old_stdout
        new_target.close()


def run_parameterized_rl(
    data_path,
    goal_col,
    action_features,
    state_features,
    hyperparams,
    common_settings,
    goal_settings=None,
    save_dir="model",
):
    """
    執行參數化的離線強化學習訓練

    Args:
        data_path: CSV 檔案路徑
        goal_col: 目標欄位 (用於獎勵函數)
        action_features: 控制參數 (Action Space)
        state_features: 背景參數 (State Space)
        hyperparams: IQL 特定參數 (expectile, weight_temp 等)
        common_settings: 通用設定 (epochs, precision 等)
        goal_settings: 目標品質區間設定 (LSL/USL)
    """
    if not data_path or not goal_col or not action_features:
        raise ValueError(
            "Missing critical modeling info: data_path, goal_col, or action_features not provided."
        )

    if not goal_settings or "lsl" not in goal_settings or "usl" not in goal_settings:
        raise ValueError(
            "Quality goals (LSL/USL) must be set in UI, default values not allowed."
        )

    # 提取品質區間
    y_low = float(goal_settings.get("lsl", 0.0))
    y_high = float(goal_settings.get("usl", 1.0))

    # print(f"DEBUG: Starting IQL task, target range: [{y_low}, {y_high}]")

    # 1. 資料預處理
    df, _ = DataPreprocess.get_processed_data_and_cols(data_path)

    # 計算 Action 標準差 (用於正規化)
    delta_actions = df[action_features].diff().dropna()
    action_stds = delta_actions.std().values.astype(np.float32) + 1e-6

    # Calculate Y2 Axis Range for ALL Numeric Parameters in the dataset
    # This ensures both Strategy and Prediction model parameters are covered.
    y2_candidates = df.select_dtypes(include=[np.number]).columns.tolist()

    # Filter valid numeric columns (double check)
    y2_cols = [c for c in y2_candidates if c in df.columns]

    y2_ranges = {}
    if y2_cols:
        print("[INFO] Calculating individual Y2 ranges (Mean +/- 6 Sigma):")
        for col in y2_cols:
            col_data = df[col].dropna()
            if len(col_data) == 0:
                continue

            mean_v = col_data.mean()
            std_v = col_data.std()

            # Handle zero std
            if std_v == 0:
                std_v = 1.0 if mean_v == 0 else abs(mean_v) * 0.1

            min_v = float(mean_v - 6 * std_v)
            max_v = float(mean_v + 6 * std_v)
            y2_ranges[col] = [min_v, max_v]
            print(f"   Parameter '{col}': {[min_v, max_v]}")

    # 2. 構建 MDPDataset
    states, actions, rewards, terminals = [], [], [], []
    for i in range(len(df) - 1):
        row, row2 = df.iloc[i], df.iloc[i + 1]

        # State: [選定的背景參數 + 當前動作 + 當前目標值]
        s = np.concatenate(
            [
                row[state_features].values.astype(np.float32),
                row[action_features].values.astype(np.float32),
                [float(row[goal_col])],
            ]
        )

        # Action: 正規化位移量
        a_raw = (row2[action_features].values - row[action_features].values).astype(
            np.float32
        )
        a_norm = np.clip(a_raw / action_stds, -1.0, 1.0)

        # Reward: 呼叫獎勵引擎 (傳入介面設定的低標/高標)
        r = reward_engine.calculate_reward(
            float(row[goal_col]), float(row2[goal_col]), a_norm, low=y_low, high=y_high
        )

        states.append(s)
        actions.append(a_norm)
        rewards.append(r)
        terminals.append(False)

    if terminals:
        terminals[-1] = True

    # print(f"DEBUG: Dataset constructed. Transitions: {len(states)}")
    if len(states) == 0:
        print(
            "CRITICAL: Dataset is empty! Please check if your CSV has more than 1 row and valid feature columns."
        )
    elif len(states) < 100:
        print(
            f"WARNING: Dataset size ({len(states)}) is very small for RL. Training might be unstable or ineffective."
        )

    dataset = d3rlpy.dataset.MDPDataset(
        observations=np.array(states),
        actions=np.array(actions),
        rewards=np.array(rewards),
        terminals=np.array(terminals),
    )

    # 3. 初始化 IQL 模型 (參數優先級：UI > config.py > Hardcoded)
    algo_defaults = config.ALGO_CONFIGS.get("IQL", {})

    iql_config = d3rlpy.algos.IQLConfig(
        batch_size=int(
            hyperparams.get("batch_size") or algo_defaults.get("batch_size", 1024)
        ),
        actor_learning_rate=float(
            hyperparams.get("actor_learning_rate")
            or algo_defaults.get("actor_learning_rate", 3e-4)
        ),
        critic_learning_rate=float(
            hyperparams.get("critic_learning_rate")
            or algo_defaults.get("critic_learning_rate", 3e-4)
        ),
        expectile=float(
            hyperparams.get("expectile") or algo_defaults.get("expectile", 0.8)
        ),
        weight_temp=float(
            hyperparams.get("weight_temp") or algo_defaults.get("weight_temp", 0.5)
        ),
        gamma=float(hyperparams.get("gamma") or algo_defaults.get("gamma", 0.99)),
        tau=float(hyperparams.get("tau") or algo_defaults.get("tau", 0.01)),
        observation_scaler=d3rlpy.preprocessing.StandardObservationScaler(),
    )
    with silence_stdout():
        iql = iql_config.create()

    # 4. 準備監控
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(save_dir, f"rl_run_{timestamp}")
    callback = monitor_utils.PolicyStabilityCallback(
        df,
        state_features,
        action_features,
        goal_col,
        action_stds,
        y_low=y_low,
        y_high=y_high,
    )

    # 5. 訓練迴圈 (訓練停止條件優先級：UI > config.py > Hardcoded)
    train_common_defaults = config.TRAIN_COMMON
    max_epochs = int(
        common_settings.get("epochs") or train_common_defaults.get("MAX_EPOCHS", 500)
    )
    stable_threshold = float(
        common_settings.get("precision")
        or train_common_defaults.get("STABLE_THRESHOLD", 0.001)
    )
    # 設定 d3rlpy 日誌等級，過濾掉海量的初始化參數訊息
    import logging

    logging.getLogger("d3rlpy").setLevel(logging.ERROR)

    print(f"\n[INFO] Starting Strategy Training (RL)")
    print(f"       Max Epochs: {max_epochs}")
    print(f"       Stability Threshold: {stable_threshold}")
    required_stable_count = int(common_settings.get("stable_count", 5))

    stable_counter = 0
    final_epoch = 0

    # 取得 IQL 特有的步數設定
    n_steps = int(
        common_settings.get("n_steps") or train_common_defaults.get("N_STEPS", 500)
    )
    n_steps_per_epoch = int(
        common_settings.get("n_steps_per_epoch")
        or train_common_defaults.get("N_STEPS_PER_EPOCH", 500)
    )

    for epoch in range(1, max_epochs + 1):
        # d3rlpy 2.0+ 的 fit(n_steps) 接收的是「總累積步數」
        # 在手動迴圈中，每一輪必須遞增目標步數才能讓模型繼續前進
        target_steps = epoch * n_steps
        with silence_stdout():
            iql.fit(
                dataset,
                n_steps=target_steps,
                n_steps_per_epoch=n_steps_per_epoch,
                show_progress=False,
            )

        # 穩定性檢查 (由介面參數決定何時停下)
        diff = callback.on_epoch_end(iql)
        final_epoch = epoch

        # 精簡輸出每輪狀態
        print(f"Epoch {epoch:03d}/{max_epochs} | Stability Diff: {diff:.8f}")

        if diff < stable_threshold and epoch > 10:
            stable_counter += 1
            if stable_counter >= required_stable_count:
                print(f"[SUCCESS] Training converged at epoch {epoch}")
                break
        else:
            stable_counter = 0

    # 6. 保存最終產出
    model_manager.save_policy_bundle(
        iql,
        os.path.join(run_dir, "policy_bundle"),
        state_features,
        action_features,  # 傳入 action_features
        action_stds,
        final_epoch,
        diff,
        action_ranges=y2_ranges,
    )

    return {
        "status": "success",
        "run_dir": run_dir,
        "final_epoch": final_epoch,
        "final_diff": diff,
        "y2_ranges": y2_ranges,
    }


def run_from_json(json_path):
    """從 JSON 配置文件啟動 IQL 訓練"""
    if not os.path.exists(json_path):
        print(f"Error: Config file not found {json_path}")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        job_config = json.load(f)

    # 核心參數：必須由 UI 提供，否則直接報錯 (不再回退到 config.py)
    data_path = job_config.get("data_full_path") or job_config.get("filename")
    goal_col = job_config.get("goal")
    actions = job_config.get("actions")
    states = job_config.get("states", [])
    goal_settings = job_config.get("goal_settings") or job_config.get("goalSettings")

    if not data_path or not goal_col or not actions:
        raise ValueError(
            "Missing modeling info (file/target/features). please select in UI before training."
        )

    # 回填建模資訊：優先讀取專屬 RL 的配置，若無則回退至 generic 配置
    hyperparams = job_config.get("rl_hyperparams") or job_config.get("hyperparams", {})
    common_settings = job_config.get("rl_common") or job_config.get("common", {})

    # 執行訓練
    save_dir = job_config.get("bundles_dir", "model")
    result = run_parameterized_rl(
        data_path=data_path,
        goal_col=goal_col,
        action_features=actions,
        state_features=states,
        hyperparams=hyperparams,
        common_settings=common_settings,
        goal_settings=goal_settings,
        save_dir=save_dir,
    )

    # 回寫狀態到 JSON (供 UI 顯示)
    if result and result.get("status") == "success":
        job_config["status"] = "completed"
        job_config["final_epoch"] = result.get("final_epoch")
        job_config["final_diff"] = round(result.get("final_diff", 0), 6)
        job_config["run_dir"] = result.get("run_dir")

        if result.get("y2_ranges"):
            job_config["y2_axis_ranges"] = result.get("y2_ranges")

        # 關鍵：在策略輸出資料夾內也存一份「暫存緩存」
        run_path = result.get("run_dir")
        if run_path:
            with open(
                os.path.join(run_path, "config.json"), "w", encoding="utf-8"
            ) as f:
                json.dump(job_config, f, ensure_ascii=False, indent=4)

        # 同步更新原始 JSON
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(job_config, f, ensure_ascii=False, indent=4)

    return result


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # 支持命令行: python engine_strategy.py config.json
        run_from_json(sys.argv[1])
    else:
        print(
            "Strategy Engine Ready. Usage: python engine_strategy.py <config_json_path>"
        )
