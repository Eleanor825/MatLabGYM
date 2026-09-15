# MatLabGYM 修订建议与可实现研究方案

版本：0.1 · 2026-09-16  
用途：供主文档及三个子文档逐节修改，不直接改动飞书原文

## 1. 结论先行

MatLabGYM 最适合被定义为一个“可验证的材料科学 sequential decision environment”，而不是一个把多个材料模型、LLM、RL 和自动实验平台统称在一起的项目。第一版应先证明一个窄而硬的命题：

> 在固定、可审计的实验协议下，agent 能否从真实历史实验或经过验证的物理后端中选择并执行合法实验，并在证据返回后以更少的实验预算达到科学目标？

建议把现有三份子文档重新组织为一条闭环：

```text
Long-horizon planning
  -> executable workflow
  -> dispatch / start / completion evidence
  -> scientific oracle returns outcome
  -> evidence-driven decision
  -> replan or stop
```

关键取舍如下：

1. **第一版只承诺一个可运行环境**：`ElectrolyteReplayEnv-v0`。使用经过审计的历史 conductivity/EIS 数据时，只允许查询实际测过的 `(formulation, condition)`，不在未覆盖区域伪造预测值。
2. **规划和决策分成两个 benchmark track**。规划 track 评价状态转换和可执行性；决策 track 评价 regret、sample efficiency、target recall 和停止/复测/验证选择。两者共用 task、action、trace 和 provenance schema。
3. **所有“实验完成”必须分层**：`plan_materialized`、`dispatch_verified`、`started`、`completed`。`dispatch` 不是实验已开始，专家判断的可执行性也不是返回了实验数据。
4. **RL 后置**。静态 replay 更接近 Bayesian optimization、active learning 或 bandit；只有当 action 改变未来状态（样品耗尽、validation stage、设备占用、电芯退化）时，才将问题作为 RL 或 model-based RL。
5. **科学 oracle 与 reward 解耦**。oracle 返回测量/模拟结果；任务 evaluator 再由结果计算成功、regret、成本和约束惩罚。不能把手写 reward 叫作 ground truth。
6. **训练环境可自适应，测试环境必须冻结**。任务 proposer、curriculum manager 和 agent 可以提议任务，但不能修改 hidden test、oracle、评估器、安全边界或测试答案。

## 2. 阅读范围与证据边界

本建议对照了：

- 主文档《MatLabGym：面向材料自主研发的可验证虚拟实验环境》；
- 子文档 1《针对长程实验任务的规划》；
- 子文档 2《针对长程实验任务的决策》；
- 子文档 3《材料性能模拟》；
- 目标论文及其代码/数据仓库；
- ScienceWorld、ChemGymRL、DISCOVERYWORLD、Science-Gym、ALFWorld、RoboCasa、LIBERO、ScienceAgentBench 和 DiscoveryBench 的公开论文或官方仓库；
- `https://github.com/Eleanor825/MatLabGYM` 的远程仓库状态。

本次已通过飞书 MCP 读取主文档的 7 条未解决批注；三个子文档当前没有独立批注。批注集中在：成本/时间/通量与 reset 参数、episode/workspace 隔离和防作弊、multi-agent 是否必要、预测模型能否作为 skill、curriculum 与 harness/skills 自进化、业务方参与 skill registry、Ray 并发以及“环境简单、task 复杂”的第一版策略。以下建议逐条回应这些意见，并把仍需业务方确认的事项列在第 14 节。

仓库审计结果：`MatLabGYM` 是公开但完全空的仓库，没有可保留的源码、入口、依赖、测试或 CI。因此本建议把实现视为 greenfield，并把初始 scaffold 作为 M0 交付，而不是假设已有能力。

## 3. 文档间的核心问题

### 3.1 目标层级没有被固定

主文档同时谈 planning、decision、curriculum、co-evolution、electrolyte、alloy、cell 和真实平台，容易让读者误以为这些能力都在第一版同时可交付。三个子文档其实已经给出了正确的分层，但需要把它们提升为主文档的顶层结构：

| 层 | 科学问题 | ground truth | 第一版状态 |
| --- | --- | --- | --- |
| Planning | workflow 是否能按真实约束执行并到达目标状态？ | skill contracts、preconditions、state transitions、platform constraints、goal predicate | **必须实现** |
| Decision | evidence 返回后下一实验/候选/阶段是否有价值？ | hidden measured outcomes、validated simulator 或 real-lab outcome | **先做 replay** |
| Scientific world | action 后真实/物理结果是什么？ | real-data replay、validated physics、hybrid 或 real lab | **按 fidelity 注册** |

