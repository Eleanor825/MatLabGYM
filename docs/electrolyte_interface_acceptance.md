# 电解液六阶段接口验收清单

本清单配套[六阶段 Operation Inventory](electrolyte_operation_inventory.md)，用于对齐模拟器契约、平台接口和真实执行证据。**当前是文档化验收要求，不是真实平台验收报告。** 以下“已有测试”仅指只读检查发现的测试代码；本次文档工作未运行新测试，也未执行真实实验。平台证据尚未提供，不能据此判定任何真实平台用例通过。

检查范围：`src/matlabgym/domains/electrolyte_line.py`、`src/matlabgym/lab/runtime.py`、`src/matlabgym/lab/environment.py`、`tests/test_lab_framework.py`。下文测试名均位于最后一个文件。源码函数与测试名称作为可检索证据；验收时另行记录提交版本。

## 阶段和证据约定

| 阶段 | 当前 operation ID | 输入 kind / state | 输出 kind / state |
| --- | --- | --- | --- |
| S1 配液 | `mix_electrolyte` | 无输入 artifact | `electrolyte_batch` / `mixed` |
| S2 电解液表征 | `characterize_electrolyte` | `electrolyte_batch` / `mixed` | `characterized_electrolyte` / `characterized` |
| S3 注液与一次封口 | `inject_and_first_seal` | `characterized_electrolyte` / `characterized` | `first_sealed_cell_batch` / `first_sealed` |
| S4 化成与分容 | `formation_and_capacity` | `first_sealed_cell_batch` / `first_sealed` | `formed_cell_batch` / `formed` |
| S5 二次补液与脱气 | `second_fill_and_degas` | `formed_cell_batch` / `formed` | `degassed_cell_batch` / `degassed` |
| S6 电池测试 | `test_cell_batch` | `degassed_cell_batch` / `degassed` | `cell_test_report` / `completed` |

“当前”描述已实现的模拟行为；“要求”描述拟议验收标准，若超出当前行为即为待实现或待确认项。`accepted`、模拟 `completed`、物理启动、物理完成和科学有效性必须分别取证。平台负责人应逐项填写后附模板，结论限“通过 / 不通过 / 待确认 / 不适用（附理由）”。AC ID 保持稳定，不因调整顺序而重编号。

S1–S6 分别对应 Inventory 的 OP-01–OP-06。待确认决定与验收项映射：DEC-01 表征前置 → AC-02/10；DEC-02 实体与消耗 → AC-09/12/15；DEC-03 启停与 skill 边界 → AC-07/08/15/16；DEC-04 参数单位 → AC-01–06/11；DEC-05 失败样品处置 → AC-15/16/19；DEC-06 资源容量 → AC-12；DEC-07 耗时成本 → AC-13/17；DEC-08 结果质量 → AC-02/06/18；DEC-09 API、事件、幂等与真实 ID → AC-08/09/14/18–20。

## 六阶段正常路径

以下六项分别使用 `start_operation`，新 `request_id`，S2–S6 的 `input_id` 指向前一步完成后的 artifact。前置条件为 episode 已 reset、资源空闲且预算足够。每项都应先收到 `accepted` 和 `job_id`，再在完成时获得输出；不得把受理响应当成产物。模拟检查通过 `advance_time` 推进逻辑时间；真实平台应改用经确认的状态查询/回调及完成证据。

