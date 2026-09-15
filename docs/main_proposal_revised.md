# MatLabGym 面向材料自主研发的可验证虚拟实验环境

## 0. 项目定位与第一阶段结论

MatLabGym 是一个面向 Scientific Agent 的、可重放且可审计的材料科学 sequential decision environment。它不把“生成一个看起来合理的实验方案”当作核心能力，而是要求 agent 在明确的实验约束、有限资源和隐藏 scientific outcome 下，完成：

```text
Research goal
  -> observe public state
  -> plan / decide
  -> validate and dispatch
  -> start and complete an experiment
  -> reveal evidence
  -> update hypothesis
  -> continue, drop, retest, validate, replan or stop
```

第一阶段采用“环境简单、任务复杂”的策略：先实现一个确定性、无 GPU、无 API key 依赖的 state-transition engine 和 electrolyte replay backend，再接入真实数据、PyCalphad、PyBaMM 和真实自主实验平台。这样可以先验证接口、隔离、约束、长程记忆和评价协议，再增加模型和物理复杂度。

<text color="red">第一阶段不声称已经拥有真实材料性能预测能力，也不把未经验证的 predictor、LLM Judge 或手写 reward 当作 Ground Truth。</text>

## 1. 项目目标与非目标

### 1.1 目标

MatLabGym 需要回答五个可检验的问题：

1. Agent 能否把高层研究目标分解成满足前置条件、参数范围、资源约束和终止条件的 workflow？
2. 实验结果返回后，agent 能否选择具有科学价值的下一步，而不是机械执行固定 protocol？
3. 在有限实验预算、样品数量、设备槽位和时间约束下，agent 能否达到目标并控制成本？
4. 任务难度自适应和 harness 演化能否减少达到固定能力阈值所需的 episodes、tokens、compute 和 wall-clock time？
5. 虚拟环境中的能力排序能否预测真实平台的执行风险，或者至少能通过小规模 calibration set 解释 sim-to-real 差异？

### 1.2 非目标

- 不在第一版覆盖任意材料、任意新配方和任意实验协议。
- 不把未测过的实验条件交给未经校准的 ML predictor 并称为真实结果。
- 不以单一 reference workflow 或专家 action exact match 作为主要正确性标准。
- 不在没有真实成本字段时虚构金钱、时间、通量或样品消耗数值。
- 不在基础环境尚未通过 replay、validator 和 baseline 验收前直接宣称 RL 或 multi-agent 有效。

## 2. 评审意见的落实决策

本节将主文档 comment 转化为工程和研究约束，避免意见只停留在讨论层面。

1. <text color="red">Reward、时间、价格和通量</text>：科学目标是硬约束，时间、金钱、样品和设备占用是次级优化目标。任务 evaluator 先判断目标是否达成，再在可行轨迹中比较 cost、duration、sample consumption、throughput 和 information efficiency。数据没有真实成本时只使用 `unit query cost = 1`，并把指标命名为 sample efficiency，不称为真实实验成本。
2. <text color="red">Reset 参数和隔离</text>：`reset` 至少接收 `task_spec`、`seed`、`budget`、`resource_config`、`oracle_snapshot`、`observation_perturbation` 和 `workspace_policy`。每个 episode 创建独立 workspace、数据库 namespace、artifact 目录和 RNG 状态；agent 不得读取其他 episode 的上下文、隐藏 outcome、evaluator 或答案。
3. <text color="orange">Multi-agent</text>：第一版使用单一 executor policy 作为基线，先验证环境和 evaluator。后续可以加入 role-separated proposer、planner、executor 和 verifier，但 multi-agent 不是环境成立的前提，且必须单独报告协作增益和额外成本。
4. <text color="orange">预测模型作为 skill</text>：允许 agent 根据已经观察到的历史 evidence 训练候选生成器或 surrogate skill。surrogate 只能产生带不确定性的建议，不能写入 hidden outcome、修改 oracle 或绕过 validator；训练数据范围、模型版本、校准集和 OOD 误差必须记录在 provenance 中。
5. <text color="orange">Curriculum 与 harness 自进化</text>：把“学得越快”具体化为达到预注册能力阈值所需的 episodes、tokens、compute 和 wall-clock time。executor agent/harness 是 policy，skill 是动作接口和状态转移契约，environment 是被评估的世界模型。环境和 agent 可以提出任务或策略，但必须通过 immutable holdout、回归、安全和反投机测试后才能接受。
6. <text color="yellow">业务方 skill registry</text>：业务方/实验平台 owner 提供 workstation、operation、SOP、参数范围、样品和容器 I/O、失败码、设备容量和安全边界，并对版本负责；工程侧负责 schema、校验、版本、trace 和 replay。文献只能提供约束类别，不能替内部平台填写具体数值。
7. <text color="orange">Ray 并发</text>：Ray 用于并行 episode、seed、任务变体和候选评估，但每个 actor 必须有独立 workspace、artifact 目录和资源配额。并发不能改变单 episode budget、seed 语义、evaluator 或 hidden test。
8. <text color="green">第一版环境简单、task 复杂</text>：保留此策略。复杂度优先放在任务组合、依赖、资源冲突、观测延迟、异常恢复和跨轮次重规划，而不是一开始引入不可验证的高保真材料模型。

