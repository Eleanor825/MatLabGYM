# MatLabGYM 三个子文档第二轮科学审查与红线修订建议

版本：0.2 · 2026-09-16  
用途：不修改飞书主文档和三个子文档；本页只给出可直接回填的修订意见。**所有带“建议修改”标签的内容均应在飞书中标红。**

## 1. 审查范围与总判断

本轮重新读取了主文档、三个子文档及主文档现有 comment，并补充核对了目标论文、官方代码仓库和相关 science-agent / active-experiment 工作。三个子文档的方向是正确的，但还存在四个会影响论文可信度和工程落地的结构性问题：

1. planning、decision、scientific oracle 的接口和评价边界还没有完全闭合；
2. “成本最小”在没有真实成本字段时容易被误写成虚假 ground truth；
3. replay、physics simulator、surrogate 和 real lab 的可信等级没有形成注册和准入机制；
4. 上下文过载、防作弊、并发和自进化目前更多是原则描述，还没有变成可验收的 contract。

<text color="red">建议将三个子文档从“并列研究想法”改成一个分层闭环：Planning Track → Execution Evidence Track → Scientific Oracle Track → Decision Track → Replanning Track。每一层拥有独立的 success predicate、artifact 和指标，但共享 TaskSpec、Action、Observation、StepResult、Trace 和 Provenance。</text>

<text color="red">建议把第一阶段的研究命题收窄为：在固定 oracle、固定预算和不可变 hidden test 下，agent 是否能以更高的可执行率、更低的 simple regret 和更少的资源消耗完成证据驱动的材料实验决策。不要在第一阶段同时承诺通用材料覆盖、RL、multi-agent、自进化和真实平台部署。</text>

## 2. 主文档 comment 的科学化回应

### 2.1 Reward、时间、价格和通量

现有 comment 的核心意思是“在达到科学目标的前提下，把时间和钱花得最少”，并进一步提出通量、返回时间和价格约束。这个方向合理，但必须区分硬约束、真实观测成本和实验者指定的预算。

<text color="red">建议将 reward 写成词典序目标，而不是一开始写成任意加权和：第一层是科学目标/安全约束是否满足；第二层是在满足第一层的轨迹中最小化真实成本；第三层才比较信息效率、吞吐和 wall-clock。形式上可写为：GoalSatisfied → SafetySatisfied → minimize(C_money, C_time, C_sample, C_device) → maximize(InformationGain or performance improvement)。</text>

<text color="red">建议在 TaskSpec 中将 `budget` 拆成 `budget_experiments`、`budget_money`、`budget_time`、`budget_sample`、`device_slots` 和 `throughput_limit`。每个字段都必须带 `observed | configured | unknown` 的 provenance 状态；unknown 不得在报告中被解释成真实实验成本。</text>

<text color="red">当数据只有 conductivity 或单一性能字段时，V0 只能使用 `unit_query_cost=1`，并将结果命名为 query/sample efficiency。只有真实平台提供 duration、试剂成本、样品消耗和设备占用后，才开放 cost-aware benchmark。</text>

### 2.2 Reset、episode 隔离和上下文过载

comment 明确提出 reset 时需要哪些参数、每个环境隔离、避免一个 episode 看到另一个 episode 的交互逻辑，以及长程上下文过载问题。现有子文档的 state 列表还缺少时间、队列、权限和上下文预算。

<text color="red">建议固定 reset 契约：`reset(task_spec, seed, oracle_snapshot, resource_config, observation_policy, workspace_policy, perturbation_config)`。返回值除 public observation 外，还应返回 `episode_id`、`task_hash`、`env_version` 和可审计的 resource ledger；hidden outcome、evaluator 和其他 episode 的 trace 不得进入 observation。</text>

<text color="red">建议将实验状态显式拆成 `material_state`、`sample_state`、`container_state`、`equipment_state`、`resource_ledger`、`clock/queue_state`、`evidence_state` 和 `agent_memory_budget`。长程任务中的“记忆”只能来自 observation 或允许的摘要，不得通过文件系统、缓存、全局变量或错误信息绕过上下文限制。</text>

