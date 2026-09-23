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

**现在的位置：M0 工程原型已完成，M1 准备中。** 我们已经能在软件里跑完“选配方 → 配液 → 测电导率 → 根据结果继续选配方”。下一步要让实验室确认操作规则，并接入真实测量数据。

- [x] **[M0 · 把实验环境跑起来](docs/roadmap.md#m0)**：统一操作接口，打通电解液筛选流程，并能重放检查每一步。已合并 main。
- [ ] **[M1 · 让环境符合真实实验](docs/roadmap.md#m1)**：确认实验室实际能做什么、如何处理失败，接入可靠的配方和测量数据。清单已备好，待平台确认与数据接入。
- [ ] **[M2 · 验证 Agent 是否真的有用](docs/roadmap.md#m2)**：在相同实验预算下比较不同策略，检验实验反馈能否帮助 Agent 少走弯路。待开展。
- [ ] **[M3 · 接上实验室，先观察和核对](docs/roadmap.md#m3)**：先读取真实任务、样品和结果，检查断连、重复请求和失败恢复，不让 Agent 直接操作设备。待开展。
- [ ] **[M4 · 做小规模真实实验，再扩展](docs/roadmap.md#m4)**：在确认的操作范围内试运行，验证结果和成本，再考虑其他材料及多 Agent。后续阶段。

### 现在做了什么，怎么做的

- **流程已经能跑。** Agent 用同一套接口启动操作、查看状态和读取结果；配液和表征完成后，环境才返回电导率。我们把步骤顺序、设备占用和实验预算写成了可检查的规则。
- **结果可以复查。** 每次运行保存操作、样品关系、结果和奖励，再重放一遍核对是否一致。95 项测试、三种示例策略及多 Python 版本 CI 已通过，代码见 [PR #2](https://github.com/Eleanor825/MatLabGYM/pull/2)。
- **真实验证还没完成。** 目前使用演示数据或尚未校准的 CSV 数据回放；完整六阶段产线只验证了模拟流程，还没有接入真实电芯性能结果，也没有控制真实设备。

点击各阶段查看“要解决什么、准备怎么做、做到什么程度算完成”。具体任务、优先级和负责角色放在 [TODO](docs/TODO.md) 中，完成后再勾选；正式版本发行包也仍在待办中。

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