## 3. 三层问题定义

| 层级 | 研究问题 | Ground Truth | 第一阶段状态 |
| --- | --- | --- | --- |
| Planning | workflow 能否在真实约束下执行并到达目标状态？ | skill contract、precondition、state transition、platform constraint、goal predicate | 必须实现 |
| Decision | evidence 返回后下一实验、候选或验证阶段是否有价值？ | hidden measured outcome、validated simulator 或真实实验 outcome | 先做 replay |
| Scientific world | action 后实验结果是什么？ | real-data replay、validated physics、hybrid 或 real-lab adapter | 按 fidelity 注册 |

三层共用 `TaskSpec`、`Action`、`Observation`、`StepResult`、trace 和 provenance，但 evaluator 分开。Planning 的合法性不能替代 scientific outcome，scientific outcome 也不能自动证明设备已经执行。

## 4. 统一 Environment API

环境内核采用 Gymnasium 风格的最小接口；`plan` 是 agent/harness 的能力，不作为环境可信性的组成部分。

```python
observation = env.reset(task=task_spec, seed=seed)
observation = env.observe()
result = env.step(action)
final = env.stop(reason="goal_reached")
```

每次 `step` 返回：

```json
{
  "observation": {},
  "reward": 0.0,
  "terminated": false,
  "truncated": false,
  "info": {
    "valid": true,
    "endpoint": "completed",
    "scientific_outcome": {},
    "cost": {"experiments": 1, "time": null, "money": null, "sample": null},
    "failure_reason": null,
    "provenance": {}
  }
}
```

### 4.1 TaskSpec

```json
{
  "task_id": "electrolyte.conductivity.v0",
  "version": "0.1",
  "instruction": "Find a formulation above the target within budget",
  "initial_state": {},
  "tools": ["measure_conductivity"],
  "hidden_parameters": {"outcome_table": "sha256:..."},
  "success_predicate": {"metric": "conductivity_ms_cm", "op": ">=", "value": 12.0},
  "safety_predicate": {"invalid_action": "reject", "out_of_table_query": "reject"},
  "max_steps": 5,
  "budget": {"experiments": 5},
  "split": "train"
}
```

任务、oracle、skill registry、reward/evaluator、seed schedule 和数据 split 都写入不可变 manifest，并由 hash 标识。训练、开发和 hidden test 的 outcome store 分离。

### 4.2 Skill contract

每个真实平台操作必须包含：

```text
name
typed inputs and parameters
units and valid ranges
preconditions
required samples / containers / equipment
duration and cost, if observed
outputs and postconditions
state effects
failure modes and recovery skills
safety limits
source provenance and effective version
```

平台数值来自设备 API、SOP、配置或审计后的日志。没有证据的 capacity、温度、时长和价格必须标记为 unknown，不能由模型或工程师随意填充。

## 5. 可执行性与证据端点

参考 robotic chemistry stress test 中“计划得分高但无法 dispatch”的问题，MatLabGym 将实验状态拆成四个端点：

| 端点 | 证明的事实 | 不可推断的事实 |
| --- | --- | --- |
| `plan_materialized` | 生成了结构化计划 | 计划合法或实验开始 |
| `dispatch_verified` | task、tool、设备和参数通过调度校验 | 设备已经执行 |
| `started` | 平台返回明确的开始确认 | 实验已经成功完成 |
| `completed` | 有终态、返回数据和 provenance | 数据一定科学可信 |

固定分母统计四个端点的 funnel；无法评分的 trial 记为 0，并保留失败 artifact。专家评估可以作为 advisory signal，但不能取代结构化 validator、平台回执和 scientific oracle。

## 6. Planning Track 长程实验规划

### 6.1 Environment 状态

```text
Material state：配方、组成、结构、候选池、已知 evidence
Sample state：样品身份、数量、纯度、处理历史、容器绑定
Lab state：设备状态、容量、占用、维护、可用参数范围
Experiment state：假设、预算、时间、阶段、终止条件、失败历史
```

