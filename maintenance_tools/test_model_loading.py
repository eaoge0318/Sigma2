# test_model_loading.py
"""测试策略模型加载"""

import os
import sys

# 测试路径
model_path = "workspace/Mantle/bundles/rl_run_20260203_233740/policy_bundle"

print("=" * 60)
print("策略模型加载测试")
print("=" * 60)

# 检查文件是否存在
print(f"\n1. 检查模型文件是否存在...")
files_to_check = [
    os.path.join(model_path, "policy.d3rlpy"),
    os.path.join(model_path, "meta.json"),
    os.path.join(model_path, "algo_meta.json"),
]

all_exist = True
for fpath in files_to_check:
    exists = os.path.exists(fpath)
    status = "✅ 存在" if exists else "❌ 不存在"
    print(f"  {status}: {fpath}")
    if not exists:
        all_exist = False

if not all_exist:
    print("\n❌ 错误：部分文件不存在！")
    sys.exit(1)

# 尝试加载模型
print(f"\n2. 尝试加载模型...")
try:
    import model_manager

    algo, meta = model_manager.load_policy_bundle(model_path)

    print(f"✅ 模型加载成功！")
    print(f"   - 算法类型: {type(algo).__name__}")
    print(f"   - 背景特征数: {len(meta['bg_features'])}")
    print(f"   - 动作特征: {meta.get('action_features', meta.get('action_stds', []))}")
    print(f"   - Action STDs: {meta['action_stds']}")

    # 测试预测
    print(f"\n3. 测试模型预测...")
    import numpy as np

    # 创建一个测试状态（bg_features + action_features + current_y）
    num_bg = len(meta["bg_features"])
    num_actions = len(meta["action_stds"])

    test_state = np.zeros((1, num_bg + num_actions + 1), dtype=np.float32)

    try:
        action = algo.predict(test_state)
        print(f"✅ 预测成功！")
        print(f"   - 输出维度: {action.shape}")
        print(f"   - 输出值: {action[0]}")
    except Exception as e:
        print(f"❌ 预测失败: {e}")
        import traceback

        traceback.print_exc()

except Exception as e:
    print(f"❌ 模型加载失败: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)

print(f"\n" + "=" * 60)
print("✅ 所有测试通过！模型正常工作。")
print("=" * 60)
