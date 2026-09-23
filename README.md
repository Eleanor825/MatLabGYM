# MatLabGYM

MatLabGYM is a verifiable environment framework for materials-research agents. It combines a hardware-independent protocol layer, platform compilation, deterministic asynchronous execution, and a Gym-style episode interface.

Version `0.4` adds a [uniform environment API](docs/uniform_api.md) across planning,
lab execution, direct replay and a runnable [electrolyte screening loop](docs/electrolyte_scenario.md).
The screening task connects completed mixing/characterization jobs to frozen conductivity
measurements, sample lineage, query-budget reservations and configurable rewards.
See the [Roadmap](docs/roadmap.md) and [TODO](docs/TODO.md) for delivery gates and concrete tasks.

Version `0.2` includes a runnable six-stage electrolyte production-line simulation based on the internal `MATLABGYM LAB` interface template:

```text
mix electrolyte
  -> characterize
  -> inject and first seal
  -> formation and capacity
  -> second fill and degas
  -> test
```

## Roadmap

> **当前阶段：M0 工程原型已完成，正在为 M1 平台确认与真实数据接入做准备。**
> 统一接口、电导率筛选闭环、reward 和评测代码已通过 [PR #2](https://github.com/Eleanor825/MatLabGYM/pull/2) 合并到 main。
> 95 项测试、三策略示例重放及 Python 3.9 / 3.11 / 3.12 CI 已通过。
> 当前可以运行模拟与 CSV replay；真实数据校准、正式科学评测和实机对接尚未完成。

勾选规则：`[x]` 表示所述交付已完成，`[ ]` 表示仍需完成；“准备中”仅表示清单和接口已备齐，不表示平台已经确认或真实实验已开始。完成一项后更新勾选，并附 PR、测试或平台证据。

### M0 · 统一接口与闭环原型 — 工程实现完成

- [x] 统一规划、产线、replay 和筛选环境的 reset/step、动作 schema、结果、成本来源与评测接口。
- [x] 实现配液 → 表征 → 测量反馈 → 选择下一候选的电导率闭环。
- [x] 实现三类可配置 reward、独立指标及公开顺序／随机／自适应基线。
- [x] 验证预算预留、幂等、停止后样品隔离、同 seed reset 身份隔离和严格重放。
- [x] 完成干净安装、95 项测试、三策略 CLI 和多 Python 版本 CI，并合并 main。
- [ ] 发布正式版本标签／发行包及对应版本说明。（TASK-004 的剩余交付）

**已达到的程度：**软件可以复现运行；科学反馈覆盖 S1 配液与 S2 表征。六阶段产线已能模拟执行，但 S6 电芯容量／寿命等真实性能结果尚未接入。

### M1 · 平台契约与真实数据 — 当前准备阶段

- [x] 整理六阶段 [Operation Inventory](docs/electrolyte_operation_inventory.md)、9 项待确认决策和 20 个[接口验收场景](docs/electrolyte_interface_acceptance.md)。
- [ ] 指定平台、工艺和数据负责人，逐项确认 DEC-01–09。（TASK-010）
- [ ] 确认表征是否必选、启停与 Skill 边界、参数单位、失败后样品处置和真实 ID。（TASK-007/008/009）
- [ ] 获取第一份有来源和使用授权的电导率数据，完成质量检查并冻结支持域。（TASK-006/007）
- [ ] 接入真实测量报告，确认设备容量、耗时和成本来源。（TASK-011/013）

**下一步验收门槛：**适用接口有 SOP/API/日志依据；数据来源、单位、质量检查和支持域可追溯。当前未取得这些确认，不能把模拟参数当作真实工艺规则。

### M2 · 独立科学评测 — 待开展

- [ ] 隔离隐藏结果与 evaluator，完成进程／文件边界和泄漏测试。（TASK-012）
- [ ] 冻结训练／开发／测试划分、任务、预算、种子和失败统计分母。（TASK-014）
- [ ] 比较基线及真实反馈／无反馈／扰乱反馈，验证反馈是否改善决策。（TASK-015）
- [ ] 报告达标率、best-found、regret、有效实验数及效应量／置信区间；reward return 单独报告。（TASK-014/015）

**验收门槛：**数据与评价独立、无泄漏、结果可复现。仅切换 reward 对固定策略重新计分，不算学习效果验证。

### M3 · 影子平台对接与故障恢复 — 待开展

- [ ] 实现只读／影子 adapter，关联真实任务、样品、设备和报告 ID。（TASK-016）
- [ ] 实现跨 worker／进程运行身份、持久化幂等和重启恢复。（TASK-022/017）
- [ ] 验证断连、丢响应、乱序回调、超时和部分失败；未知状态先查询对账，未知样品保持隔离。（TASK-017）
- [ ] 完成适用接口验收并形成平台确认报告。（TASK-018）

**验收门槛：**状态与平台记录一致，不重复物理执行或计费。依赖就绪后可与 M2 并行推进。

### M4 · 受控实机与扩展 — 后续阶段

- [ ] 在确认的控制范围内完成有限实机试运行与异常处置验收。（TASK-019）
- [ ] 验证真实科学结果，标定实际时间／成本；补齐完整六阶段科学任务。（TASK-019/020）
- [ ] 在首个场景验证后，评估其他材料域和多 Agent 调度，并分别建立测试与对照。（TASK-020/021）

**验收门槛：**每次真实执行及科学达标都有可追溯证据，新增场景独立验证。

完整阶段定义见 [Roadmap](docs/roadmap.md)；22 项任务的优先级、建议负责角色、依赖和通过条件见 [TODO](docs/TODO.md)。进度依据已完成的交付和验收判断，不用未经验证的完成百分比或日期代替。

## Design

The execution architecture is inspired by the separation used in the chemical description language χDL:

```text
hardware-independent Protocol
  -> ProtocolCompiler
  -> platform-bound CompiledProtocol
  -> LabRuntime / real-lab adapter
  -> artifact lineage + trace
  -> LabGymEnv + configurable reward
```

MatLabGYM implements its own small, dependency-free contracts. It does not copy or import the official χDL implementation, which is AGPL-3.0 licensed. The paper has no official GitHub repository; the maintained implementation is the Cronin Group's [official GitLab repository](https://gitlab.com/croningroup/chemputer/xdl).

The framework keeps four concepts separate:

- **Operation/tool**: one controllable platform operation with typed parameters, input/output artifacts, preconditions, resource requirements, duration, cost, and interruptibility.
- **Skill**: an atomic multi-operation protocol. Intermediate execution is visible in provenance but cannot be controlled by the agent.
- **Runtime**: owns the logical clock, load-aware resource binding, sample locks, jobs, costs, artifact IDs, lineage, request idempotency, and failure codes.
- **Reward**: a versioned benchmark configuration. It is intentionally not scientific ground truth and can be replaced without changing the environment dynamics.

See [Framework Architecture](docs/framework.md) for the complete contracts and extension path.
See the [meeting whiteboard redraw](docs/figures/README.md) for the six-stage
electrolyte flow and discussion points, with editable LaTeX/TikZ, PDF and PNG.
For platform review, use the six-stage
[Operation Inventory](docs/electrolyte_operation_inventory.md) and
[Interface Acceptance Checklist](docs/electrolyte_interface_acceptance.md).
They separate implemented simulation behavior from unconfirmed physical controls,
sample states, parameter limits and cost/time sources.
See [Literature Traceability](docs/literature_traceability.md) for the paper-to-contract audit and the current paper-readiness boundary.
See [Scientific Gym Rewards](docs/scientific_gym_rewards.md) for a source-verified
comparison of ChemGymRL, ScienceWorld and BoxingGym, and
[Reward Design](docs/reward_design.md) for the implemented reward presets.

Version `0.3` adds designer-configurable replay rewards, component-level reward
traces, replay-environment cohort support, slot/task/budget validation and a
per-trial policy factory. `ElectrolyteReplayEnv.reset()` now returns `(obs, info)`;
its trace schema is version 2 and its default reward is best-observed improvement
plus a target bonus. Historical v0.2 replay returns/traces are not interchangeable.

## Quick start

```bash
cd MatLabGYM
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .

python -m matlabgym.demo --seed 7
python examples/run_electrolyte_line.py
python examples/compare_rewards.py --output /tmp/matlabgym-reward-comparison.json
python examples/run_electrolyte_screening.py --output /tmp/electrolyte-screening
python -m unittest discover -s tests -v
```

No API key, GPU, database, or external service is required.

## Agent API

`LabGymEnv.reset` follows the modern Gymnasium return shape without requiring Gymnasium:

```python
observation, info = env.reset(seed=7)
result = env.step(action)
```

The environment accepts five commands:

| Command | Purpose |
| --- | --- |
| `start_operation` | Start one registered tool operation. |
| `start_skill` | Start an atomic multi-step skill. |
| `stop_job` | Stop a running interruptible tool. |
| `advance_time` | Advance deterministic logical time and complete due jobs. |
| `poll` | Read state without advancing time. |

Start an operation:

```python
from matlabgym import Action, build_electrolyte_line_env

env = build_electrolyte_line_env()
observation, info = env.reset(seed=7)

result = env.step(Action("start_operation", {
    "operation_id": "mix_electrolyte",
    "request_id": "mix-001",
    "parameters": {
        "recipe": {"components": [
            {"material": "EC", "fraction": 0.3},
            {"material": "EMC", "fraction": 0.7}
        ]},
        "batch_size_ml": 20.0
    }
}))
```

A successful start returns a job ID, logical completion time, incremental cost, and episode total cost. A failed start returns a stable `failure_code`, reason, and retryability flag. Mutating commands (`start_operation`, `start_skill`, `advance_time`, and `stop_job`) are idempotent by `request_id`: an identical retry returns `replayed: true` without changing state, charging cost, or assigning reward again; reuse for a different request is rejected.

## Tool and skill execution

The bundled `run_electrolyte_cell_line` skill executes all six stages atomically:

```python
accepted = env.step(Action("start_skill", {
    "skill_id": "run_electrolyte_cell_line",
    "request_id": "campaign-001",
    "parameters_by_step": {
        "mix": {
            "recipe": {"components": [...]},
            "batch_size_ml": 20.0
        }
    }
}))

finished = env.step(Action("advance_time", {
    "minutes": 905,
    "request_id": "wait-001"
}))
```

Completion produces six episode-scoped artifacts with parent lineage and per-stage logical completion times, ending in a `cell_test_report`. Trying to stop the atomic skill returns `NOT_INTERRUPTIBLE`. Running stages as individual tools allows the environment to check each intermediate artifact and reject out-of-order execution.

## Reward evolution

Reward is supplied when the environment is constructed:

```python
from matlabgym.domains import build_electrolyte_line_env
from matlabgym.lab import RewardSpec

env = build_electrolyte_line_env(RewardSpec(
    version="experiment-efficiency-v2",
    completed=0.5,
    invalid=-2.0,
    goal=20.0,
    cost_weight=0.01,
    time_weight=0.001,
))
```

The reward version and full configuration are included in the environment manifest. Construction validates the task, registry, platform, backend, schema, budget, reward specification, and reward implementation against that manifest, and the registry is frozen when the runtime is created. Agents may evolve policies, planners, skills, or harnesses against a fixed manifest. Changing reward creates a new benchmark version rather than silently changing an active evaluation.

## Existing environments

- `PlanningEnv`: deterministic five-stage workflow fixture retained for API compatibility.
- `ElectrolyteReplayEnv`: discrete conductivity replay/fixture environment for evidence-driven decisions.
- `ElectrolyteEnv`: asynchronous mixing and characterization with delayed replay measurements and query-budget reservations.
- `LabGymEnv`: protocol compiler and asynchronous execution framework.
- `build_electrolyte_line_env`: executable orchestration reference for the six-stage interface template.

## Verification guarantees

The current tests cover:

- valid end-to-end skill execution;
- out-of-order artifact rejection;
- tool stop and atomic-skill stop rejection;
- resource and parameter validation;
- idempotent request IDs;
- compiled-plan integrity and stale-manifest rejection;
- source-protocol attestation for externally submitted plans;
- finite time inputs and hard episode deadlines;
- sample locking, consumption, and collision-free IDs;
- observation and trace isolation from caller mutation;
- load-aware selection across equivalent resources;
- deep-copy isolation for submitted nested parameters;
- cross-episode artifact isolation;
- configurable reward versions;
- compiler rejection of type-incompatible protocol chains;
- deterministic replay behavior of the earlier decision environment.
- fail-closed benchmark admission, sparse measured-support replay and replicate handling;
- endpoint evidence aggregation across a complete episode;
- full deterministic replay verification with required provenance fields.

The runtime emits deterministic event logs and the environment emits transition traces. They are audit artifacts for the deterministic verifier described below.

Version `0.2` now includes a deterministic full-trace verifier in
`matlabgym.replay`. It compares manifest, before/after public state, result
payload, endpoint evidence, reward, terminal flags and state hash. It is valid
for this deterministic backend only; it is not evidence of physical start,
scientific validation, or a LabBench reproduction.

The benchmark layer includes fail-closed admission contracts, a fixed-slot
execution-only cohort runner, and synthetic paired operators for invalid-action,
duplicate-action and time-delay stress cases. The fixture has no calibrated
scientific oracle, no real-failure operator or prompt-injection sandbox, and no
scientific benchmark claim is admitted by default.

## Real-lab adapter boundary

The deterministic runtime is a reference backend. A production adapter should preserve the same public result schema while mapping:

```text
submit_plan   -> scheduler/API dispatch
poll          -> external job status
stop_job      -> platform-supported cancellation
artifact_id   -> laboratory sample/result ID
logical ETA   -> observed/configured ETA with source metadata
cost          -> observed/configured/proxy value with explicit units
```

Real execution must keep `accepted`, `dispatched`, `started`, and `completed` distinct. A dispatch acknowledgement is not evidence that an experiment started or produced a valid scientific outcome.

## Scientific scope

The repository still contains no production laboratory connector or calibrated materials-performance model. The six-stage line validates platform contracts and orchestration, not electrolyte chemistry. The analytic conductivity fixture remains a smoke-test oracle and must not support scientific claims.

The current implementation is an execution-only substrate. It does not claim
to reproduce the robotic-chemistry stress test, its 45-workstation corpus,
4,608-trial matrix, expert executable labels, or physical deployment results.
The cohort runner and stress operators are synthetic execution tools; they do
not provide real-failure evidence, scientific oracle outcomes, or physical
start/completion telemetry.
The literature-to-contract audit and the remaining gates are recorded in
[`docs/literature_traceability.md`](docs/literature_traceability.md).

## References

- Rauschen et al., *Universal chemical programming language for robotic synthesis repeatability*, Nature Synthesis 3, 488-496 (2024). https://doi.org/10.1038/s44160-023-00473-6
- Cronin Group, χDL official repository. https://gitlab.com/croningroup/chemputer/xdl
- Guo et al., *Stress-testing large language model agents in a robotic chemistry laboratory*, 2026. https://arxiv.org/abs/2607.23045
- Beeler et al., *ChemGymRL: A customizable interactive framework for reinforcement learning for digital chemistry*, Digital Discovery 2024. https://doi.org/10.1039/d3dd00183k