每个操作是一个状态转移：


```text
(state_t, action_t) -> validator -> state_{t+1}
```

例如 `cycle(cell_001)` 在 `cell_001` 尚未组装时必须返回 `precondition_error`，不能通过自然语言描述把不存在的样品“补出来”。容器从 `uncapped` 到下一个需要 `capped` 的工作站之间，必须存在合法 `recap` 操作；样品换容器必须有显式 transfer。

### 6.2 任务生成

任务优先从真实成功和失败 workflow 反向构造：保留 initial state 和 terminal goal，隐藏中间操作，要求 agent 在状态机中找到任意合法路径。难度不预先平均设定为 10/20/30/50 steps，而是先统计内部真实 operation-length 分布，再加入：

- dependency depth；
- constraint density；
- resource scarcity；
- branching factor；
- state memory；
- failure rate；
- observation delay 和 missingness；
- 与训练材料/设备的 domain shift。

### 6.3 Planning 指标

```text
plan materialization rate
valid action rate
precondition satisfaction rate
dispatch verification rate
started rate
completed rate
goal success rate
partial subgoal score
failure recovery rate and recovery cost
repeated invalid-action rate
```

主要成功条件是最终 state 满足 goal predicate，而不是和某一条 reference workflow 做 exact match。

## 7. Decision Track 证据驱动决策

真实材料研发不是一次生成 protocol 后执行到底，而是：

```text
experiment -> evidence -> hypothesis update -> continue / drop / retest / validate / replan / stop
```

### 7.1 V0 电解液 replay

第一版使用经过数据卡和质量审计的历史 electrolyte conductivity/EIS 数据。Agent 只能查询数据中实际测量过的 `(formulation, condition)`；未测条件返回 `oracle_missing_outcome`，不能调用一个未经校准的 predictor 补值。

建议任务：

1. **Candidate selection**：固定实验预算内找到 conductivity 最高或达到阈值的 formulation。
2. **Temperature characterization**：选择有限温度点，尽量恢复关键温度区间。
3. **Continue / drop / retest / validate**：在廉价筛选、中等验证和昂贵验证之间管理 candidate lifecycle。
4. **Evidence-driven replanning**：当新结果与当前 hypothesis 冲突时，选择复测、替代表征、淘汰候选或改变 workflow。

### 7.2 Decision Ground Truth

同一个 state 下可能有多个合理 action，因此不使用 action exact match。对于静态 replay：

```text
simple_regret = oracle_optimum - best_found
experiments_to_target = first step reaching target
Top-k recall = discovered true top-k / k
budget-constrained success = goal reached within budget
```

Expected Information Gain 只有在存在显式 generative model 或经过验证的 physics backend 时才启用。仅凭 GP 或 surrogate 的方差不能称为真实 information gain。

### 7.3 RL 的使用边界

静态 outcome table 更接近 Bayesian optimization、active learning 或 bandit，不强行使用 RL。只有当 action 改变未来 state、资源、候选阶段或可行 action 集合时，才进入 RL/model-based RL：

```text
DecisionEnv-v0：real-data replay -> random / greedy / BO / LLM / bandit
DecisionEnv-v1：stateful campaign -> RL / model-based RL / LLM+RL
```

## 8. Scientific Oracle 与多 fidelity backend

Oracle 和 environment 解耦，统一表示为：

```text
(material_state, experimental_action) -> scientific_outcome
```

### Level 0：Real-data replay

结果来自真实已完成实验；优点是 outcome 真实性强，缺点是 action space 受数据覆盖限制。

### Level 1：Validated physics simulator

AlloyEnv 可以使用 PyCalphad，CellEnv 可以使用 PyBaMM，但 solver、数据库和 parameter set 必须分别登记。PyCalphad 不是自动 Ground Truth，PyBaMM 也不代表所有 cell chemistry；只有在明确 composition/protocol regime 内与内部或文献实验校准后，才能注册为 benchmark backend。

### Level 2：Hybrid oracle

用真实数据估计 physics model 的 discrepancy，并公开 calibration set、误差、适用范围和不确定性语义。hybrid oracle 的 counterfactual 能力不能超过校准范围。

### Level 3：Real-lab adapter

真实平台返回 measurement、设备回执和失败原因。必须区分 `dispatch_verified`、`started` 和 `completed`，保存原始 task id、设备日志、返回数据和时间戳。

每个 oracle 都要有 oracle card：