建议在主文档开头加入“能力边界声明”，并删除容易造成过度承诺的表达，例如“覆盖所有材料”“训练 agent 学会材料研发”或“simulator 即 ground truth”。

### 3.2 “长程”缺少可检验定义

不能只用 10/20/30/50 步人工设定长短。子文档 1 已指出，应先统计内部真实 operation-length 分布，再按分位数或业务阈值定义 short/medium/long。建议同时记录：

```text
horizon              操作数
dependency_depth     最长前置依赖链
constraint_density   每一步可触发的约束数
resource_scarcity    资源/设备紧张程度
branching_factor     合法可选动作数
state_memory         需要跨多少步记住样品/设备状态
uncertainty          观测噪声或结果不确定度
domain_shift         与训练任务的距离
```

“长程能力”应报告一条随 horizon、约束密度和 OOD 距离变化的曲线，而不是只报告一个总分。

### 3.3 可执行性、科学合理性和实验完成被混在一起

Guo 等人的 robotic chemistry stress test 是本项目最重要的警示：45 个模块化工作站暴露为 machine-readable skills，4,608 次 trial 中只有 3.3% 被专家判定为满足约束的可执行 workflow，最佳配置也只有 28.1%；只有 3 条 workflow 超过 30 个 operation，最长 44 个 operation。论文还显示，高 JSON/semantic 分数不保证 dispatch，dispatch 也不证明实验已开始或完成。

MatLabGYM 必须在 schema 中保存以下端点，并分别计分：

| endpoint | 可证明的事实 | 不可推断的事实 |
| --- | --- | --- |
| `plan_materialized` | 生成了结构化计划 | 计划合法或实验开始 |
| `dispatch_verified` | task/tool/设备解析成功且通过调度检查 | 设备已执行 |
| `started` | 有明确 start acknowledgement | 实验已经成功完成 |
| `completed` | 有 terminal status 和返回数据 | 数据一定科学可信 |

主指标建议固定分母，unscorable 记为 0，并同时输出每个端点的 drop-off funnel；不要只统计成功到最后的幸存者。

### 3.4 “合理决策”不应退化为专家 action exact match

两个子文档都正确指出，同一个 state 可能有多条合理路线。主文档应明确：

- planning 不比较生成序列与单一 reference plan 的字符串相似度；
- decision 不比较 agent action 与专家 action 的 exact match；
- 只要 action 合法并导致更好的终局或更高的信息/成本效率，就应被计入；
- 如果存在多个等价最优解，应使用 outcome-based evaluator、Pareto frontier 或 regret，而不是单一标签。

## 4. 建议替换后的总体架构

### 4.1 统一接口

建议把主文档 2.1 的 `reset / observe / plan / execute / stop` 收敛为以下最小 API；`plan` 可以是 agent/harness 层能力，不必强行塞进环境内核：

```python
obs = env.reset(seed=seed, task=task_spec)
obs = env.observe()
result = env.step(action)
final = env.stop(reason="goal_reached")
```

`step` 必须返回：

```json
{
  "observation": {},
  "reward": 0.0,
  "terminated": false,
  "truncated": false,
  "info": {
    "valid": true,
    "endpoint": "completed",
    "failure_reason": null,
    "scientific_outcome": {},
    "cost": {"experiments": 1, "time": null, "sample": null},
    "provenance": {}
  }
}
```

### 4.2 TaskSpec

每个任务应冻结为一个可哈希的 `TaskSpec`：

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

任务文件、oracle 文件、skill registry、reward/evaluator 版本和 seed schedule 都必须进入 manifest；不能只靠 prompt 或 README 记忆。

### 4.3 Skill contract

来自真实平台的每个操作都要有机器可读 contract：

```text
name
inputs and typed parameters
preconditions
valid ranges and units
required samples / containers / equipment
duration and cost, if observed
outputs and postconditions
state effects
failure modes and recovery skills
safety limits
source provenance and effective version
```

数值上限必须来自设备 API、SOP、配置或实验日志。文献只能提供 constraint 类型，不能替内部平台填写具体 capacity、温度或时间。