<text color="red">建议新增 Context Stress Track：固定科学任务，逐步增加 operation 数、依赖深度、观测长度和 evidence 数量；比较 full-history、压缩摘要、检索记忆和无记忆 agent。摘要必须经过 information-leakage check，不能把 hidden outcome、future state 或 evaluator 规则压缩进去。</text>

### 2.3 Multi-agent 是否必要

comment 提出 execute experiment 是否应该 multi-agent。现阶段没有证据证明 multi-agent 是环境成立的必要条件；如果一开始就使用多 agent，无法分辨收益来自更强的协作还是更宽的 token/工具预算。

<text color="red">建议采用三阶段对照：Stage A 单一 executor policy；Stage B planner + executor；Stage C proposer + planner + executor + verifier。每个阶段使用相同 TaskSpec、oracle、budget、seed 和 hidden test，额外报告 agent 数量、通信 token、工具调用和 wall-clock 开销。</text>

<text color="red">建议把 multi-agent 定义为可插拔 harness，而不是写入环境内核。环境只负责状态、动作、结果和约束；角色如何分工属于 policy/harness ablation。</text>

### 2.4 预测模型作为 skill

comment 提出 agent 是否可以根据已有实验训练预测模型作为 skill。可以，但必须将 surrogate 定义为“建议工具”，不能让它变成隐式 oracle。

<text color="red">建议将 surrogate skill 的输出固定为 `{prediction, uncertainty, training_data_hash, model_version, calibration_status, applicability_range}`。surrogate 只能影响 candidate ranking 或 acquisition proposal，不能修改 hidden outcome、success predicate、evaluator 或 safety constraint。</text>

<text color="red">建议新增 surrogate ablation：oracle-only、surrogate-assisted、surrogate-as-oracle（仅作为负面对照）三组。主结果只接受前两组；第三组必须明确标注为 methodological anti-pattern。</text>

### 2.5 Curriculum、harness/skills 自进化和 policy 归属

comment 中问到 harness 是 policy、skill 是 policy，还是完全不管外环总结。这个问题需要在定义层解决。

<text color="red">建议固定术语：environment 是状态转移和 outcome 生成器；skill 是带 precondition/effect 的动作接口；executor/planner/harness 是 policy；curriculum manager 是训练数据/任务分配器；verifier/evaluator 是独立裁判。skills 不应被称为 policy，除非 skill 内部包含可学习选择逻辑并单独登记其参数。</text>

<text color="red">建议将“学得越快”操作化为达到预注册能力阈值所需的 `episodes-to-threshold`、`tokens-to-threshold`、`compute-to-threshold` 和 `wall-clock-time-to-threshold`。同时报告最终能力，避免一个方法只因提前停止而看起来更快。</text>

<text color="red">建议将可进化对象限制为 task generator 参数、prompt/memory policy、tool routing、planner heuristic 和最小 harness patch；不可修改对象包括 hidden test、scientific oracle、success predicate、evaluator、安全边界和数据 split。</text>

### 2.6 业务方是否需要参与 skill registry

答案是需要，而且职责应写入项目流程，而不是只在文档中说“由平台提供”。

<text color="red">建议建立 Skill Registry RACI：业务方/平台 owner 负责 operation 语义、设备能力、SOP、参数范围、容器/样品 I/O、故障码和安全边界；工程侧负责 schema、版本、validator、trace、replay 和 API adapter；科学负责人负责 outcome 定义、校准数据和适用范围；评测负责人负责 hidden test 和 evaluator。</text>

<text color="red">每个 skill 进入 benchmark 前必须有 owner、source document、effective date、version、review status 和变更 diff。没有 owner 或没有证据来源的 skill 只能进入 sandbox，不能进入主测试集。</text>

### 2.7 Ray 并发

Ray 可以解决 episode/seed/task 的并发，但并发本身不是科学贡献，且可能引入共享文件、随机数、许可证和设备槽位竞态。

<text color="red">建议将 Ray 放在 runner 层，并为每个 actor 显式分配 `episode_id`、seed、workspace、artifact_dir、CPU/GPU/toolbox/license quota 和 timeout。任务 evaluator 使用 episode-local ledger，不依赖进程完成顺序。</text>

<text color="red">建议新增并发一致性测试：单线程与 Ray 并行在相同 seed/task manifest 下的 trace hash、metrics、预算消耗和失败分类必须一致；若不一致，结果只能作为 non-deterministic infrastructure run，不进入论文主结果。</text>