```text
oracle_id
backend_type
dataset / model / database version
valid composition / temperature / protocol regime
calibration set and metrics
known failure modes
uncertainty semantics
license and provenance
```

## 9. 三个优先场景

### 9.1 ElectrolyteEnv：第一版核心

使用真实自动化 conductivity/EIS 数据，先做离散 replay，不预测未覆盖的 formulation。没有真实 duration、money 或 sample consumption 时，成本只表示 query count；接入内部日志后再增加实际成本。

### 9.2 AlloyEnv：通过校准门槛后接入

第一任务只优化 target phase fraction、undesired phase constraint 或 phase-window identification。不要在同一个 CALPHAD oracle 中同时宣称 strength、density、ductility 和 corrosion 可靠。

### 9.3 CellEnv：作为动态 RL 场景

固定一个已验证 parameter set 或真实 cycling trajectory，支持 `charge`、`discharge`、`rest`、`hold_voltage` 和 diagnostic。初始任务为 charging protocol optimization 或 system identification；长期 degradation 任务需要单独的真实数据和 validation protocol。

正极和负极先作为 controlled-family historical replay extension，只比较同一 SID、相同上下游材料、相同 cell type 和可比 protocol 下的受控差异。

## 10. 防作弊、隔离和安全

每个 episode 都必须拥有：

```text
独立 workspace
独立数据库 namespace
独立 artifact 目录
独立随机数状态
只读的 task/evaluator manifest
隐藏 outcome store
```

agent 不得：

- 读取 hidden labels、evaluator 源码或其他 episode 的 trace；
- 修改 oracle、reward、任务生成器、hidden test 或安全边界；
- 将未执行动作写成已完成实验；
- 删除失败 artifact 或覆盖 provenance；
- 用重复非法动作消耗时间后伪造进展。

stress suite 加入 schema/单位扰动、缺失或延迟 observation、tool timeout、设备 unavailable、资源冲突、异常 outcome、陈旧/矛盾 evidence 和恶意 notebook/comment/tool-return 内容。安全违规单独计分，不与科学失败混为一谈。

## 11. Curriculum 与协同进化 harness

### 11.1 Curriculum manager

任务带有 difficulty vector：

```text
d = (horizon, dependency_depth, constraint_density,
     resource_scarcity, uncertainty, failure_rate,
     branching_factor, state_memory, domain_shift)
```

manager 根据最近窗口的成功率、错误类型、learning progress、任务成本和 OOD 覆盖度，优先选择略高于当前能力但仍能从反馈中学习的任务。任务晋级前必须验证可解性、success predicate、难度增量和 hidden-answer 隔离。

### 11.2 Evolution harness

```text
Environment proposer -> 提出任务、约束和扰动
Agent proposer       -> 提出 workflow、策略或最小 harness patch
Verifier              -> 检查 schema、状态、可解性和科学边界
Adversarial tester    -> 搜索 shortcut、reward hacking 和安全违规
Gatekeeper            -> 在 train/dev admission 前执行回归门槛
Archive               -> 保存任务、trace、版本、seed 和失败类型
```

环境和 agent 可以“自己设计、自己商量”，但只能在 contract 内提议。不可变 core test、hidden outcome、evaluator、oracle 参数和安全规则由独立 gatekeeper 管理。未来允许 harness patch 时，每个 patch 必须是最小 diff，并在 held-in、held-out、regression 和 security suite 上同时通过。

## 12. 评价协议与实验矩阵

### 12.1 基线顺序

1. scripted canonical workflow：验证 state machine 和 evaluator。
2. random all actions：验证非法动作、失败码和 budget 语义。
3. random legal action：验证基础成功率。
4. greedy、grid/Latin-hypercube 和 BO/UCB/EI：作为 Decision baseline。
5. structured LLM planner 和 ReAct/tool agent：验证语言模型增益。
6. RL/model-based RL：仅用于真正 stateful 的 V1+ environment。

### 12.2 报告规范

- 预注册 seed list；每个 episode 独立 seed 和 workspace。
- 训练、开发、测试 task manifest 分离；hidden test 不在训练或调参中使用。
- 报告 per-episode 原始 artifact、mean、standard deviation 和置信区间。
- 同时报告最终能力、成本、学习速度、OOD 泛化、failure taxonomy 和 reward hacking rate。
- 任何 rerun 必须说明是网络/API/基础设施失败还是科学失败；不得静默删除失败运行。

### 12.3 学习速度

“学得越快”定义为在固定能力阈值下最小化：

```text
episodes-to-threshold
tokens-to-threshold
compute-to-threshold
wall-clock-time-to-threshold
```