### 4.4 Trace 与 provenance

每条 transition 记录：

```text
episode_id, task_id, env_version, seed
state_before, action, validator_result
oracle_request, oracle_response, state_after
endpoint, reward, cost, failure_reason
model/harness version, timestamp, artifact hashes
```

轨迹必须支持 replay。重放只使用当时指定的 oracle snapshot，不能在事后查询最新数据替换 outcome。

## 5. 第一阶段科学范围

### 5.1 V0：ElectrolyteReplayEnv

子文档 2 和 3 已选出正确的第一场景：自动化实验产生的 electrolyte conductivity/EIS 数据。可采用 Rahmanian 等公开的自动化电解液数据作为数据审计起点，但在数据加载前必须核对 license、列定义、重复测量、异常过滤、温度覆盖和 provenance。数据中没有真实成本、时间或样品消耗时，只能设定 `experiment_cost = 1` 并明确这代表 query/sample efficiency，不代表真实金钱或 wall-clock cost。

V0 的 action space 只包含数据确实测过的 `(formulation_id, temperature)`。返回值优先包含：

```text
conductivity
uncertainty, if present
real/imaginary impedance, if present
source record id and dataset version
```

建议先做三个任务：

1. **Candidate selection**：预算 B 内找到 conductivity 最高或超过阈值的 formulation。
2. **Temperature characterization**：在有限测量次数内恢复一个 formulation 的关键温度点，不要求把整条曲线全部测完。
3. **Continue / drop / retest / validate**：廉价筛选后决定保留、淘汰、复测或进入更昂贵验证。

V0 只使用 replay outcome。Expected Information Gain 只有在存在显式 generative model 或 validated physics model 时才启用；不能训练一个 GP 后把 GP 的信息增益叫作真实 ground truth。

### 5.2 V1：AlloyEnv

AlloyEnv 可以接 PyCalphad，但注册条件应写成 gate，而不是“PyCalphad 等于真实真值”：

1. 确定内部 alloy system；
2. 确认数据库覆盖的 composition/temperature/phase 范围；
3. 用内部或文献 phase data 做 calibration；
4. 报告相分数、相组成、Gibbs energy 的误差；
5. 只在通过 gate 的 regime 注册 benchmark。

第一任务只做 target phase fraction 或 undesired phase constraint，不要在一个 oracle 中同时声称 strength、density、ductility、corrosion 都可靠。

### 5.3 V1.5：CellEnv

PyBaMM 适合动态环境，但应先固定一个已验证 parameter set 和 regime。初版任务可以是 charging protocol optimization 或 system identification：

- action：charge/discharge/rest/hold voltage；
- observation：可测的 voltage/current/temperature/capacity time series；
- hidden state：parameter set 或 degradation state；
- success：达到 SOC/电压安全约束，或恢复 hidden parameter；
- 真实数据版本：使用完整 cycling trajectory replay，隐藏未来曲线。

只有当 action 影响未来 state、资源或后续可行 action 时，才把该 track 用于 RL。否则以 BO/active learning/bandit 作为主要 baseline。

### 5.4 暂缓项

正极/负极 composition 到 cycle life 的开放式性能预测，除非能构造 controlled family（相同 SID、anode/cathode/electrolyte、cell type 和可比 protocol，只改变一个因素）并经过人工审计，否则只做 replay extension，不做任意 composition 的 simulator。

## 6. 评价方案

### 6.1 Planning track

建议同时报告：

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

success predicate 由最终 state 自动判断。允许不同拓扑顺序的合法 workflow；可以用 dependency graph 的覆盖和额外步骤率做辅助分析，但不能把 graph edit distance 当主要正确性。

### 6.2 Decision track

对静态 replay 至少报告：

- `best_found`；
- `simple_regret = oracle_optimum - best_found`；
- `experiments_to_target`；
- `budget_constrained_success`；
- `Top-k recall`；
- discovery curve/AUDC；
- valid action rate、重复测量率和 missing-outcome rate。

对多阶段 decision 再加：

- continue/drop/retest/validate 的阶段正确率；
- contradiction 后 workflow-level replanning 率；
- alternative-characterization 选择率；
- 停止决策的后悔值；
- 资源、样品、时间和设备占用成本。

### 6.3 Curriculum / lifelong track

