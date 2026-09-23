# 科学 Gym 的 reward：源码核实与 MatLabGYM 建议

核实日期：2026-09-23。以下结论来自官方仓库的实现，不从 README 推测；范围限定为列出的环境和执行路径。源码以 commit 固定，未运行这些上游环境。

| 实现 | 实际目标与结算方式 | 成本处理 | success / 终止与 reward 的关系 |
|---|---|---|---|
| ChemGymRL `GenBench` + `RewardGenerator` | 主目标为终止结算 `F(s_T)-F(s_0)`；中途仅离散动作错误反馈可罚分。`F` 可为产量或产量×纯度，属于稀疏终点奖励加事件惩罚。 | 每个反馈码 `-1` 加 `-0.1`；所核实路径无金钱/每步时间线性扣分，步数上限直接终止。 | `done` 来自终止动作或步数耗尽，返回空 `info`，没有独立科学成功判定。不能把 `done` 当达标。 |
| ScienceWorld `GoalSequence` + Python `step` | 完成有序/无序子目标累积 progress score；每步 `reward=score_t-score_(t-1)`。这是里程碑式 shaping，未推进目标的动作通常为零。 | 所核实公式无固定动作费；moves 超限结束。任务失败把 score 设为 `-100`，形成一次负分差。 | `isCompleted` 返回值同时覆盖任务完成、超步数和失败；单步正 reward 只说明进展。 |
| BoxingGym `DirectGoal`（Dugongs）+ `iterative_experiment` | 在指定实验次数检查点评估预测 MSE，越小越好；环境实验返回观测和执行布尔值，没有每次实验的 Gym reward。 | 外层限制实验轮数；无效输入可以重试，故轮数不是严格的工具调用数；此路径未将费用折算进 MSE。 | `run_experiment` 的 `success=True` 仅表示输入有效并成功生成观测，与预测准确性无关。 |

## 1. ChemGymRL：产量、纯度与终点改善

固定版本：`ab8227b6b33f13617b7e551bdf6b894df7eec68d`。