跨任务学习时增加 held-out transfer、forgetting/regression、FWT、NBT、AUC 和 task-order sensitivity，不能只报告训练 loss。

## 13. 里程碑与验收门槛

### M0：可复现内核

完成 typed contracts、reset/observe/step/stop、planning validator、replay oracle、seed/reset、workspace 隔离、trace/replay、scripted/random baseline、单元测试和 README。

验收：同 seed 完整 trace 和 metrics 一致；非法 action、重复测量、错误前置条件有结构化错误码；失败 artifact 不丢失。

### M1：真实电解液 replay

完成数据卡、license、schema mapping、质量审计、train/dev/test split、hidden outcome store、random/greedy/BO baseline 和 regret/AUDC/Top-k 报告。

### M2：多阶段 evidence-driven decision

加入 candidate lifecycle、continue/drop/retest/validate/stop、异常和矛盾 evidence、alternative characterization、replanning 指标以及单位 query cost 与真实 cost 的区分。

### M3：AlloyEnv 或 CellEnv 二选一

根据数据库/验证集先到位者选择。AlloyEnv 先做 phase constraint；CellEnv 先做 charging/system identification。未通过 calibration gate 不进入主 benchmark。

### M4：并发与协同进化

用 Ray 并行 episode/seed，加入 curriculum manager、proposer/verifier/gatekeeper、immutable holdout、adversarial tester 和回归报告。

### M5：真实平台校准

完成至少一个 backend 的 real-lab adapter，报告虚拟指标与真实 dispatch/start/completed 结果的相关性、失配类型和校准建议。

## 14. Repo 与当前实现

GitHub 仓库 `https://github.com/Eleanor825/MatLabGYM` 从空仓库开始，当前已包含：

```text
typed Action / Observation / StepResult / TaskSpec
PlanningEnv：前置条件和状态转移 demo
ElectrolyteReplayEnv：fixture outcome 与 CSV replay 接口
deterministic seed/reset
trace/replay 和 regret 指标
unit tests
README 和本 proposal
```

fixture oracle 只用于工程 smoke test，不代表真实 conductivity。接入真实数据时必须保留 outcome provenance、数据版本和 license；接入 PyCalphad/PyBaMM 时必须增加 calibration report。

## 15. 风险与责任边界

| 风险 | 缓解措施 | 责任方 |
| --- | --- | --- |
| 把 surrogate 当 Ground Truth | oracle card、calibration gate、hidden replay | 工程 + 科学负责人 |
| hidden outcome 泄漏 | episode namespace、只读 manifest、独立 evaluator | 工程 |
| dispatch 被误报成完成 | endpoint funnel 和平台回执 | 平台 owner + 工程 |
| 成本数字虚构 | 无字段只用 unit query cost | 科学负责人 |
| skill 约束过时 | 业务方签署 registry、版本和变更记录 | 业务方 |
| 多 agent 混入基础结果 | 单 agent baseline、独立协作 track | 研究负责人 |
| Ray 并发改变实验语义 | resource quota、独立 seed/workspace | 工程 |
| curriculum/harness 互相刷分 | immutable test、独立 gatekeeper、adversarial test | 研究负责人 |
| 内部数据泄漏 | 脱敏、最小字段、私有 evaluator | 数据 owner |

## 16. 参考工作

- Guo et al. (2026), *Stress-testing large language model agents in a robotic chemistry laboratory*. arXiv:2607.23045. https://arxiv.org/abs/2607.23045
- Wang et al. (2022), *ScienceWorld: Is your Agent Smarter than a 5th Grader?* EMNLP. https://aclanthology.org/2022.emnlp-main.775/
- Beeler et al. (2024), *ChemGymRL: A customizable interactive framework for reinforcement learning for digital chemistry*. Digital Discovery. https://doi.org/10.1039/d3dd00183k
- Jansen et al. (2024), *DISCOVERYWORLD*. NeurIPS Datasets and Benchmarks. https://arxiv.org/abs/2406.06769
- Cerrato et al. (2026), *Science-Gym: a simple testbed for AI-driven scientific discovery*. Machine Learning. https://doi.org/10.1007/s10994-025-06914-x
- Dave et al. (2022), *Autonomous optimization of non-aqueous Li-ion battery electrolytes via robotic experimentation and machine learning coupling*. Nature Communications. https://doi.org/10.1038/s41467-022-32938-1
- ScienceAgentBench. https://arxiv.org/abs/2410.05080
- DiscoveryBench. https://arxiv.org/pdf/2407.01725
