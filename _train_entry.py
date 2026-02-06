# train_entry.py
from core_logic import DataPreprocess
import config
from core_logic import reward_engine
from core_logic import model_manager
from core_logic import monitor_utils
import numpy as np
import os
import sys
import json
import d3rlpy
from datetime import datetime

import matplotlib

matplotlib.use("Agg")


def run_training(job_config_path=None):
    # 1. 读取任务配置（如果提供）
    # Defaults
    target_col = "measure"
    data_path = "data.csv"
    action_cols = []

    # Try safe fallback to config.py if attributes exist
    if hasattr(config, "MEASURE_COL"):
        target_col = config.MEASURE_COL
    if hasattr(config, "RAW_DATA_PATH"):
        data_path = config.RAW_DATA_PATH
    if hasattr(config, "ACTION_FEATURES"):
        action_cols = config.ACTION_FEATURES

    if job_config_path and os.path.exists(job_config_path):
        print(f"📋 Loading job config from: {job_config_path}")
        with open(job_config_path, "r", encoding="utf-8") as f:
            job_conf = json.load(f)

        # 从 JSON 读取目标列 (Override default)
        target_col = job_conf.get("goal", target_col)
        print(f"✅ Target column from config: {target_col}")

        # 从 JSON 读取数据路径 (Override default)
        data_path = job_conf.get("data_full_path", data_path)
        print(f"✅ Data path from config: {data_path}")

        # 从 JSON 读取 Actions (Override default)
        action_cols = job_conf.get("actions", action_cols)
        print(f"✅ Actions from config: {action_cols}")
    else:
        print("⚠️ No job config provided, using default config.py settings")
        print(f"   Target column: {target_col}")
        print(f"   Data path: {data_path}")

    # 2. 资料预处理
    print(f"Loading data from {data_path}...")
    df, all_cols = DataPreprocess.get_processed_data_and_cols(data_path)

    # 验证目标列是否存在
    if target_col not in df.columns:
        raise ValueError(
            f"Target column '{target_col}' not found in data. "
            f"Available columns: {df.columns.tolist()[:10]}..."
        )

    print(f"✅ Target column '{target_col}' found in data")

    # 计算 Action 的标准差
    valid_actions = [c for c in action_cols if c in df.columns]

    if valid_actions:
        delta_actions = df[valid_actions].diff().dropna()
        action_stds = delta_actions.std().values.astype(np.float32) + 1e-6
    else:
        print("⚠️ No valid action columns found or Actions list is empty.")
        action_stds = np.array([], dtype=np.float32)

    bg_features = [c for c in all_cols if c not in valid_actions + [target_col]]

    # Calculate Y2 Axis Range (BG + Action + 10% padding)
    y2_cols = bg_features + valid_actions
    # Filter only numeric columns just in case
    y2_cols = [
        c for c in y2_cols if c in df.columns and np.issubdtype(df[c].dtype, np.number)
    ]

    y2_range = None
    if y2_cols:
        y2_global_min = df[y2_cols].min().min()
        y2_global_max = df[y2_cols].max().max()
        y2_span = y2_global_max - y2_global_min

        # Handle zero span case
        if y2_span == 0:
            y2_span = abs(y2_global_max) * 0.1 if y2_global_max != 0 else 1.0

        y2_range = [
            float(y2_global_min - 0.1 * y2_span),
            float(y2_global_max + 0.1 * y2_span),
        ]
        print(f"✅ Calculated Y2 Range: {y2_range}")

        # Update Job Config with Y2 Range immediately
        if job_config_path and os.path.exists(job_config_path):
            try:
                with open(job_config_path, "r", encoding="utf-8") as f:
                    current_conf = json.load(f)

                current_conf["y2_axis_range"] = y2_range

                with open(job_config_path, "w", encoding="utf-8") as f:
                    json.dump(current_conf, f, ensure_ascii=False, indent=4)
                print("✅ Updated job config with y2_axis_range to file")
            except Exception as e:
                print(f"⚠️ Failed to update job config: {e}")

    # 3. 构建离线强化学习数据集 (MDPDataset)
    states, actions, rewards, terminals = [], [], [], []
    for i in range(len(df) - 1):
        row, row2 = df.iloc[i], df.iloc[i + 1]

        # State: [bg, current_actions, current_y]
        s = np.concatenate(
            [
                row[bg_features].values.astype(np.float32),
                row[config.ACTION_FEATURES].values.astype(np.float32),
                [float(row[target_col])],  # 使用 target_col
            ]
        )

        # Action: normalized delta
        a_raw = (
            row2[config.ACTION_FEATURES].values - row[config.ACTION_FEATURES].values
        ).astype(np.float32)
        a_norm = np.clip(a_raw / action_stds, -1.0, 1.0)

        # Reward: 使用 reward_engine 计算
        r = reward_engine.calculate_reward(
            float(row[target_col]),
            float(row2[target_col]),
            a_norm,  # 使用 target_col
        )

        states.append(s)
        actions.append(a_norm)
        rewards.append(r)
        terminals.append(False)

    # ⭐ 修正：d3rlpy 要求至少有一個端點，否則會噴 AssertionError
    if terminals:
        terminals[-1] = True

    dataset = d3rlpy.dataset.MDPDataset(
        observations=np.array(states),
        actions=np.array(actions),
        rewards=np.array(rewards),
        terminals=np.array(terminals),
    )

    # 3. 初始化 IQL 模型
    iql = d3rlpy.algos.IQLConfig(
        batch_size=config.IQL_BATCH_SIZE,
        actor_learning_rate=config.IQL_ACTOR_LR,
        critic_learning_rate=config.IQL_CRITIC_LR,
        expectile=config.IQL_EXPECTILE,
        weight_temp=config.IQL_WEIGHT_TEMP,
        gamma=config.IQL_GAMMA,
        tau=config.IQL_TAU,
        observation_scaler=d3rlpy.preprocessing.StandardObservationScaler(),
    ).create()

    # 4. 監控與儲存路徑
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(config.MODEL_SAVE_DIR, f"run_{timestamp}")
    callback = monitor_utils.PolicyStabilityCallback(df, bg_features, action_stds)

    # 5. 訓練迴圈
    print(f"Training started. Results will be saved to {run_dir}")
    best_diff = float("inf")
    stable_counter = 0

    for epoch in range(1, config.MAX_EPOCHS + 1):
        iql.fit(dataset, n_steps=500, n_steps_per_epoch=500, show_progress=False)

        diff = callback.on_epoch_end(iql)
        print(f"Epoch {epoch} | Policy Diff: {diff:.6e}")

        # 追蹤並儲存最佳模型
        if diff < best_diff and diff > 0:
            best_diff = diff
            model_manager.save_policy_bundle(
                iql,
                os.path.join(run_dir, "best_model"),
                bg_features,
                config.ACTION_FEATURES,  # 傳入 action_features
                action_stds,
                epoch,
                diff,
                global_y2_range=y2_range,
            )

        # 提早停止判斷
        if diff < config.STABLE_THRESHOLD and epoch > 10:
            stable_counter += 1
            if stable_counter >= config.REQUIRED_STABLE_COUNT:
                print(f"Training converged at epoch {epoch}")
                break
        else:
            stable_counter = 0

    model_manager.save_policy_bundle(
        iql,
        os.path.join(run_dir, "final_model"),
        bg_features,
        config.ACTION_FEATURES,
        action_stds,
        epoch,
        diff,
        global_y2_range=y2_range,
    )


if __name__ == "__main__":
    # 支持从命令行接收 job config 路径
    job_config_path = sys.argv[1] if len(sys.argv) > 1 else None
    run_training(job_config_path)
