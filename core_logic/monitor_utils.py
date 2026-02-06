# monitor_utils.py
import os
import json
import numpy as np
import matplotlib.pyplot as plt
import config


class PolicyStabilityCallback:
    def __init__(
        self,
        df,
        bg_features,
        action_features,
        goal_col,
        action_stds,
        y_low=0.0,
        y_high=1.0,
        probe_count=16,
    ):
        self.df = df.reset_index(drop=True)
        self.bg_features = bg_features
        self.action_features = action_features
        self.goal_col = goal_col
        self.action_stds = action_stds
        self.y_low = y_low
        self.y_high = y_high
        self.output_dir = config.DASHBOARD_DIR
        self.y_grid = np.linspace(0, 5, 100)
        self.epoch = 0
        self.prev_actions = None
        self.diff_history = []
        self.epoch_history = []

        # 固定幾個測試樣本觀測 Policy 變化
        n = len(self.df)
        self.probe_indices = np.random.choice(
            np.arange(0, n), size=min(probe_count, n), replace=False
        ).tolist()

    def on_epoch_end(self, algo):
        self.epoch += 1

        # 1. 計算 Policy Diff
        current_actions_batch = []
        for i in self.probe_indices:
            row = self.df.iloc[i]
            bg = row[self.bg_features].values.astype(np.float32)
            x0 = row[self.action_features].values.astype(np.float32)

            actions_list = []
            for y in self.y_grid:
                # 關鍵：這裡必須與 engine_strategy.py 的狀態構建邏輯完全一致
                s = np.concatenate([bg, x0, [y]]).astype(np.float32)
                a = algo.predict(s[None, :])[0]
                actions_list.append(a)
            current_actions_batch.append(np.stack(actions_list))

        avg_actions = np.mean(np.stack(current_actions_batch), axis=0)

        diff = 0.0
        if self.prev_actions is not None:
            diff = float(
                np.mean(np.linalg.norm(avg_actions - self.prev_actions, axis=1))
            )
            self.diff_history.append(diff)
            self.epoch_history.append(self.epoch)
        self.prev_actions = avg_actions.copy()

        # 2. 繪製監控圖並儲存
        self._save_monitor_plot(avg_actions, diff)
        self._save_status_json(diff)

        return diff

    def _save_monitor_plot(self, avg_actions, diff):
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

        # Policy Slice
        ax1.axvspan(
            self.y_low, self.y_high, color="green", alpha=0.1, label="Target Zone"
        )
        for i, name in enumerate(self.action_features):
            ax1.plot(self.y_grid, avg_actions[:, i], label=name)
        ax1.set_title(f"Policy Slice @ Epoch {self.epoch}")
        ax1.legend(fontsize="small")
        ax1.set_xlabel("Quantity (y)")
        ax1.set_ylabel("Action (normalized delta)")

        # Convergence
        if self.diff_history:
            ax2.plot(self.epoch_history, self.diff_history, marker=".")
            # 使用 symlog 避免 diff 為 0 時報錯，並設定一個極小的線性閾值
            ax2.set_yscale("symlog", linthresh=1e-8)
            ax2.set_title("Policy Convergence (Log)")

        plt.tight_layout()
        fig.savefig(os.path.join(self.output_dir, "plot.png"))
        plt.close(fig)

    def _save_status_json(self, diff):
        status_path = os.path.join(self.output_dir, "status.json")
        with open(status_path, "w") as f:
            json.dump(
                {
                    "epoch": self.epoch,
                    "diff": diff,
                    "target_range": [self.y_low, self.y_high],
                },
                f,
            )