| ID / 阶段 | 前置、输入与动作 | 预期输出、状态和副作用 | 当前已有证据 / 未覆盖 | 平台待提供证据 |
| --- | --- | --- | --- | --- |
| AC-01 / S1 | 无输入；提交平台确认的 `recipe` 对象与 `batch_size_ml=20`；模拟推进 30 min | 产出 S1 输出；记录参数、资源、生产 job；模拟提交计费 12 | `test_tool_can_be_stopped_when_interruptible` 覆盖配液受理；`test_physical_artifact_cannot_be_used_by_two_jobs` 覆盖配液完成。未逐项断言全部元数据 | 配方版本、原料批号、实配体积、混合记录、容器/批次 ID、物理完成事件 |
| AC-02 / S2 | 已完成 S1；`methods=["density", "conductivity"]`；模拟推进 45 min | 产出 S2 输出，父引用指向 S1；当前完成时将被消费输入标记 consumed；模拟计费 20 | `test_physical_artifact_cannot_be_used_by_two_jobs` 覆盖仅 conductivity 的表征完成与消费。未验证真实测量值及方法语义 | 方法与单位、仪器和校准版本、原始数据、检测报告、取样量/余样、表征是否必选的签认 |
| AC-03 / S3 | 已完成 S2；`cell_count=8`；模拟推进 60 min | 产出 S3 输出，父引用指向 S2；不可中断；模拟计费 35 | 六阶段 skill 测试间接覆盖；无单操作完整正常路径断言 | 注液量、逐电芯 ID 与批次映射、一次封口完成及质量记录 |
| AC-04 / S4 | 已完成 S3；`protocol="formation-v1"`；模拟推进 480 min | 产出 S4 输出；不可中断；模拟计费 80 | 六阶段 skill 测试间接覆盖；字符串对应真实协议及分容指标未覆盖 | 协议版本、通道映射、化成曲线、容量结果、异常电芯清单与终态 |
| AC-05 / S5 | 已完成 S4；`vacuum_kpa=80`；模拟推进 50 min | 产出 S5 输出；不可中断；模拟计费 30 | 六阶段 skill 测试间接覆盖；补液、压力基准与最终封装细节未覆盖 | 补液配方/数量、压力绝压或表压定义、脱气记录、工艺边界及完成确认 |
| AC-06 / S6 | 已完成 S5；`test_protocol="capacity-v1"`；模拟推进 240 min | 产出 S6 报告 artifact；环境目标达到后 terminated；模拟计费 55。当前报告为元数据对象，不含真实测试数据 | `test_atomic_skill_reaches_goal` 间接覆盖目标终止；未覆盖报告数据、测量质量与科学结论 | 测试协议、原始曲线、指标/单位、报告位置与校验信息、有效性判据及审核结果 |

## 跨阶段接口与故障验收

