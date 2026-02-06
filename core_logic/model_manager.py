# model_manager.py
import os
import json
import d3rlpy
import numpy as np
import config


def save_policy_bundle(
    algo,
    save_dir,
    bg_features,
    action_features,
    action_stds,
    epoch=None,
    diff=None,
    target_range=None,
    action_ranges=None,  # 改為 action_ranges，預期是 dict: {param: [min, max]}
):
    """Saves policy model and its inference metadata as a bundle."""
    os.makedirs(save_dir, exist_ok=True)

    # 1. 儲存 d3rlpy 模型
    algo.save(os.path.join(save_dir, "policy.d3rlpy"))

    # 2. 儲存 algo 特有的 meta
    algo_meta = {
        "library": "d3rlpy",
        "algo_name": algo.__class__.__name__,
        "algo_file": "policy.d3rlpy",
        "saved_at_epoch": epoch,
        "policy_diff": float(diff) if diff is not None else None,
    }
    with open(os.path.join(save_dir, "algo_meta.json"), "w") as f:
        json.dump(algo_meta, f, indent=2)

    # 3. 儲存推論用的 business meta
    meta = {
        "bg_features": bg_features,
        "action_features": action_features,  # 從參數獲取，不從 config
        "action_stds": action_stds.tolist()
        if isinstance(action_stds, np.ndarray)
        else action_stds,
        "target_range": target_range if target_range else [0, 1],  # 預設 [0, 1]
        "target_center": (target_range[0] + target_range[1]) / 2
        if target_range
        else 0.5,
        "y2_axis_ranges": action_ranges,  # 儲存 Y2 軸範圍字典 {param: [min, max]}
    }
    with open(os.path.join(save_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    print(f"Model bundle saved to: {save_dir}")


def load_policy_bundle(bundle_dir, device="cpu"):
    """Loads a saved policy bundle."""
    with open(os.path.join(bundle_dir, "algo_meta.json"), "r") as f:
        algo_meta = json.load(f)

    algo = d3rlpy.load_learnable(
        os.path.join(bundle_dir, algo_meta["algo_file"]),
        device=device,
    )

    with open(os.path.join(bundle_dir, "meta.json"), "r", encoding="utf-8") as f:
        meta = json.load(f)

    # 轉回 numpy
    meta["action_stds"] = np.asarray(meta["action_stds"], dtype=np.float32)
    return algo, meta


def find_latest_best_model(base_dir=None):
    """
    尋找最新的 best_model 路徑。
    在多租戶環境下，應傳入 user_bundles_dir 以確保隔離。
    """
    if base_dir is None:
        base_dir = os.path.join(config.BASE_STORAGE_DIR, "default", "bundles")

    if not os.path.exists(base_dir):
        return None

    # 搜尋 run_ 開頭的目錄或是直接在 base_dir 下找
    runs = [
        d
        for d in os.listdir(base_dir)
        if (
            d.startswith("run_") or d.startswith("rl_run_") or d.startswith("pred_run_")
        )
        and os.path.isdir(os.path.join(base_dir, d))
    ]

    if not runs:
        # 檢查是否直接就在 base_dir 下
        if os.path.exists(os.path.join(base_dir, "policy.d3rlpy")):
            return base_dir
        return None

    latest_run = sorted(runs)[-1]
    run_path = os.path.join(base_dir, latest_run)
    best_path = os.path.join(run_path, "best_model")
    bundle_path = os.path.join(run_path, "policy_bundle")

    if os.path.exists(best_path):
        return best_path
    elif os.path.exists(bundle_path):
        return bundle_path
    return run_path