如果后续支持跨任务学习，借鉴 LIBERO 的 FWT、NBT、AUC 思路，报告：

- `episodes-to-threshold`；
- `tokens/compute-to-threshold`；
- wall-clock time-to-threshold；
- held-out transfer；
- forgetting/regression；
- task-order sensitivity。

“学得越快越好”必须被操作化为固定能力阈值下的资源消耗，而不能只报告训练 loss 或单个 episode 的最高 reward。

## 7. Stress test 设计

### 7.1 基础压力维度

每个维度单独做 ablation，并提供组合 stress suite：

1. hidden parameter variation：配方、温度、设备 regime；
2. unseen task template：表面措辞变换、未见材料 family；
3. observation noise/delay/missingness；
4. unit、schema 和字段顺序扰动；
5. tool timeout、设备 unavailable、资源冲突；
6. invalid action、重复 action、不可逆操作；
7. outlier 或仪器异常；
8. stale/contradictory evidence；
9. untrusted notebook/comment/tool-return prompt injection；
10. budget、样品数量和时间同步约束。

### 7.2 参考 benchmark 的取舍

| 参考环境 | 应借鉴 | 不应直接搬入 |
| --- | --- | --- |
| ScienceWorld | task template、参数 variation、隐藏 OOD、deterministic reset、subgoal score | 小学科学内容、Scala/JVM 依赖、手工 gold path 作为唯一真值 |
| ChemGymRL | bench 模块、跨 bench vessel/state、Gymnasium API、稀疏终局 reward、POMDP | 未校准的玩具反应动力学作为材料真值 |
| DISCOVERYWORLD | hypothesis→experiment→analysis→conclusion 的完整 discovery loop、分层难度、explanatory knowledge score | 直接复制文本世界的常识任务 |
| Science-Gym | collection/design/discovery equation 的统一接口、可解释科学目标 | 其物理题作为材料性能 oracle |
| ALFWorld | 抽象计划层与执行层分离、seen/unseen split、partial goal score | 家居环境和 embodied simulator |
| RoboCasa/LIBERO | atomic skill + composite task、程序生成、multi-seed success、FWT/NBT/AUC | 3D 接触动力学、海量视觉资产 |
| AgentDojo | stateful tool、恶意观测与 utility/security 双指标 | 把 prompt injection 当普通 scientific failure |

### 7.3 失败 taxonomy

至少保留以下互斥主标签，同时允许多标签细分：

```text
schema_error
parameter_range_error
precondition_error
resource_conflict
state_continuity_error
dispatch_error
start_missing
oracle_missing_outcome
oracle_failure
scientific_constraint_violation
poor_candidate_choice
no_replan_after_contradiction
repeated_invalid_action
budget_exhausted
security_or_prompt_injection
```

## 8. Baseline 和实验矩阵

不要第一版直接做“LLM vs RL”。推荐分三层：

### 8.1 验证基线

- scripted canonical workflow：验证 state machine 和 evaluator；
- random legal action：验证环境是否能给出非零成功率；
- random all actions：验证非法动作和错误标签；
- exhaustive oracle：只在小 fixture 上验证 optimum/regret。

### 8.2 决策基线

- random candidate selection；
- greedy best observed；
- grid/Latin-hypercube（如果 action space 可连续采样）；
- Gaussian-process BO / Expected Improvement / UCB；
- simple active learning；
- scripted uncertainty-aware heuristic。

### 8.3 agent 基线

- structured LLM planner with action schema；
- ReAct/tool agent；
- model-based policy；
- RL only for stateful V1+ environments。

每个方法使用相同 task manifest、query budget、seed list、hidden test 和 evaluator。结果至少报告 mean ± std，保存每个 episode 原始 trace，不只保存汇总分数。

## 9. Curriculum 和 co-evolution 的可实现版本

### 9.1 Curriculum manager

任务难度以向量表示；每轮根据最近窗口的成功率、错误 taxonomy、learning progress 和任务成本，采样“略高于当前能力”的任务。任务生成器只能变异：

- 初始状态；
- 合法参数范围内的条件；
- 资源和设备约束；
- 观测噪声/延迟；
- 已审计的 outcome table 或 physics regime。

每个任务进入训练池前需要 verifier 检查：可表达、可执行、至少有一条可行路径、success predicate 可判定、难度增量可解释、不能从 public observation 直接读出 hidden answer。

