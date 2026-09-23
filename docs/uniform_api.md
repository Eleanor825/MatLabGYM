# Uniform Scientific Environment API v1

所有内置环境共享同一组生命周期、动作返回、成本来源和审计接口。域专属的科学目标与参数保留在各自 Task 和 operation contract 中；统一接口不要求把“完成产线”和“达到电导率”当成同一个目标。

## 生命周期与交互

```python
from matlabgym import Action, ElectrolyteEnv, ElectrolyteTask, ScientificEnv, make_fixture_task

env = ElectrolyteEnv(ElectrolyteTask(), make_fixture_task()[1])
assert isinstance(env, ScientificEnv)
obs, info = env.reset(seed=7)
schemas = env.action_specs()

obs, reward, terminated, truncated, info = env.step(Action("poll", {}))
# 也可保持属性访问：result = env.step(...); result.observation / result.info
```

| 接口 | 所有内置环境的约定 |
|---|---|
| `reset(*, seed=None, options=None)` | 返回 `(Observation, info)`；清空episode状态；不支持的非空options拒绝。任务、oracle和reward在构造时固定 |
| `action_specs()` | 返回命令名和参数 JSON Schema；产线环境附带 operation/skill registry、输入实体类型/状态和参数单位 |
| `step(Action(name, parameters))` | 返回 `StepResult`，可解包为 `(obs, reward, terminated, truncated, info)`；episode结束后拒绝新step |
| `observe()` / `public_snapshot()` | 返回公共观测/可序列化公共状态快照；不包含未测outcome或全域最优值 |
| `trace()` | 返回完整轨迹的深拷贝 |
| `evaluate()` | evaluator侧调用，返回域专属原始指标；可能读取完整支持域，禁止作为Agent工具 |
| `episode_outcome()` | 返回同一 `EpisodeOutcome`，供cohort runner使用；运行器不再读取特定backend的runtime内部状态 |
| `budget_spec` | 域声明的预算上限字典；TrialSlot中已登记的预算字段必须逐项匹配，未知字段拒绝 |
| `manifest` | 提供 `to_dict()` 与 `manifest_hash`；绑定task、reward及后端适用的registry/platform/oracle版本 |

`Observation.available_actions` 是状态相关动作提示；需要完整参数约束时使用 `action_specs()`。step仍是本项目的对象协议，没有承诺完整Gymnasium spaces/wrappers兼容性。Planning/replay的便捷动作名与异步产线命令可以不同，外层调用和返回协议保持一致。

## 统一 info

reset和step均有以下字段：

```json
{
  "api_version": "1.0",
  "episode_id": "episode namespace",
  "manifest_hash": "sha256:...",
  "state_hash": "sha256:...",
  "results": [],
  "reward_components": {},
  "failure_code": null,
  "provenance": {"backend": "backend identifier"},
  "costs": []
}
```

`results` 每项规范化为 `success/status/request_id/job_id/produced_artifact_ids/failure_code/failure_reason/retryable/replayed`，无此概念的值为null、空列表或false；允许额外域字段。顶层failure_code表示本次动作的失败，不代表历史整个episode是否有失败。

`costs`记录**本次动作的增量**，每项为 `{quantity, unit, source}`；quantity有限且非负，source只能是 observed/configured/proxy/unknown。不存在可靠金额时不生成货币数字。旧六阶段演示成本的unit为 `configured_cost_unit`；电导率查询为 `measurement_query`/proxy；模拟逻辑时间为minute/configured。不同unit不能直接求和作业务成本。观测中的 `budget_remaining` 是各域主预算的便捷字段，多维预算应读取 `budget_spec` 及域公共状态。

`accepted`只表示接受任务；`completed`也可能仅为模拟完成。物理启动/完成及科学验证应读取独立endpoint evidence，不能从success或reward推断。

## 当前域

| 环境 | 任务边界 | 动作 |
|---|---|---|
| `PlanningEnv` | 五阶段规划fixture | prepare/assemble/formation/cycle/characterize |
| `LabGymEnv` / `build_electrolyte_line_env` | 六阶段产线执行fixture | start_operation/start_skill/stop_job/advance_time/poll |
| `ElectrolyteReplayEnv` | 直接查询有限支持域的电导率 | measure_conductivity |
| `ElectrolyteEnv` | 配液、表征、获得证据、选择下一个候选 | 与产线相同的五类命令；见[电解液场景](electrolyte_scenario.md) |

## 隔离、重试和重放

异步环境用request_id对成功的变更请求去重；同ID不同payload拒绝。相同请求重放不重复计费或质量奖励，但它仍是一次Agent交互，可能消耗动作数预算。失败请求的重试与已成功请求的去重不能混为一谈。

非JSON或NaN动作规范化为 `__invalid_payload__` 后拒绝，保证失败轨迹本身也能重放；不保留不可序列化的原始payload。`verify_trace`比较公共状态、规范化结果、奖励分项、完整info、终止标志和manifest。带产物ID的异步环境记录reset_count，同seed多次reset仍产生不同命名空间；verifier按记录恢复reset序号，拒绝超过10,000次的reset provenance。

这只是单进程对象隔离。跨worker唯一身份、持久化幂等、进程/文件/网络沙箱仍在[TODO](TODO.md)中；不要把env或evaluate的Python对象直接暴露给可执行任意代码的Agent。

## 版本迁移

v0.4包含此前本地v0.3 reward修改；PlanningEnv.reset迁移为二元组，step支持五元组解包，trace增加统一info。旧轨迹不保证按新schema重放，应保留其代码/manifest版本。配置变化使用新环境实例和新manifest；runner中有内部状态的策略使用 `policy_factory(slot)`。
