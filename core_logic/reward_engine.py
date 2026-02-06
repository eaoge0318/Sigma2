# reward_engine.py
import numpy as np


def dist_to_band(y, low, high):
    """計算 y 到目標區間 [low, high] 的距離"""
    if y < low:
        return low - y
    if y > high:
        return y - high
    return 0.0


def calculate_reward(y, y2, a_norm, low=None, high=None):
    """
    計算 IQL 獎勵
    y: 當前量測值
    y2: 下一步量測值
    a_norm: 正規化後的動作向量
    low/high: 從 UI 傳入的目標區間，若無則報錯 (由引擎層保證存在)
    """
    d_prev = dist_to_band(y, low=low, high=high)
    d_next = dist_to_band(y2, low=low, high=high)

    # 1. 基礎獎勵 (區間內平坦 1.0，區間外平滑下降)
    r_base = 1.0 - 2.0 * d_next

    # 2. 勢能獎勵 (Reward Shaping): 鼓勵向區間靠近
    r_improve = 2.0 * (d_prev - d_next)

    # 3. 動作獎勵:
    # 在區間內使用嚴格的 lam=0.05 抑制亂動
    # 在區間外使用較鬆的 lam=0.2 允許修正
    lam = 0.05 if d_next == 0 else 0.2
    r_act = -lam * float(np.sum(a_norm**2))

    return r_base + r_improve + r_act
