# 电解液场景 v0：执行与科学反馈闭环

首版实现 `ElectrolyteEnv`，使用[统一接口](uniform_api.md)，在有限候选目录中执行“配液／混合 → 电导率表征 → 获得结果 → 选择下一候选”。它复用产线的registry、compiler、资源锁、异步job及artifact lineage。`ElectrolyteTask`固定目标、预算、温度和模拟设备配置。

## 操作与边界

| 项目 | 当前实现 |
|---|---|
| 配液 `mix_electrolyte` | 输入支持目录中的formulation_id和batch_size_ml；到时生成electrolyte_batch:mixed；不会提前释放电导率 |
| 表征 `characterize_electrolyte` | 输入已完成配液的artifact ID与temperature_c；到时生成conductivity_report，metadata记录测量值和oracle快照hash |
| `measure_electrolyte` skill | 将上述两步合成一个不可中断实验；默认75逻辑分钟；原子模式在整体完成时公开产物 |
| 重规划 | Agent可读取本episode所有已测值、样品、job、剩余预算，再启动下一候选；也可逐步调用两个operation |
| 支持域 | 仅接受冻结数据里已有的formulation/condition；不对未观测配方用猜测值充当Ground Truth |
| 预算 | 限制动作数、完成测量数和逻辑时间；启动表征/实验skill时预留测量配额，防止并发超额 |
| 停止 | 单步可模拟停止；停止表征将输入样品标为quarantined，禁止直接复用；没有自动恢复操作 |
| 结果 | best-found、simple regret、有效experiments-to-target、actions-to-target、合法动作率、逻辑时间与query count |

配液选择的是已知候选ID，不是任意新配方生成；CSV可缺少成分字段，此时只能做ID级replay，不能证明配方物理合法。当前只支持整数摄氏温度；fractional temperature明确拒绝，不会静默取整。

同一条件重复测量被拒绝，已经预留的条件也不能并发再次提交。同request_id重放除外，但不重复测量或奖励。真实带噪声复测需要单独的replicate数据和动作契约。

## 运行

```bash
python -m pip install -e .
python examples/run_electrolyte_screening.py \
  --policy adaptive --seed 7 --budget 5 --target 12 \
  --output /tmp/electrolyte-screening
```

输出 `manifest.json`、`metrics.json`、`trace.json` 和 `run.json`，后者记录数据状态和严格重放验证结果。默认oracle是synthetic fixture，示例结果不是科学benchmark成绩。

可选策略为 `public_order`、`random`、`adaptive`。adaptive是基于已测候选的最近邻贪心估计，只使用公开的ec/pc/emc/salt_m和本episode已测值；特征不完整时退回公开顺序。它不是BO、LLM或训练过的科研策略，提供它是为了验证反馈能进入下一轮决策。

## 接入数据

```bash
python examples/run_electrolyte_screening.py \
  --csv /path/to/conductivity.csv --policy random --budget 5 --target 12 \
  --output /tmp/electrolyte-csv
```

CSV必填列：`formulation_id,temperature_c,conductivity_ms_cm`；可选列：`uncertainty_ms_cm,source,ec,pc,emc,salt_m`。单位由列名约定：摄氏度、mS/cm；不自动换算。重复键默认拒绝；不确定度必须非负且有限，测量值须有限。还需由数据负责人提供来源、许可、实验批次、质量控制和划分依据，导入CSV不会自动设置scientifically_validated=true。

## 与六阶段产线的关系

`build_electrolyte_line_env()`仍用于配液→表征→注液一封→化成分容→二注排气→测试的完整执行验收，使用相同五类命令和统一info。`ElectrolyteEnv`只对前两阶段提供电导率证据；后四阶段没有真实电芯性能oracle。两种任务可以由同一个runner调度，但不能把电导率达标报告成容量或寿命达标。

两步时长、批量范围、容量和中断能力目前均为sandbox配置，未获真实产线签认。停止隔离是工程保守规则，不代表已经模拟了样品损伤。预算/时间截断不会冒充物理停止，公共job状态仍保留。真实平台接入前按[Inventory](electrolyte_operation_inventory.md)与[验收清单](electrolyte_interface_acceptance.md)关闭相关DEC/AC事项。

## 验收证据

`tests/test_electrolyte_screening.py`覆盖逐步操作、原子skill与逐步计分一致、延迟反馈、产物lineage、并发预算、重复请求、停止隔离、支持域、同seed重置隔离、四种环境公共契约、cohort和完整info重放。`tests/test_screening_policy.py`验证策略只读公共观测、等待任务及反馈影响选点。计划与未完成事项见[Roadmap](roadmap.md)和[TODO](TODO.md)。