## 3. 子文档一的修订意见：长程实验任务规划

### 3.1 保留的核心

子文档一最有价值的判断是“从真实平台反向构建 Environment”，并明确了 workstation、operation、SOP、参数范围、样品/容器状态、设备依赖和失败日志。这个核心应保留。

### 3.2 必须新增的 formal contract

<text color="red">建议将 `Skill` 的最小 schema 改成：`skill_id, version, inputs, typed_parameters, units, preconditions, effects, resource_requirements, duration, cost, output_artifacts, failure_modes, recovery_skills, safety_limits, provenance`。其中 `duration/cost` 可以是 null，但必须带 `observed/configured/unknown` 状态。</text>

<text color="red">建议把当前的 `Output(a_t)=Input(a_{t+1})?` 改为 typed state compatibility：下一动作的每一个 required input 必须能在上一状态中解析到同类型对象，且对象的 sample/container lineage、数量、单位和状态满足 contract。输出不要求与下一个输入文本相等，而要求满足可验证的 unification predicate。</text>

<text color="red">建议给 validator 增加四层结果：`schema_valid`、`state_valid`、`resource_valid`、`goal_reachable`。只有全部通过才进入 `dispatch_verified`；失败时返回互斥主错误码和可选的细分标签。</text>

### 3.3 长程定义和任务生成

ScienceWorld 的经验表明，参数化变体和隐藏 OOD 比简单增加任务步数更能区分泛化能力；DISCOVERYWORLD 则把假设、实验、分析和结论组合成完整发现闭环。MatLabGYM 不应只制造更长的线性 SOP。

<text color="red">建议将长程任务定义为 difficulty vector，而不是单一 horizon：`(operation_count, dependency_depth, constraint_density, branching_factor, resource_scarcity, state_memory, failure_rate, observation_length, domain_shift)`。任务等级根据真实 workflow 分布的分位数校准，不能人工平均填充。</text>

<text color="red">建议每个任务至少包含一个可验证 terminal goal、一个或多个 optional subgoal、至少两条合法路径或一条合法路径加一个可恢复失败点。这样既避免 exact-match，也避免任务因无解而无法收敛。</text>

<text color="red">建议将任务拆成 `planning-only`、`planning-under-constraints`、`planning-with-recovery` 和 `planning-with-evidence` 四个 family。第一版环境可以简单，但 task graph 必须复杂且可程序化验证。</text>

### 3.4 证据端点

目标论文中的关键经验是：计划结构/语义得分高，不等于可 dispatch；dispatch 也不等于实验 started/completed。

<text color="red">建议在子文档一中新增 endpoint funnel：`plan_materialized → dispatch_verified → started → completed → scientifically_validated`。每个 endpoint 都保存对应回执或 artifact；固定分母报告每一层 drop-off，unscorable trial 计 0。</text>

### 3.5 子文档一建议替换的结尾

<text color="red">建议替换为：Planning Environment 的 ground truth 不是某一条 reference workflow，而是 skill contract、typed state transition、platform/resource constraint 和 terminal goal predicate 的联合可满足性。Agent 只要从初始状态合法到达目标状态即可成功；但 plan materialization、dispatch、start、completion 和 scientific validation 必须由独立证据分别证明。</text>

## 4. 子文档二的修订意见：长程实验任务决策

### 4.1 任务类型应分开

当前子文档把 candidate selection、next measurement、continue/drop/retest/validate 和 replanning 都放在同一个 decision 叙述中，科学问题略显混杂。

<text color="red">建议拆成四类 benchmark：A candidate selection；B measurement selection；C lifecycle decision；D contradiction-driven replanning。每一类有不同 action space、终止条件和 baseline，不能用一个 aggregate reward 代替。</text>

### 4.2 Replay 的统计有效性

历史 replay 不是天然无偏。若只随机按行拆分，同一 formulation、同一 paper、同一 batch 或相邻温度可能同时出现在 train/test，导致泄漏。

<text color="red">建议数据 split 优先按 formulation family、campaign/batch、paper/source、时间窗口和实验室/设备域分组，而不是按单行随机切分。至少报告 IID split、family-held-out split、campaign-held-out split 和 condition-held-out split。</text>

