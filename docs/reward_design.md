# 可配置 reward：第一阶段实现

Reward 是实验设计的一部分，由我们选择目标、权重和版本。Oracle 提供可观测结果；evaluator 独立计算目标是否达到、best-found、simple regret 和有效实验数。改变 reward 不修改数据、目标阈值或 evaluator。

源码依据见 [scientific_gym_rewards.md](scientific_gym_rewards.md)。当前实现借鉴终点质量改善与进展差分，不宣称复现任一上游 Gym。

## 电导率 replay 的三个预设

对最大化任务，令 `B_t` 为本 episode 已测得的最佳性质，`b` 为事先配置的 baseline，`s>0` 为事先配置的 scale：

```text
Q_t = (max(b, B_t) - b) / s      # 未测量时 Q_0 = 0
r_t = goal_bonus × first_target_reached
    + improvement_weight × (Q_t - Q_(t-1))
    - measurement_cost × valid_query
    - invalid_penalty × invalid_action
```

当前环境达标立即终止，因此 goal bonus 只支付一次。差分只在成功取得新观测时支付；相同 measurement key 再次查询被拒绝，不消耗测量预算，也没有质量奖励。这里的重复查询规则不代表真实复测；带噪声复测需要独立的 replicate action/data contract。

| 预设 | 目标奖励 | 质量改善权重 | 每次有效查询扣分 | 无效动作扣分 |
|---|---:|---:|---:|---:|
| `ReplayRewardSpec.sparse_goal()` | 1 | 0 | 0 | 1 |
| `ReplayRewardSpec.improvement()` | 1 | 1 | 0 | 1 |
| `ReplayRewardSpec.cost_aware()` | 1 | 1 | 0.05 | 1 |

所有列及 baseline、scale、version 均可覆盖。数值是设计默认值，不是从文献或真实实验估计的最优权重。`scale` 必须由公开任务先验设定，不能查询 hidden optimum；默认环境采用 `abs(target)`（目标为零或未设置时为 1）。性质低于 baseline 时没有质量改善奖励，应按 domain 选择合理 baseline。该标量奖励允许效率与目标权衡；严格目标优先的排名应使用独立指标，不要靠任意权重保证。

```python
from matlabgym import ElectrolyteReplayEnv, ReplayRewardSpec, make_fixture_task

task, oracle = make_fixture_task()
reward = ReplayRewardSpec.cost_aware(
    version="conductivity-cost-ablation-v1",
    baseline=0.0,
    scale=12.0,                 # 性质单位为 mS/cm
    goal_bonus=2.0,
    improvement_weight=1.0,
    measurement_cost=0.02,
    invalid_penalty=1.0,
)
env = ElectrolyteReplayEnv(task, oracle, reward=reward)
obs, info = env.reset(seed=7)
```

每步 `info` 和 trace 记录 `reward_components`，其和等于 reward。完整配置、任务、温度和 oracle snapshot hash 纳入 manifest；改变任何权重都会改变 manifest hash，即使忘记修改 version。构造后改变 task/reward 会被拒绝。

无折扣时质量增量相加等于最终质量改善；若训练使用 `gamma<1`，这里的普通差分不保证策略不变。不同 reward 版本的 return 不应直接拿来比较模型优劣。

## 产线执行 reward

原 `RewardSpec(...)` 继续支持 accepted/completed/invalid/stopped/goal 与成本、时间权重。新增 `RewardSpec.sparse_goal()` 和 `RewardSpec.cost_aware()`，关闭中间 completed 奖励，避免仅因更多完成事件或不同 skill 包装获得额外分数。它们仍只评价执行目标，没有科学性能奖励。

```python
from matlabgym.domains import build_electrolyte_line_env
from matlabgym.lab import RewardSpec

env = build_electrolyte_line_env(RewardSpec.cost_aware(
    version="line-efficiency-v1", goal=10.0, cost_weight=0.001,
))
```

兼容旧默认行为，`build_electrolyte_line_env()` 不传配置时仍保留原 completed 奖励。若选择这种密集事件奖励，应专门测试重复制造低价值产物的激励。默认新预设没有这个中间事件奖励，但不能据此声称全面消除 reward hacking。

## 成本、终止与科学声明

- Replay 每次有效测量的成本固定为 `query_cost=1`，标记 `cost_source=proxy`、`cost_unit=measurement_query`；reward 的 measurement_cost 是每单位查询的扣分权重，不是货币成本。
- 产线原成本和逻辑时间仍是模拟配置。不要跨环境直接比较这些 cost 总数。
- 目标达成或候选支持域耗尽属于 `terminated`；预算或动作数上限耗尽属于 `truncated`。同一步达标优先按目标终止。
- `success` 表示当前冻结数据中的阈值达成；CSV 文件导入不自动获得科学校准资格，`scientifically_validated` 保持 False。
- 现有隔离仍是内存对象隔离。向具备任意 Python/文件权限的 agent 开放环境前，需要进程/文件边界隔离 hidden outcome 和 evaluator。

## 运行对比与迁移

```bash
PYTHONPATH=src python3 examples/compare_rewards.py \
  --output /tmp/matlabgym-reward-comparison.json

# 可替换为已获准使用的数据；列沿用 CSVReplayOracle schema
PYTHONPATH=src python3 examples/compare_rewards.py \
  --csv /path/to/measurements.csv --target 12 --budget 5 --seeds 10 \
  --output /tmp/replay-reward-comparison.json
```

示例以相同 seed 比较公开候选顺序与随机策略，在三个 reward 配置下记录轨迹、return、目标达成率、regret、测量数和 manifest。它只检查固定策略的不同 reward 计分，不执行 RL 训练，也不证明某个 reward 会学出更好的策略。默认是单一 synthetic fixture，不能作为科学 benchmark 排名。

v0.3 的 replay API 变化：`reset()` 返回 `(obs, info)`；step 仍返回项目的 `StepResult`，不是完整 Gymnasium Env；支持域只列当前任务温度下允许的动作。trace schema 为 2，默认 reward 从逐次性质值改为 best-so-far 增量。新轨迹可由 `verify_trace` 复核，不应混用旧轨迹。

`run_cohort` / `run_paired_stress` 可传 `policy_factory(slot)`，为每个 episode 创建独立策略；直接 `policy=` 仅适合无内部状态的函数。runner 验证 slot 的 task、manifest 及已登记预算字段与实际环境一致；缺失预算字段为兼容旧调用允许省略，新实验应完整填写 `env.budget_spec`。环境通过 `episode_outcome()` 提供独立汇总，因此 replay 无需伪装成产线 runtime。

v0.4已将配液和表征产物与replay测量接通，见[电解液场景](electrolyte_scenario.md)。下一步冻结真实数据和平台operation参数，再进行策略学习/LLM反馈消融；后四阶段的电芯性能与真实平台集成仍待完成。