### 9.2 Evolution harness

第一版只允许提议，不允许任意改代码：

```text
environment proposer -> candidate TaskSpec
agent proposer       -> candidate policy/workflow
verifier             -> schema/state/solvability checks
adversarial tester    -> shortcut/reward-hacking checks
gatekeeper            -> train/dev admission
archive               -> task/trace/version/provenance
```

如果未来开放 harness patch，patch 必须是最小 diff，并在 held-in、held-out、regression 和 security suite 上同时通过；不能因为原题得分上涨就接受修改。hidden test、oracle 参数、evaluator 和安全边界永远不可修改。

## 10. 里程碑和 repo 交付

### M0：可复现内核（当前 demo 已覆盖大部分）

交付：

- typed `Action/Observation/StepResult/TaskSpec`；
- planning state transition engine；
- replay oracle protocol；
- deterministic seed/reset；
- JSON trace/replay；
- scripted/random baseline；
- unit tests；
- README 与一键 demo。

验收：同 seed 的 trace 和 metrics 完全一致；非法 action、重复测量、错误前置条件都能被结构化识别。

### M1：真实电解液 replay

交付：

- 数据 license 和数据卡；
- schema mapping 与质量审计报告；
- train/dev/test split；
- hidden outcome store；
- random/greedy/BO baseline；
- regret、AUDC、target recall 报告。

### M2：evidence-driven multi-stage decision

交付：筛选、复测、验证、停止、冲突证据和 alternative characterization；固定分母的 endpoint funnel；异常/缺失/延迟 stress suite。

### M3：validated AlloyEnv 或 CellEnv（二选一）

不要同时承诺两个新 backend。AlloyEnv 适合先做静态物理约束；CellEnv 适合证明真正的 long-horizon RL。选择标准是数据/数据库和内部验证集先到位者。

### M4：跨域与真实平台校准

在至少一个 backend 通过 calibration gate 后，再做 simulator-to-real ranking correlation；明确虚拟评测不能自动代表真实设备成功率。

## 11. 对主文档和子文档的逐节修改指令

### 11.1 主文档

| 原位置 | 优先级 | 建议修改 |
| --- | --- | --- |
| 0 一句话概括 | P0 | 保留“可验证 sequential decision environment”，增加第一版只做一个可运行 replay backend 的范围句。 |
| 1 项目目标 | P0 | 增加三层能力表；把“预测材料性能”明确改为“由 oracle 提供可审计 outcome”。 |
| 2.1 Environment | P0 | 把 API、TaskSpec、Trace schema 固定；`plan` 放到 harness 层，环境内核只保证 reset/observe/step/stop。 |
| 2.2 Skill schema | P0 | 增加 units、version、provenance、failure/recovery 和 safety；明确平台数值不得凭空填写。 |
| 2.3 Oracle | P0 | 增加 fidelity registration/calibration gate；明确 replay 不能查询未测 action，PyCalphad/PyBaMM 不是自动 ground truth。 |
| 2.4 Reward | P0 | 把 oracle outcome、task evaluator、training reward 三者分段；V0 主报告 regret/efficiency，避免万能 reward。 |
| 3 RQ/Hypotheses | P0 | 将 RQ1 planning、RQ2 decision、RQ3 oracle validity、RQ4 curriculum、RQ5 sim-to-real 分开；RL 假设只用于 stateful 环境。 |
| 4 Curriculum | P1 | 保留 difficulty vector，但用真实 workflow 分布校准 horizon；定义 threshold、FWT/NBT/AUC。 |
| 5 Evolution harness | P1 | 增加 proposer 权限边界、hidden test、独立 oracle、adversarial tester 和最小 patch gate。 |
| 6 场景 | P0 | 改成 V0 electrolyte replay、V1 alloy/cell 二选一、V1.5 controlled replay extension；删除未经数据审计的 episode 数承诺。 |
| 7 评价 | P0 | 增加 plan/dispatch/start/completed funnel、fixed denominator、unscorable=0、failure taxonomy 和 mean±std。 |
| 8 里程碑 | P0 | 改成 M0–M4 的依赖链，明确每个里程碑验收条件和“不通过时不升级”的 gate。 |
| 9 论文关系 | P1 | 加入“符号/约束验证不等于科学 oracle”的边界；把计划验证和材料结果验证分开。 |
| 10 非技术解释 | P1 | 用“材料研发飞行模拟器”比喻时，补充 dispatch 不等于 started/completed、fixture 不等于真实实验。 |
| 11 原则 | P0 | 增加版本冻结、数据卡、数据/模型许可证、不可变 test、泄漏审计和第三方复核。 |