<text color="red">建议在 replay manifest 中记录 coverage matrix：candidate × experiment × condition 的观测覆盖、重复测量数量、缺失模式、异常规则和 outcome hash。未覆盖 action 返回 `oracle_missing_outcome`，不得静默调用 predictor。</text>

### 4.3 决策指标

Rohr 等人的 sequential learning 工作和 Dave 等人的 Clio/Dragonfly 真实 autonomous campaign 说明 BO 是必须的强 baseline；STEMGym 说明预算效率应使用信息—成本曲线，而不是只看终点性能。

<text color="red">建议 V0 至少报告 `best_found`、`simple_regret`、`experiments_to_target`、`Top-k recall`、`budget-constrained success`、learning/discovery curve 和 AUC。若引入真实 duration/money/sample，再报告 cost-normalized regret 和 throughput。</text>

<text color="red">建议将 `Expected Information Gain` 限定在具有显式 generative model、likelihood、prior 和 observation noise 的 backend。对于纯 historical replay，优先使用 regret、target recall 和 sample efficiency，不把 GP posterior variance 当作 ground-truth information gain。</text>

### 4.4 Lifecycle 和 stopping

真实研发的 continue/drop/retest/validate 不是简单的四个文本动作，而是会改变 candidate 的 stage、资源消耗和未来可行动作。

<text color="red">建议为 candidate 增加 lifecycle state：`screened → provisional → retest_pending → validated → rejected → archived`，并由 action 触发可验证的状态转移。`stop` 只有在满足终止条件或预算边界时才可获得成功，不应因为 agent 输出一句“建议停止”就 done。</text>

<text color="red">建议增加 stopping regret：如果 agent 现在 stop，与 oracle 完整 search 或预注册 policy frontier 相比损失多少；同时报告过早停止率、无效延长率和 contradiction 后重规划率。</text>

### 4.5 RL 边界

子文档二已经有“静态 replay 更像 BO/active learning/bandit，stateful environment 才适合 RL”的正确判断，应将它升级为 formal task-typing rule。

<text color="red">建议明确：若 `P(s_{t+1}|s_t,a_t)` 只通过 budget/candidate history 变化且 outcome table 固定，主 baseline 是 contextual bandit/BO；若 action 改变 sample state、equipment availability、validation stage、degradation state 或未来可行 action，才进入 episodic RL/model-based RL。</text>

## 5. 子文档三的修订意见：材料性能模拟与 Scientific Oracle

### 5.1 标题和中心命题

子文档三的实质内容是 oracle governance，而不是“模拟器越多越好”。

<text color="red">建议将标题改为“Scientific Oracle 与多 fidelity backend”，并把中心命题写成：No registered and validated oracle, no ground-truth scientific benchmark。</text>

### 5.2 Oracle 注册卡

<text color="red">建议每个 oracle 必须提交 `oracle_id, backend_type, dataset/model/database version, valid regime, calibration set, validation metrics, uncertainty semantics, known failure modes, license, provenance, evaluator_version`。没有这些字段的后端只能作为 exploratory tool，不能用于主评测。</text>

### 5.3 电解液

Rahmanian 等人的自动化 conductivity/EIS 数据适合作为 V0 的 replay 起点，但需先完成数据卡、重复实验和异常规则审计。它可以回答有限预算下的 candidate/condition 选择，不自动回答未测配方的反事实性能。

<text color="red">建议把 ElectrolyteEnv-v0 的 action space 限制为数据中实际存在的 `(formulation_id, temperature/condition)`，observation 至少包含 outcome、uncertainty（若原始数据有）、source record id 和 data version。V0 的主结果使用 replay ground truth；surrogate 仅作为候选排序 ablation。</text>

### 5.4 Alloy

PyCalphad 的 solver、热力学数据库和实验校准必须分开。数据库覆盖之外的 composition/temperature 不应被默认解释为可靠。

<text color="red">建议 AlloyEnv 的准入门槛为：数据库覆盖明确、phase/temperature 区间明确、内部或文献 validation set 预先冻结、phase fraction/phase composition/Gibbs energy 误差达到项目阈值、known failure regime 在 task manifest 中显式列出。第一任务只做 phase constraint 或 phase-window identification。</text>