设容器 `v` 的目标物质量为 `a_v`，总物质量为 `m_v`，则非纯度模式 `F=Σ a_v`；纯度模式 `F=Σ a_v²/m_v`（仅对 `m_v>0` 累加）。因此后者不是单纯的百分比纯度，而是**产量乘纯度**。溶剂排除、溶解组分折算、指定非目标物扣除均可配置；精确公式见 [`chemistrylab/util/reward.py:71–95`](https://github.com/chemgymrl/chemgymrl/blob/ab8227b6b33f13617b7e551bdf6b894df7eec68d/chemistrylab/util/reward.py#L71-L95)。注意 `exclude_mat` 在平方前扣除，不宜直接把此公式推广为任意有符号性质的 reward。

[`general_bench.py:177–222`](https://github.com/chemgymrl/chemgymrl/blob/ab8227b6b33f13617b7e551bdf6b894df7eec68d/chemistrylab/benches/general_bench.py#L177-L222) 确认：平时没有 `ΔF`；只有 `done` 才加 `F(final)-initial_reward`。初值在 reset 保存（[224–231 行](https://github.com/chemgymrl/chemgymrl/blob/ab8227b6b33f13617b7e551bdf6b894df7eec68d/chemistrylab/benches/general_bench.py#L224-L231)），错误反馈惩罚常量为 `-0.1`（[103 行](https://github.com/chemgymrl/chemgymrl/blob/ab8227b6b33f13617b7e551bdf6b894df7eec68d/chemistrylab/benches/general_bench.py#L103)）。具体反应台使用产量模式（[`reaction_bench.py:45`](https://github.com/chemgymrl/chemgymrl/blob/ab8227b6b33f13617b7e551bdf6b894df7eec68d/chemistrylab/benches/reaction_bench.py#L45)），萃取台存在纯度加权模式（[`extract_bench.py:158`](https://github.com/chemgymrl/chemgymrl/blob/ab8227b6b33f13617b7e551bdf6b894df7eec68d/chemistrylab/benches/extract_bench.py#L158)）。

## 2. ScienceWorld：子目标进展的差分

固定版本：`e8216d6044e8e39be9fcb185e3b2dfb602584b52`。

设有序子目标数 `n`、已推进索引 `k`、无序子目标数 `m`、已完成数 `u`。未失败时，内部 `S=min(1,k/n+u/[m(n+1)])`，无无序子目标时该贡献为零；失败时 `S=-1`。有序目标全部完成的判定独立检查 `k>=n`。见 [`Goal.scala:95–133`](https://github.com/allenai/ScienceWorld/blob/e8216d6044e8e39be9fcb185e3b2dfb602584b52/simulator/src/main/scala/scienceworld/tasks/goals/Goal.scala#L95-L133)。

Python 先取 `score=int(round(100*S))`，再计算分差，并在 `numMoves>envStepLimit` 或 `score<0` 时强制终止，见 [`scienceworld.py:420–452`](https://github.com/allenai/ScienceWorld/blob/e8216d6044e8e39be9fcb185e3b2dfb602584b52/scienceworld/scienceworld.py#L420-L452)。例如上一步 score 为 40、任务本步失败，则 reward 为 `-100-40=-140`，不能把失败 reward 描述为固定 `-100`。

## 3. BoxingGym：评估损失与实验执行状态分离

固定版本：`b43e38cb03d09c13efa9cf4d9bae740d51157bfd`。

Dugongs 的预测评价计算 `MSE=mean((prediction-measurement)²)`，第二返回量为逐样本平方误差的标准差，不是均值的标准误，见 [`dugongs.py:56–72`](https://github.com/kanishkg/boxing-gym/blob/b43e38cb03d09c13efa9cf4d9bae740d51157bfd/src/boxing_gym/envs/dugongs.py#L56-L72)。实验本身返回 `(length,True)`，非法输入返回 `(error,False)`，见 [273–279 行](https://github.com/kanishkg/boxing-gym/blob/b43e38cb03d09c13efa9cf4d9bae740d51157bfd/src/boxing_gym/envs/dugongs.py#L273-L279)。

外层按 `num_experiments[-1]` 运行轮数，允许失败重试，在指定轮数执行评价；EIG 仅在 `check_eig` 时另外记录，并未在该循环作为环境 reward 返回，见 [`run_experiment.py:105–144`](https://github.com/kanishkg/boxing-gym/blob/b43e38cb03d09c13efa9cf4d9bae740d51157bfd/run_experiment.py#L105-L144)。这里应称为“实验预算下的预测评估”，不应强行归类为逐步稠密 RL reward；其他任务的损失需分别核实。

## 对 MatLabGYM 的实现建议

1. **先确定科学目标，再组合效率项。** 对优化任务定义可解释的连续质量 `Q`（例如测得性质相对基线的改善、距离目标区间的距离），记录单位、方向、归一化和上界；对建模任务可单独报告 held-out MSE。操作完成计数不能替代科学质量。
2. **把终止、执行成功、科学成功分开。** 操作 `completed` / 请求成功不等于 task success；科学成功由有效终点证据及阈值定义。预算耗尽应独立记录，不能仅从 reward 正负反推成功。
3. **推荐证据驱动的增量奖励。** 完成并提交可核验的测量后更新 `Q_best`，可用 `r_quality=Q_best,new-Q_best,old`；重复读取同一报告、重放相同请求、无新证据等待均不再获质量奖励。若选择终点结算，也应明确采用 `Q_final-Q_initial` 并只结算一次。这是本项目建议，不是三者共有实现。
4. **成本使用实际增量。** 总 reward 可配置为 `r_quality + one_time_success_bonus - λc·Δcost - λt·Δlogical_time + invalid_penalty`，将各分项写入日志。费用/时间在哪里计入，就在哪里扣一次；避免 start 与完成重复收费，异步工作应明确时间成本采用墙钟逻辑时间还是设备占用量。
5. **避免为容易重复的中间步骤无限给分。** 必要里程碑应按任务/工件 lineage 去重；如继续奖励每个完成事件，应有明确界限并检查反复制造低价值工件是否获利。只有科学有效、来源可追踪的 endpoint 才能推进质量与成功状态。
6. **冻结 reward 版本并同时报告原始指标。** 沿用 manifest 内 reward 配置；评估同时给出科学质量、成功率、成本、时间和总 return。差分 reward 在不折扣求和时可望远镜相消；若训练使用 `γ<1`，不能把普通 `ΔQ` 自动宣称为策略不变的 potential shaping。