### 11.2 子文档 1：长程实验任务规划

建议保留其“从真实平台反向构建”的核心，但新增三点：

1. 先定义 `WorkflowEpisode` 和 endpoint funnel，再讨论任务生成；
2. 用真实 operation-length 分布而不是预先平均设定 10/20/30/50 steps；
3. 将 platform executability、scientific reasonableness 和 actual execution 分成三个 evaluator。

建议替换结尾总结为：

> Planning environment 的 ground truth 是 skill contracts、state transitions、platform constraints 和 goal predicate 的联合约束。它不要求 agent 复现单一 reference plan，而要求轨迹从初始 state 合法地到达终态；轨迹是否 dispatch、started 或 completed 必须由独立 endpoint evidence 分别证明。

### 11.3 子文档 2：长程实验任务决策

建议保留 replay-first 的判断，并补充：

- candidate selection、measurement selection 和 lifecycle decision 是三个不同 task family；
- replay 环境报告 regret/sample efficiency，不报告未经模型定义的 EIG；
- BO 必须是强 baseline，LLM/RL 不能跳过；
- 真实异常和 synthetic perturbation 分开标注；
- `retest/drop/validate/stop/replan` 的动作必须影响候选 lifecycle state，避免只是自然语言标签。

建议把“RL 到底放在哪里”上移到本节开头，作为 task typing 规则：

```text
static outcome table -> BO / active learning / bandit / structured LLM
stateful campaign    -> RL / model-based RL / LLM+RL
```

### 11.4 子文档 3：材料性能模拟

建议把标题改为“Scientific oracle 与多 fidelity backend”，因为重点不是“模拟越多越好”，而是 outcome 是否经过验证。

必须新增 oracle card：

```text
oracle_id, backend_type, dataset/model version
valid composition/temperature/protocol regime
calibration set and metric
known failure modes
uncertainty semantics
license and provenance
```

电解液、合金、电芯三条路线应分别写清：第一阶段能回答什么、不能回答什么、进入 benchmark 的 gate 是什么。不要在同一 reward 中把 CALPHAD 可给出的 phase fraction 与尚未验证的 mechanical properties 相加。

## 12. 当前 repo 已实现与待实现

当前提交的 scaffold 位于 `MatLabGYM/`：

```text
pyproject.toml
setup.py
README.md
src/matlabgym/core.py          typed contracts
src/matlabgym/electrolyte.py   fixture + CSV replay oracle and decision env
src/matlabgym/planning.py      precondition/state-transition env
src/matlabgym/demo.py          one-command demo
tests/test_environment.py      replay, duplicate, reproducibility tests
```

当前 demo 已实现：

- deterministic `reset(seed)`；
- typed action catalogue；
- hidden outcome reveal；
- invalid action/duplicate measurement rejection；
- planning precondition checks；
- structured endpoint and failure info；
- trace export and replay；
- `best_found`、oracle optimum、simple regret、experiments-to-target、valid action rate。

当前 demo **没有**实现：真实电解液数据、真实实验成本、PyCalphad、PyBaMM、LLM agent、RL trainer、真实设备 dispatch 或 sim-to-real 结论。README 已明确这些限制，后续接入时不得删除。

## 13. 风险登记

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 把 fixture/ML predictor 当 ground truth | 结论失真 | oracle fidelity registry、calibration gate、数据卡 |
| hidden outcome 泄漏 | regret 虚高 | 独立 evaluator、只读 artifact、hash manifest |
| dispatch 被误报为 execution | 过度宣称部署能力 | endpoint funnel、started/completed 证据 |
| BO baseline 缺失 | 无法判断 LLM/RL 增益 | V1 前必须实现 random/greedy/BO |
| 成本数字为人为设定 | 伪造实验效率 | 无真实字段时只用 unit query cost |
| 多 backend 同时开发 | 交付失焦 | M3 二选一，按验证集到位情况决定 |
| curriculum 只按步数增长 | 学习曲线不可解释 | difficulty vector + learning progress |
| agent/environment 互相刷分 | 泛化失效 | immutable test、独立 oracle、adversarial tester |
| 数据 license/provenance 不清 | 无法公开或复现 | 数据卡、许可证、版本 hash |
| 真实平台日志含敏感信息 | 合规/泄漏 | 脱敏、最小字段、访问隔离 |