### 5.5 Cell

PyBaMM 适合构造动态环境，但不同 chemistry、parameter set 和 protocol 的验证强度不同；官方示例在某些倍率下拟合良好不等于所有电芯可用。

<text color="red">建议 CellEnv-v1 先做 charging protocol optimization 或 system identification。固定 chemistry/parameter set、observation noise、time discretization 和 safety limits；使用 early-cycle observation 隐藏 future trajectory，分别评估 control success、parameter identification error 和 long-horizon degradation risk。</text>

### 5.6 正极/负极

<text color="red">建议正极/负极第一版只做 controlled-family replay：固定 SID、上下游材料、cell type 和 comparable protocol，只改变一个受控因素。不能把跨论文、跨实验室、跨 electrolyte、跨 protocol 的性能差异直接归因于 cathode/anode。</text>

## 6. 结合更多相关工作的设计取舍

### 6.1 目标论文 Stress-testing robotic chemistry laboratory

该工作使用 45 个模块化工作站、62 类操作、433 个约束和 456 个参数，进行 4,608 个 trial；仅 3.3% trial 获专家 executable label，最佳配置 28.1%；只有 3 条 workflow 超过 30 operations，最长 44。其十个 evidence endpoint 将计划、验证、dispatch、start 和 completion 分开，并明确 dispatch 不证明实验已开始或完成。

<text color="red">MatLabGYM 必须直接继承 endpoint funnel、固定分母、端点级失败 taxonomy 和跨轮次 workflow-level replanning 指标；不能只报告 JSON/schema 通过率或最终推荐性能。</text>

### 6.2 ScienceWorld 与 DISCOVERYWORLD

ScienceWorld 提供任务模板、参数变体、hidden OOD、POMDP 状态和 subgoal score；DISCOVERYWORLD 提供 120 个任务、8 个主题×3 个难度，并把 hypothesis→experiment→analysis→conclusion 作为完整 discovery loop，同时分开 completion、relevant actions 和 explanatory knowledge。

<text color="red">MatLabGYM 应采用“任务模板 + hidden variation + deterministic success predicate + optional subgoal”结构；但将小学科学对象替换为材料样品、实验条件、仪器和数据分析，不直接搬运其 hand-coded gold path。</text>

### 6.3 ChemGymRL

ChemGymRL 的 bench、vessel 和 Lab Manager 说明模块化实验链是可实现的；其 reaction/extraction/distillation bench 同时包含离散/连续动作、部分可观测状态和过程/终局 reward。

<text color="red">MatLabGYM 可以借鉴 bench→bench state interface 和 typed vessel/sample transfer，但必须把材料 outcome、单位、守恒、安全和 provenance 做成强约束；ChemGymRL 的玩具动力学不能直接作为材料科学 ground truth。</text>

### 6.4 Science-Gym、STEMGym 与 BoxingGym

Science-Gym 将 collection、experiment design 和 equation discovery 放在 Gym-compatible scientific testbed 中；STEMGym 用 15 个 physics-simulated STEM worlds、dose budget 和 DEC-AUC 强调信息—资源 Pareto；BoxingGym 用 10 个 generative probabilistic environments 和 EIG 评估实验设计、模型发现与解释预测。需要注意，“Science-Gym”在公开资料中存在命名歧义，引用时必须锁定具体论文/仓库。

<text color="red">MatLabGYM 建议同时报告 outcome、information、resource 三类曲线：最终科学目标、单位实验/时间/剂量获得的信息，以及预算耗尽前的 Pareto frontier。只有显式概率模型 backend 才开放 EIG；replay backend 不使用伪 EIG。</text>

### 6.5 ScienceAgentBench、BLADE 与 SciAgentGym

ScienceAgentBench 将 102 个来自 44 篇论文的科学任务统一为可执行程序，并分别评代码、运行结果和成本；BLADE 用专家独立分析和 facet evaluator 处理多种等价分析路径；SciAgentGym 将 1,780+ 工具、隔离 filesystem/database/Python execution、typed protocol 和 structured traces 组合成多步 scientific tool-use benchmark。