| ID / 适用阶段 | 前置、输入与动作 | 预期输出、状态和副作用（当前 / 要求） | 当前已有证据 / 未覆盖 | 平台待提供证据 |
| --- | --- | --- | --- | --- |
| AC-07 / S1–S6、整线 | reset 后调用 `start_skill(run_electrolyte_cell_line)`，仅覆盖 mix 配方及 20 mL；依次 poll、推进时间至 905 min | 当前：一个 job，提交时预留整计划资源并计费 232；最终一次生成六个 artifact，最后为报告；逻辑累计完成时间为 30/75/135/615/665/905 min。要求：核对六阶段顺序、父引用、全部 ID 和终止结果；单操作串联路径也应补齐验证 | `test_atomic_skill_reaches_goal`、`test_skill_artifacts_record_per_step_completion_times`、`test_completed_skill_replay_returns_all_artifacts`；无六次独立操作完整链路测试；skill 中途不发布逐阶段产物 | 一份全链路平台执行记录，包含阶段事件、物料谱系、设备、成本和报告；说明平台是单总 job 还是总/子 job 结构 |
| AC-08 / S1–S6 | 提交合法启动，随后 poll，未达到完成条件时检查响应及 artifact | 当前：首响应 `success=true, status=accepted, endpoint=dispatch_verified`，内部 job 为 running；受理不产生 artifact；poll 不推进时间。要求：客户端不得把 success、running 或 ETA 当作完成 | `test_atomic_skill_reaches_goal` 断言 accepted；`_submit_plan`、`_complete`、`LabGymEnv.step` 给出行为；poll 无推进及未完成无产物缺少专门断言 | 受理/排队/运行/完成状态映射、API 响应样例、查询和回调契约，以及受理后仍未启动案例 |
| AC-09 / S1–S6 | 对一个请求核对 request、job、输入输出 artifact、平台调度任务、样品/容器/电芯和报告标识 | 当前：job/artifact ID 是 episode 内逻辑标识；artifact 含 producer_job_id、parent_ids 及参数/资源元数据。要求：真实平台 ID 单独映射并可双向追溯，不以模拟 ID 充当平台已存在证据；批次到单电芯拆分规则明确 | `_new_job_id`、`_new_artifact_id`、`_complete`；`test_artifacts_are_episode_isolated`、`test_initial_artifact_id_is_not_overwritten`；真实 ID 映射未实现 | ID 命名空间、唯一性与生命周期、总/子任务和批次/电芯关系、映射样例及查询结果 |
| AC-10 / S2–S6 | 使用不存在、错误 kind/state、被消费或跨 episode 的输入；尝试跳过 S2 直接注液 | 当前：链路由输入 kind/state 强制；缺输入等拒绝且不得启动/扣费。要求：平台明确表征是否每批必做、可否复用历史报告及跳过条件；确认前保留当前必经 S2 契约，不能宣称其为已确认物理规则 | `test_out_of_order_input_is_rejected`、`test_compiler_rejects_incompatible_chain`、`test_forged_compiled_plan_cannot_bypass_input_chain`、`test_artifacts_are_episode_isolated`；无平台表征必选签认 | SOP 版本、工艺负责人签认、各状态定义、表征报告有效期及异常重入规则 |
| AC-11 / S1–S6 | 提交边界值、缺字段、类型错误、非有限数及未知字段；核对 recipe/methods/protocol 的内部语义 | 当前：注册了 mL 1–1000、cell_count 整数 1–96、kPa 1–101；recipe 仅 object、methods 仅 array、两类 protocol 仅 string。要求：补齐配方组分/浓度基准、方法枚举、协议版本、压力基准与补液参数；单位换算及空值策略有明确契约，不能以顶层类型通过代表物理有效 | `test_parameter_bounds_are_enforced`、`test_malformed_payload_is_rejected_without_crashing`、`test_huge_integers_are_rejected_without_overflow`、`test_unknown_skill_step_override_is_rejected`；完整物理语义和单位换算未覆盖 | 字段字典、必填/默认/范围、单位和精度、枚举与协议注册表、有效及无效请求样例 |
| AC-12 / S1–S6 | 占满资源后提交另一 job；并发使用同一输入；已完成消费后再次使用 | 当前：容量不足 `RESOURCE_BUSY`，占用样品 `ARTIFACT_BUSY`，两者可重试；消费后 `ARTIFACT_CONSUMED` 不可重试；拒绝不得新增计费/占用。skill 整体预留全部涉及资源。要求：平台确认容量计量、锁范围、排队和释放时点 | `test_resource_capacity_is_enforced`、`test_physical_artifact_cannot_be_used_by_two_jobs`、`test_scheduler_uses_second_resource_of_same_type`；测试名中的 physical 仍指模拟 artifact | 真实资源表及容量、锁和队列日志、并发竞争回放、部分资源占用失败的回滚记录 |
| AC-13 / S1–S6 | 剩余预算不足以覆盖计划后启动；分别检查拒绝、完成、停止、重试账目 | 当前：按计划全额提交计费；超预算拒绝 `BUDGET_EXCEEDED`；停止不退款。要求：拒绝无扣费，平台区分预估/预留/实际/退款并确认币种，不能把模拟 cost 视为真实报价 | `_submit_plan`、`stop_job`；指定测试文件未见超预算专门用例；幂等测试覆盖不重复计费 | 币种、收费/退款规则、价格版本、预算不足响应、账单对账与实际支出证据 |
| AC-14 / S1–S6 | 同 request_id 重试相同启动；改变参数或操作；完成后重放；重试 advance/stop；模拟网络丢响应后重试 | 当前：成功启动相同请求复用 job、零增量成本且不重复奖励；同 ID 不同请求 `REQUEST_CONFLICT`；控制命令也去重。要求：真实平台与 adapter 跨重启持久化去重；明确保留期、查询补偿及拒绝请求的重试语义 | `test_request_id_is_idempotent`、`test_request_id_conflict_is_rejected`、`test_completed_idempotent_request_cannot_repeat_reward`、`test_completed_skill_replay_returns_all_artifacts`、`test_advance_and_stop_requests_are_idempotent`；当前记录为内存且 reset 清空，网络/重启未覆盖 | 服务端幂等保证、持久化作用域、丢响应重试日志、单次物理执行与单次扣费证据 |
| AC-15 / S1、S2、S6 | 对运行中的可中断单操作发 stop；重点检查已持有输入样品的 S2/S6 | 当前：置 stopped、释放资源和输入分配，不产新 artifact、不退款；未将输入样品标为未知，因此 snapshot 可能再次显示 available。**要求：真实执行后的样品状态未知时，禁止把它当作可复用输入；应隔离/锁定，待平台确认余量、污染、损伤与恢复资格后显式放行。** 此要求尚未实现 | `test_tool_can_be_stopped_when_interruptible` 只覆盖无输入 S1；`stop_job`/`snapshot` 显示缺口；未覆盖停止后输入隔离、恢复与再利用 | 停止确认、设备安全状态、样品处置/余量记录、恢复条件及授权人、禁止未知样品下游启动的案例 |
| AC-16 / S3–S5、整线 skill | 对不可中断操作或 `run_electrolyte_cell_line` job 发 stop；含 skill 正处于可中断首步的情况 | 当前：计划不可中断则拒绝 `NOT_INTERRUPTIBLE`，job 保持运行，不释放预留；整线 skill 始终不可中断。要求：明确软件 stop 与设备急停的区别、急停后恢复和样品隔离流程；不可假定当前 API 可急停真实设备 | `test_atomic_skill_cannot_be_stopped`、`test_non_interruptible_operation_cannot_be_downgraded`；单阶段真实急停及恢复未覆盖 | SOP、工艺不可中断区间、设备急停/联锁能力、故障处置责任人及验证记录 |
| AC-17 / S1–S6 | 核对每阶段 duration/cost；在逻辑时间与墙钟不一致时检查 ETA；达到环境时间/步数上限 | 当前：耗时 30/45/60/480/50/240 min，cost 12/20/35/80/30/55，均为静态模板；owner 为 `battery-platform-owner`，provenance 为模拟模板字符串。时间上限可截断 episode 而 job 仍 running。要求：补充测量/估计来源及版本，明确 timeout 不代表物理停止 | `test_skill_artifacts_record_per_step_completion_times`、`test_invalid_time_inputs_do_not_advance_or_create_reward`、`test_time_limit_caps_advance_before_completion`；无真实耗时/成本标定 | 排队与工艺耗时区分、时间戳与时区、估计区间和样本来源、费用表、超时后 job 接管与追踪规则 |
| AC-18 / S1–S6 | 从受理到启动、完成、科学有效逐级检查 endpoint evidence | 当前：`_endpoint_evidence` 对 STARTED 固定 false，来源 `not_claimed_by_simulator`；COMPLETED 仅 `deterministic_completion`；SCIENTIFICALLY_VALIDATED 固定 false。要求：物理启动需设备/调度端关联事件；物理完成需真实终态及可追溯产物；科学有效需独立判据，不能由 artifact 存在推导 | `LabGymEnv._endpoint_evidence`；指定测试文件无物理证据用例。模拟内部 running、逻辑到时及 metadata 时间戳均不是物理事件 | 带平台 job/device/sample ID 的启动日志、完成事件、原始数据/报告、证据来源和时间戳，以及科学判据版本与审核人 |
| AC-19 / S1–S6、整线 | 注入提交后断连、轮询超时、回调重复/乱序、阶段失败、部分电芯失败、进程重启 | 当前：确定性模拟未实现真实断连与 partial failure；skill 完成时一次生成全部输出，无法代表中间阶段物理故障。要求：未知执行状态不能自动重发造成重复物理动作；保留已完成阶段和部分产物、隔离不确定样品、核算已发生成本，并按确认后的策略恢复/终止；不得伪造整线 completed | `advance_time`、`_complete` 仅给出确定性完成路径；指定测试文件未覆盖故障注入、部分失败和恢复 | 故障状态机、错误码/可重试定义、事件排序与去重、恢复/对账接口、故障注入报告与部分成功样例 |
| AC-20 / S1–S6 | 记录环境/注册表/平台/奖励版本，修改平台资源或契约后重用旧计划；核对观测与 trace | 当前：manifest 绑定 registry/platform hash、backend 和 schema；过期/伪造计划拒绝，观测与 trace 拷贝隔离。要求：验收报告绑定实际代码及平台接口版本，不能只保留占位 owner/provenance | `test_stale_compiled_plan_is_rejected`、`test_manifest_mismatch_fails_fast`、`test_manifest_backend_and_schema_are_bound_to_runtime`、`test_source_hash_tampering_is_rejected`、`test_observation_cannot_mutate_runtime_or_prior_trace` | 平台接口版本、设备配置快照、代码提交、契约版本、日志/报告索引及真实负责人的确认 |

