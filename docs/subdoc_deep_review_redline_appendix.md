# MatLabGYM 第二轮红线修订补充条款

以下条款补充自三份子文档的逐页审查，全部属于建议新增或替换内容，回填飞书时应标红。

## P0 补充一 验证内核与随机科学后端分离

<text color="red">不要把整个 environment 写成无噪声的确定性世界。schema、precondition、资源扣减、状态连续性和 goal predicate 应由纯函数验证内核完成，在固定 `(task_id, episode_id, seed, oracle_version)` 下完全可重放；测量噪声、设备故障、返回延迟和失败由显式、可播种的 stochastic oracle/failure model 产生，并在 trace 中记录随机变量和版本。</text>

建议接口为：

```text
validate(s, a) -> ValidityReport
transition(s, a, rng) -> s' + EventLog
oracle(s, a, rng) -> y + Uncertainty + Provenance
evaluator(trace, goal) -> endpoint + metrics
```

## P0 补充二 Skill contract 的完整字段

<text color="red">Skill contract 必须额外记录 units、resource lock、temporal semantics、idempotency、reversibility、contamination、failure_modes、recovery_skills、safety_limits、SOP version 和 effective date。没有这些字段，无法可靠处理并发、重试、样品损耗、时间同步和不可逆动作。</text>

推荐结构：

```yaml
skill_id: liquid.add.v1
inputs: [{name: source, type: MaterialRef}, {name: vessel, type: VesselRef}]
parameters:
  volume: {type: quantity, unit: uL, range: [1, 1000]}
preconditions: [vessel.state == uncapped, source.available >= volume]
postconditions: [vessel.contains += volume]
resources: [{resource: pipette_1ml, mode: exclusive}]
temporal: {duration: {value: 30, unit: s}, max_gap_to: null}
failure_modes: [out_of_range, timeout, contamination]
recovery: [discard_vessel, retry_with_new_tip]
idempotency: non_idempotent
reversibility: irreversible
safety_limits: {max_volume_per_vessel: {value: 3000, unit: uL}}
provenance: {source: sop_id, version: sop_rev, effective_from: date}
```

## P0 补充三 任务可解性 witness

<text color="red">每个任务进入 train/dev/test 前，必须由独立 solver、BFS/A* 或约束规划器证明在给定资源、时间窗和 max_steps 下至少存在一条满足 `Goal ∧ Safety ∧ Budget` 的轨迹。任务 manifest 保存最短可行长度、资源下界和 witness hash；witness 不对 agent 暴露。</text>

小任务可用 BFS/A*；带时间窗和并发资源的任务可用 DAG + Simple Temporal Network；大任务至少保存一个独立可行 witness 和 validator checksum。

## P0 补充四 成功、失败和近失轨迹必须同时建库

<text color="red">不能只用成功 workflow 反向生成任务。任务库必须同时包含成功、失败、近失（near-miss）和恢复轨迹：成功日志提取可行 witness，失败日志形成 failure taxonomy，近失轨迹生成最小反事实扰动。只由成功日志构造的任务不得声称代表真实平台部署分布。</text>

## P0 补充五 Replay support 和离线 policy 评估边界

<text color="red">Historical replay 只对数据支持集内的 action 提供真实 outcome。环境应区分 `measured`、`measured_with_replicates`、`unmeasured` 和 `missing_due_to_failure`；unmeasured action 返回 `OUTCOME_NOT_AVAILABLE`，不返回预测值。若要比较任意新 policy，必须提供 logging propensity/coverage 或显式生成模型；没有 positivity 时不得声称 off-policy value 无偏。</text>

manifest 至少增加：`support_mask_hash`、`logging_policy`、`propensity`（若有）、`replicate_group_id`、`censoring_reason`、`outcome_table_hash`。

## P0 补充六 Candidate lifecycle FSM

<text color="red">`continue/drop/retest/validate/stop` 必须是有成本、可验证的状态转移，而不是自然语言标签。建议 candidate lifecycle 为 `proposed → screened → shortlisted → validated → promoted | rejected`，并允许 `retest_pending → screened` 的受限回退。每个 action 固定前置 stage、资源消耗、observation、成功/失败后的 stage 和是否可回退。</text>

终局除了 success，还应计算 false-positive、false-negative、premature-stop、over-testing 和 stopping regret。

## P0 补充七 Planning 需要 DAG 和时间约束

<text color="red">线性 A→B→C 只适合作为教学例子。真实 SDL 允许并行操作，也存在 mutex、capacity、minimum/maximum gap 和时间同步。建议用 `Workflow=(V,E_precedence,E_mutex,E_sync,ResourceClaims,Goal)` 表示任务；评估允许所有满足约束的拓扑序，将额外步骤、总时长和资源峰值作为效率指标。</text>

## P0 补充八 Context Stress Track

<text color="red">新增上下文压力基准：固定 scientific goal，逐步增加 operation count、dependency depth、observation length、evidence 数量和 distractor 工具；比较 full-history、压缩摘要、检索记忆和无记忆 agent。所有摘要必须通过 information-leakage check，不得包含 hidden outcome、future state 或 evaluator 规则。</text>

