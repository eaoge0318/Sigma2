import numpy as np
import d3rlpy
import os

# Mock data
N = 100
M = 2
states = np.random.randn(N, 10).astype(np.float32)
actions = np.random.randn(N, M).astype(np.float32)
rewards = np.random.randn(N).astype(np.float32)
terminals = np.zeros(N, dtype=np.bool_)

dataset = d3rlpy.dataset.MDPDataset(
    observations=states,
    actions=actions,
    rewards=rewards,
    terminals=terminals,
)

print(f"Dataset actions shape: {dataset.actions.shape}")
print(f"Dataset actions dtype: {dataset.actions.dtype}")
# In d3rlpy 2.x, we check the dataset_info or action_space
print(f"Action space type: {dataset.get_action_size()}")

# Try to see how d3rlpy infers it
from d3rlpy.constants import ActionSpace


def infer_action_space(actions):
    if actions.ndim == 1:
        return ActionSpace.DISCRETE
    else:
        return ActionSpace.CONTINUOUS


print(f"Inferred: {infer_action_space(dataset.actions)}")