<text color="red">MatLabGYM 应将“程序/工具执行正确性、数值结果正确性、科学结论、资源成本和 provenance”分开评分；对 MATLAB/Live Script 任务增加数值容差、单位检查、solver convergence、图表/文件 artifact 和 toolbox/license 成本。</text>

### 6.6 AgentBench 与 AgentDojo

AgentBench 的 Task Server/Agent Server/Evaluation Client、Docker worker、并发和断点续评适合借鉴；AgentDojo 的有状态工具、副作用检查、user goal×attack goal cross-product 和 utility/security 双指标适合防作弊和 prompt-injection stress test。

<text color="red">建议 MatLabGYM 将 worker/evaluator 解耦，并为 MATLAB workspace、文件、网络、外部 API 和 notebook/comment 内容设置副作用沙箱。安全分、科学效用分和 utility-under-attack 分开报告，不能用一个总 reward 掩盖数据外泄或文件破坏。</text>

## 7. 推荐的统一 schema

### 7.1 Reset schema

<text color="red">建议统一为：`task_spec, seed, oracle_snapshot, resource_config, observation_policy, workspace_policy, perturbation_config, max_steps, timeout_s`。其中 `workspace_policy` 至少规定文件系统、数据库 namespace、缓存、网络和可见日志范围。</text>

### 7.2 Step schema

<text color="red">建议统一返回：`observation, reward, terminated, truncated, info`；其中 info 必须包含 `valid, endpoint, state_diff, scientific_outcome, cost, failure_code, provenance, artifact_refs`。每次 transition 都写入 immutable JSONL trace。</text>

### 7.3 Task split

<text color="red">建议 split 不只使用 train/dev/test 三个名字，而是登记 shift 类型：`IID`、`new_seed`、`new_condition`、`new_formulation_family`、`new_campaign`、`new_device_regime`、`new_failure_mode`。主榜至少报告 IID 与最接近真实部署的 OOD split。</text>

## 8. 推荐的评价矩阵

<text color="red">建议把主结果表固定为六列：Executable、Scientific、Efficiency、Robustness、Safety、Reproducibility。Executable 包含 valid action/dispatch/start/completed；Scientific 包含 goal success/regret/target recall；Efficiency 包含 experiments/time/money/sample/token；Robustness 包含 perturbation degradation/recovery；Safety 包含 unauthorized side effects/constraint violations；Reproducibility 包含 trace hash/seed repeatability。</text>

<text color="red">建议每个方法至少运行预注册的 5 个 seed；报告 mean±std 和置信区间，并提供 per-episode artifacts。若只运行单 seed，结果只能称为 smoke test 或 qualitative demonstration。</text>

<text color="red">建议主榜不合并不可比的 domain 分数。跨 domain 汇总时采用固定版本、预注册权重或 per-domain rank aggregation，并同时公布未加权原始指标。</text>

## 9. 推荐里程碑

<text color="red">M0：单机、单 agent、确定性 planning validator 和 fixture/replay oracle；通过 trace replay、非法动作、重复动作、状态连续性和隔离测试。</text>

<text color="red">M1：真实 electrolyte replay；完成数据卡、license、coverage matrix、grouped split、random/greedy/BO baseline、regret/target recall/AUC 报告。</text>

<text color="red">M2：multi-stage lifecycle；加入 continue/drop/retest/validate/stop、异常与矛盾 evidence、replanning、stopping regret 和 endpoint funnel。</text>

<text color="red">M3：AlloyEnv 或 CellEnv 二选一；先通过 oracle calibration gate，再进入主 benchmark。不得同时把两个未经校准的 backend 当作同等级结果。</text>

<text color="red">M4：Ray runner、Context Stress Track、AgentDojo 风格副作用/注入 stress suite；验证并发与单机的 trace/metrics 一致性。</text>

<text color="red">M5：multi-agent 和 harness evolution；固定 policy surface、最小 patch、immutable holdout、regression/safety gate，并报告协作/演化成本。</text>

<text color="red">M6：real-lab adapter 和 sim-to-real calibration；只报告虚拟 endpoint 与真实 dispatch/start/completion 的对应关系，不把虚拟成功自动写成真实部署成功。</text>

## 10. 最终建议的主文档表述