## 14. 待确认项

这些问题不阻塞当前 scaffold，但在接入真实数据前必须由项目负责人确认：

1. 三个子文档中提到的内部平台具体 workstation/operation registry 是否可导出？
2. 第一批真实实验优先是电解液 conductivity、轻质合金 phase window，还是电芯 protocol？
3. conductivity 数据的正式来源、license、重复测量和异常标记是什么？
4. 内部平台是否有真实 duration、sample consumption、equipment occupancy 和 failure logs？
5. hidden test 的材料 family、设备 regime 和 seed 是否能由未参与训练的负责人冻结？
6. 是否允许将内部真实日志做脱敏后的离线 replay，还是只能在私有 evaluator 中运行？

## 15. 参考资料

1. Guo, L. et al. (2026). *Stress-testing large language model agents in a robotic chemistry laboratory*. arXiv:2607.23045. https://arxiv.org/abs/2607.23045 ；代码和数据：https://github.com/pic-ai-robotic-chemistry/LabBench
2. Wang, R. et al. (2022). *ScienceWorld: Is your Agent Smarter than a 5th Grader?* EMNLP. https://aclanthology.org/2022.emnlp-main.775/ ；代码：https://github.com/allenai/ScienceWorld
3. Beeler, C. et al. (2024). *ChemGymRL: A customizable interactive framework for reinforcement learning for digital chemistry*. Digital Discovery. https://doi.org/10.1039/d3dd00183k ；代码：https://github.com/chemgymrl/chemgymrl
4. Jansen, P. et al. (2024). *DISCOVERYWORLD: A Virtual Environment for Developing and Evaluating Automated Scientific Discovery Agents*. arXiv:2406.06769. https://arxiv.org/abs/2406.06769 ；代码：https://github.com/allenai/discoveryworld
5. Cerrato, M. et al. (2026). *Science-Gym: a simple testbed for AI-driven scientific discovery*. Machine Learning. https://doi.org/10.1007/s10994-025-06914-x
6. Shridhar, M. et al. (2021). *ALFWorld: Aligning Text and Embodied Environments for Interactive Learning*. ICLR. https://arxiv.org/abs/2010.03768
7. Nasiriany, S. et al. (2024). *RoboCasa: Large-Scale Simulation of Everyday Tasks for Generalist Robots*. RSS. https://robocasa.ai/assets/robocasa_rss24.pdf
8. Liu, B. et al. (2023). *LIBERO: Benchmarking Knowledge Transfer for Lifelong Robot Learning*. NeurIPS. https://arxiv.org/abs/2306.03310
9. ScienceAgentBench. https://arxiv.org/abs/2410.05080 ；代码：https://github.com/OSU-NLP-Group/ScienceAgentBench
10. DiscoveryBench. https://arxiv.org/pdf/2407.01725 ；代码：https://github.com/allenai/discoverybench
11. Dave, A. et al. (2022). *Autonomous optimization of non-aqueous Li-ion battery electrolytes via robotic experimentation and machine learning coupling*. Nature Communications. https://doi.org/10.1038/s41467-022-32938-1

## 附录 A：建议的 V0 验收清单

- [ ] 同一 seed、同一 task manifest、同一 oracle hash 能重现完整 trace。
- [ ] 训练/开发/测试 task 文件分离，测试 outcome 不进入 agent observation。
- [ ] `plan_materialized`、`dispatch_verified`、`started`、`completed` 分开统计。
- [ ] 非法 action、重复测量、越界参数、缺失 outcome 有结构化错误码。
- [ ] replay outcome 包含 source record、dataset version 和 uncertainty 语义。
- [ ] random、greedy、BO baseline 与 agent 使用相同 budget 和 split。
- [ ] 结果报告 mean ± std，并提供 per-episode artifact。
- [ ] synthetic perturbation 与真实失败日志分开标记。
- [ ] fixture demo 的 README 明确不代表真实科学结论。
- [ ] 在进入 Alloy/Cell 前完成 oracle validation report。