## P0 补充九 数据 split 和污染审计

<text color="red">电解液和电芯 replay 不应按单行随机切分。至少提供 IID、new-seed、new-condition、new-formulation-family、new-campaign、new-device-regime 和 new-failure-mode split；同一 formulation、batch、paper、campaign 或相邻时间序列不得跨 train/test 泄漏。</text>

## P0 补充十 OracleCard 和 calibration gate

<text color="red">每个 backend 必须提交 OracleCard：`oracle_id、backend_type、dataset/model/database version、valid regime、calibration split、validation metrics、uncertainty semantics、known failure modes、counterfactual support、license、provenance、evaluator version`。未通过 calibration gate 的 backend 只能作为 exploratory/demo tool，不能产生主 benchmark 的 scientific claim。</text>

### CALPHAD / PyCalphad

<text color="red">AlloyEnv 只能在已知 thermodynamic database 覆盖的 composition/temperature/phase regime 内承诺 equilibrium phase fraction、phase composition 或 Gibbs energy。不能从 CALPHAD 自动推导 kinetics、strength、ductility、corrosion 或制造可行性。</text>

### PyBaMM

<text color="red">CellEnv 必须固定 chemistry、parameter set、time discretization、observation noise 和 safety limits，并在 held-out protocol/cell 上报告 calibration。模型在某一倍率曲线拟合良好，不等于对所有 cell chemistry 或 degradation regime 有效。</text>

## P0 补充十一 MATLAB/数值任务的额外评测

<text color="red">若后续任务要求 MATLAB script、Live Script 或 MATLAB function，必须将 syntax/compile、runtime、numerical correctness、unit consistency、solver convergence、artifact correctness、toolbox/license cost 和 wall-clock 分开计分。程序执行成功不等于科学结论正确。</text>

## P1 补充一 评估器和 runner 解耦

<text color="red">借鉴 AgentBench 的 Task Server、Agent Server、Evaluation Client，将 MATLAB worker、agent harness、oracle 和 evaluator 分离；支持 Docker/容器隔离、断点续评和失败重试。重试只允许处理网络/API/基础设施失败，科学失败必须保留并进入统计。</text>

## P1 补充二 安全与科学效用双评估

<text color="red">借鉴 AgentDojo，将用户科学目标与攻击者副作用目标交叉组合：第三方 notebook、comment、数据文件和工具返回值均视为不可信输入；在沙箱中检查文件覆盖、网络外传、hidden data 读取、未授权设备调用和 evaluator 修改。单独报告 benign utility、utility under attack、targeted attack success rate 和 scientific goal success。</text>

## P1 补充三 统计报告

<text color="red">每个方法至少使用预注册的 5 个 seed；报告 mean、standard deviation、95% confidence interval 和 per-episode artifact。对同一 task/seed 的方法比较使用 paired bootstrap 或配对检验，并报告 effect size；不要用单次最好结果替代均值。</text>

## 3 个子文档的建议插入位置

| 子文档 | 插入/替换位置 | 建议加入 |
| --- | --- | --- |
| 文档 1 规划 | 核心思路之后 | P0-1 验证内核 + stochastic oracle；完整 Skill schema；DAG/STN；可解性 witness |
| 文档 1 规划 | A/B/C/D 数据段 | 成功/失败/近失轨迹；owner/version/provenance；设备锁和安全 interlock |
| 文档 1 规划 | Environment/Task 生成段 | endpoint funnel、context stress、grouped split、防数据污染 |
| 文档 2 决策 | Environment 构建之后 | measured support、missing outcome、propensity/OPE 边界 |
| 文档 2 决策 | Task 1–4 之前 | candidate/measurement/lifecycle/replanning 四类 task family |
| 文档 2 决策 | RL 段之前 | static replay=BO/AL/bandit；stateful campaign=MDP/POMDP/RL |
| 文档 2 决策 | Continue/Drop/Validate 段 | lifecycle FSM、stopping regret、false-positive/negative |
| 文档 3 模拟 | Oracle 总体设计之后 | OracleCard、calibration gate、多 fidelity 注册 |
| 文档 3 模拟 | Electrolyte 段 | data coverage、grouped split、replicates、uncertainty semantics |
| 文档 3 模拟 | Alloy/Cell 段 | PyCalphad/PyBaMM 适用边界和 held-out validation |

## 推荐的最终研究主张

<text color="red">MatLabGYM 的研究对象不是一个万能材料预测器，而是一套能够在多个 fidelity backend 上审计科学 agent 的实验协议。第一版以简单、确定性可验证的 planning/replay 内核承载复杂任务；后续通过 OracleCard 和 calibration gate 注册 physics/hybrid/real-lab backend。每项结果都必须同时报告 workflow executability、scientific outcome、decision efficiency、long-context robustness、security side effects 和 reproducibility。</text>