<text color="red">MatLabGYM 是一个面向材料科学 agent 的可验证 sequential decision benchmark。它把真实实验平台的 skills、状态、资源和约束转化为可重放的 Environment，并通过分层 scientific oracle 提供可审计 outcome。第一阶段先在简单但可验证的 planning/replay 环境中构造复杂任务，评估 agent 的可执行性、证据驱动决策、资源效率、长程记忆和安全鲁棒性；只有在 oracle 校准、隐藏测试和独立 evaluator 通过后，才扩展到 Alloy、Cell、multi-agent、Ray 并发和 harness 演化。</text>

<text color="red">项目的核心科学贡献不是“用 RL 预测材料性能”，而是建立一个能区分 workflow executability、scientific validity、decision quality、resource efficiency 和 deployment evidence 的统一实验协议。任何性能提升都必须在固定 oracle、固定 evaluator、固定 hidden test 和可重放 trace 下，同时报告最终能力、学习速度、成本、泛化和安全代价。</text>

## 11. 参考资料

1. Guo et al. (2026). *Stress-testing large language model agents in a robotic chemistry laboratory*. https://arxiv.org/abs/2607.23045 ; code/data: https://github.com/pic-ai-robotic-chemistry/LabBench
2. Wang et al. (2022). *ScienceWorld: Is your Agent Smarter than a 5th Grader?* https://aclanthology.org/2022.emnlp-main.775/ ; https://github.com/allenai/ScienceWorld
3. Beeler et al. (2024). *ChemGymRL: A customizable interactive framework for reinforcement learning for digital chemistry*. https://doi.org/10.1039/d3dd00183k ; https://github.com/chemgymrl/chemgymrl
4. Jansen et al. (2024). *DISCOVERYWORLD*. https://arxiv.org/abs/2406.06769 ; https://github.com/allenai/discoveryworld
5. Cerrato et al. (2026). *Science-Gym: a simple testbed for AI-driven scientific discovery*. https://doi.org/10.1007/s10994-025-06914-x
6. *STEMGym: Benchmarking Sequential Decision-Making under Dose Budgets in Autonomous Electron Microscopy*. https://arxiv.org/abs/2606.29592
7. *BoxingGym: Benchmarking Progress in Automated Experimental Design and Model Discovery*. https://arxiv.org/abs/2501.01540
8. Gu et al. (2024). *BLADE: Benchmarking Language Model Agents for Data-Driven Science*. https://arxiv.org/abs/2408.09667 ; https://github.com/behavioral-data/BLADE
9. *ScienceAgentBench*. https://arxiv.org/abs/2410.05080 ; https://github.com/OSU-NLP-Group/ScienceAgentBench
10. *SciAgentGym: Benchmarking Multi-Step Scientific Tool-use in LLM Agents*. https://arxiv.org/abs/2602.12984 ; https://github.com/CMarsRover/SciAgentGYM
11. Liu et al. (2023). *AgentBench: Evaluating LLMs as Agents*. https://arxiv.org/abs/2308.03688 ; https://github.com/THUDM/AgentBench
12. Debenedetti et al. (2024). *AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents*. https://arxiv.org/abs/2406.13352 ; https://github.com/ethz-spylab/agentdojo
13. Rohr et al. (2020). *Benchmarking the acceleration of materials discovery by sequential learning*. https://doi.org/10.1039/c9sc05999g
14. Dave et al. (2022). *Autonomous optimization of non-aqueous Li-ion battery electrolytes via robotic experimentation and machine learning coupling*. https://doi.org/10.1038/s41467-022-32938-1
15. Rahmanian et al. (2023). *Conductivity experiments for electrolyte formulations and their automated analysis*. https://doi.org/10.1038/s41597-023-01936-3
16. Zhou et al. (2026). *Multi-task scheduling of self-driving laboratories under scientific constraints*. https://doi.org/10.1039/d6sc03892a
17. Boiko et al. (2023). *Autonomous chemical research with large language models*. https://doi.org/10.1038/s41586-023-06792-0
18. Burger et al. (2020). *A mobile robotic chemist*. https://doi.org/10.1038/s41586-020-2442-2
19. Chaloner & Verdinelli (1995). *Bayesian experimental design: A review*. https://doi.org/10.1080/01621459.1995.10476572