## 平台确认记录模板

每个 AC 单独复制一份，涉及多阶段时分别列证据。没有证据时填写“待确认”，不将源码实现、模板 owner 或测试定义视为平台签字。

| 字段 | 填写内容 |
| --- | --- |
| 验收 ID / 适用阶段 | AC-__ / S__ |
| 验收负责人 / 平台确认人 | 姓名、团队、职责；待填写 |
| 确认日期 | YYYY-MM-DD，时区；待填写 |
| 证据来源及版本 | 平台 API/SOP/设备固件/测量或收费依据的名称、版本和链接；待填写 |
| 代码与配置版本 | commit、manifest_hash、registry_hash、platform_hash、backend、schema_version；待填写 |
| 前置状态与输入 | 去敏后的参数、预算、资源/样品状态、协议版本；待填写 |
| 实际动作与标识 | request_id、逻辑 job/artifact ID、真实平台 job/device/sample/report ID；待填写 |
| 实际输出和副作用 | 状态序列、原始响应、证据时间戳、资源/样品变化、费用和数据位置；待填写 |
| 预期与实际差异 | 对照该 AC 的当前行为和要求，记录缺口；待填写 |
| 结论 | 通过 / 不通过 / 待确认 / 不适用（理由）；初始为待确认 |
| 后续事项 | 责任人、目标日期、补充证据或实现事项、复验记录；待填写 |

平台验收完成应以逐项证据及负责人确认记录为准。尚未确认的表征必选性、单位/协议语义、真实 ID、停止后样品处置、物理启动/完成和故障恢复，均应保留为明确待办，不能由六阶段模拟正常路径的成功替代。
