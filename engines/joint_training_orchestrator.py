# joint_training_orchestrator.py
"""
聯合訓練編排器 (Joint Training Orchestrator)
負責依序執行「策略優化 (RL)」與「數據預測 (ML)」訓練任務。
"""

import os
import sys
import json
import traceback
import logging

# 修正導入路徑，確保能找到 root 的 config 與 core_logic
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# 確保可以匯入同級目錄的編排內容
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 強力封鎖 d3rlpy 海量日誌輸出 (全域設定)
logging.getLogger("d3rlpy").propagate = False
logging.getLogger("d3rlpy").setLevel(logging.ERROR)

import engine_prediction
import engine_strategy


def run_joint_training(json_path):
    if not os.path.exists(json_path):
        print(f"Error: 找不到配置檔案 {json_path}")
        return

    print("========================================")
    print("[START] Starting Joint Training task (RL + ML)")
    print("========================================")

    with open(json_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # 1. 執行策略優化 (RL)
    # 檢查是否有 Actions/States 配置
    has_rl = len(config.get("actions", [])) > 0 or len(config.get("rlActions", [])) > 0
    if has_rl:
        print("\n[STEP 1/2] Starting Strategy Engine (RL)...")
        try:
            # 修改狀態為「策略訓練中」以利觀察 (選用)
            # config["status"] = "training_rl"
            # with open(json_path, "w", encoding="utf-8") as f: json.dump(config, f, ensure_ascii=False, indent=4)

            rl_result = engine_strategy.run_from_json(json_path)
            if rl_result and rl_result.get("status") == "success":
                print("[INFO] Strategy Engine executed successfully.")
            else:
                print("[ERROR] Strategy Engine failed to complete.")
                # 若 RL 失敗，不繼續執行 ML
                return
        except Exception as e:
            print(f"[ERROR] Strategy Engine crashed: {str(e)}")
            traceback.print_exc()
            # 更新狀態為失敗
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                cfg["status"] = "failed"
                cfg["error"] = f"Strategy Engine crash: {str(e)}"
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=4)
            except:
                pass
            return
    else:
        print(
            "\n[STEP 1/2] Skipping Strategy Optimization (No Actions/States selected)."
        )

    # 2. 執行數據預測 (ML)
    # 檢查是否有 Features 配置
    has_ml = len(config.get("features", [])) > 0
    if has_ml:
        print("\n[STEP 2/2] Starting Prediction Engine (ML)...")
        try:
            # 重新加載 config (因為 STEP 1 可能更新了內容)
            ml_result = engine_prediction.run_from_json(json_path)
            if ml_result and ml_result.get("status") == "success":
                print("[INFO] Prediction Engine executed successfully.")
            else:
                print("[ERROR] Prediction Engine failed to complete.")
                return
        except Exception as e:
            print(f"[ERROR] Prediction Engine crashed: {str(e)}")
            traceback.print_exc()
            # 更新狀態為失敗
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                cfg["status"] = "failed"
                cfg["error"] = f"Prediction Engine crash: {str(e)}"
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=4)
            except:
                pass
            return
    else:
        print("\n[STEP 2/2] Skipping Prediction (No Features selected).")

    print("\n========================================")
    print("[FINISHED] Joint Training task finished.")
    print("========================================")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_joint_training(sys.argv[1])
    else:
        print("Usage: python joint_training_orchestrator.py <config_json_path>")
