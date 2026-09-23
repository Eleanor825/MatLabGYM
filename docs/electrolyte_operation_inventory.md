# 电解液六阶段 Operation Inventory

版本：draft-0.1；整理日期：2026-09-23；状态：**待平台确认，不作为真实设备控制规范**。

本表把会议要求转成可填写、可审查的接口清单。`当前模拟`表示代码已有行为；`待确认`表示缺少平台/SOP依据；`建议契约`表示工程建议，尚未实现或验收。当前没有任何条目标记为平台确认完成。配套见 [接口验收清单](electrolyte_interface_acceptance.md)。

## 1. 来源与确认责任

| 来源 | 用途 | 证据边界 |
|---|---|---|
| [MATLABGYM LAB模拟接口模板](https://mi.feishu.cn/wiki/UzThw9D2Hi4jCtkFXQuc1HIOnde) | 六阶段、启停边界、tools/skills、I/O和约束要求 | 沿用此前读取的 revision 220 内容，未声称重新获取最新版；这是会议草案，不是签核SOP |
| [项目设计](https://mi.feishu.cn/wiki/SJ0bwxf6XiVPj9kHIvecj4ZSnKg) | 接口可验证性与成本溯源目标 | 研究设计，不替代设备API和现场日志 |
| [产线注册定义](../src/matlabgym/domains/electrolyte_line.py) | 本表所有当前参数、资源、耗时和成本值 | 当前工作区代码；基线 commit `4988df8`；这些值未经真实平台确认 |
| [Runtime](../src/matlabgym/lab/runtime.py)、[环境接口](../src/matlabgym/lab/environment.py)、[契约](../src/matlabgym/lab/contracts.py) | 当前启动、停止、锁定、计费和产物语义 | 仅确定性模拟 |

确认角色（尚未指定人员）：平台接口负责人确认可调用动作和状态；工艺/SOP负责人确认顺序、单位和安全条件；数据负责人确认结果字段及质量规则；工程负责人实现并保存验收证据。代码中的 `battery-platform-owner` 是通用占位字符串，不是已签核的业务 owner。

## 2. 六阶段输入、输出和前置条件

所有“启动”均指 `start_operation`，携带 operation ID、request ID、参数及需要的 input ID。当前六阶段都可单独请求启动，但仅在输入和资源校验通过时接受。

| 编号 / operation_id | 流程 | 当前输入实体与参数 | 当前完成输出实体 / 状态 | 当前前置条件；平台待确认事项 |
|---|---|---|---|---|
| OP-01 `mix_electrolyte` | 配液／混合 | `recipe` 对象、`batch_size_ml`；无 input artifact | `electrolyte_batch` / `mixed` | mixer可用、参数及预算通过；原料库存、容器、清洁、配方有效性和混合完成判据待确认 |
| OP-02 `characterize_electrolyte` | 表征 | OP-01产物 `input_id`；`methods` | `characterized_electrolyte` / `characterized` | 输入为 `electrolyte_batch:mixed`；表征是否必须、取样损耗、仪器校准、数值结果和放行阈值待确认 |
| OP-03 `inject_and_first_seal` | 注液／一封 | OP-02产物 `input_id`；`cell_count` | `first_sealed_cell_batch` / `first_sealed` | 输入为 `characterized_electrolyte:characterized`；干电芯/壳体来源、注液量、含水控制及封装质量待确认 |
| OP-04 `formation_and_capacity` | 化成分容 | OP-03产物 `input_id`；`protocol` | `formed_cell_batch` / `formed` | 输入为 `first_sealed_cell_batch:first_sealed`；静置/浸润是否必需、温控、电流电压边界、分容判据待确认 |
| OP-05 `second_fill_and_degas` | 二注排气 | OP-04产物 `input_id`；`vacuum_kpa` | `degassed_cell_batch` / `degassed` | 输入为 `formed_cell_batch:formed`；二注是否必选、补液量、真空压力定义、最终封口是否包含在本阶段待确认 |
| OP-06 `test_cell_batch` | 测试 | OP-05产物 `input_id`；`test_protocol` | `cell_test_report` / `completed` | 输入为 `degassed_cell_batch:degassed`；测试指标、曲线/单位、有效性与通过阈值、剩余样品状态待确认 |

**顺序未决 DEC-01：**会议示例要求注液一封前“配液完成”；代码要求“表征完成”。平台需选择表征必选、可选或仅特定配方必选，并提供SOP依据。当前代码按表征必选执行，不因本表自动放宽。

**实体未决 DEC-02：**当前每个阶段输出一个新 artifact，并把前序输入标记为 consumed。这个标记是模拟中的使用限制，不证明样品被物理耗尽。表征是否应保持原液身份并另外生成 measurement/report、批次是否需要分样/合样、测试报告如何关联仍存在的电芯，需逐项确认。

## 3. 参数、单位与校验深度

所有范围均为**当前模拟值**，不得当作真实设备安全阈值。下表参数在单步调用中均为必填；整条 skill 为部分参数提供默认值。

| 阶段 | 参数 | 当前类型 / 单位 / 校验 | 整条skill默认值 | 待平台填写 |
|---|---|---|---|---|
| OP-01 | `recipe` | JSON object；没有配方内部语义校验，空对象也通过 | 无 | 成分标识、溶剂比例基准（质量/体积/摩尔）、盐浓度单位、添加剂基准、比例和/容差、禁配组合、配方版本 |
| OP-01 | `batch_size_ml` | number；mL；1–1000 | 无 | 允许范围、计量分辨率/容差、最小余量；是否必须按质量配液 |
| OP-02 | `methods` | array；未校验元素枚举或非空 | `["density", "conductivity"]` | 支持方法及版本、测试温度单位/范围、重复次数、每项结果的单位和质量标志 |
| OP-03 | `cell_count` | integer；1–96；逻辑上为电芯数量，schema未显式声明unit | 8 | 批次/单芯ID、可用电芯数、单芯注液量及单位、一封工艺参数 |
| OP-04 | `protocol` | string；未校验可用协议ID，空字符串也符合类型 | `formation-v1` | 协议注册表/版本、电流倍率、电压、温度、静置及放行条件 |
| OP-05 | `vacuum_kpa` | number；kPa；1–101；绝压/表压未定义 | 80 | 绝压/表压、压力符号与传感器位置、补液量、保持时间、排气/封口顺序 |
| OP-06 | `test_protocol` | string；未校验协议ID | `capacity-v1` | 支持测试协议、仪器量程、结果schema、单位、采样率和质量标准 |

当前通用参数验证可拒绝未知参数、缺失必填字段、错误类型、NaN/Infinity及已声明的数值越界。业务字段尚未加入前，应继续用草案记录，不能随意传入代码并认为已经支持。

## 4. 启动、停止、暂停、恢复与动作粒度

| 阶段 | 当前可独立启动 | 当前模拟可停止 | 当前暂停 / 恢复 | 停止后的关键平台问题 | 真实支持状态 |
|---|---|---|---|---|---|
| OP-01 配液／混合 | 是，资源/参数通过后 | 是 | 不支持 / 不支持 | 已投料量如何记录？混合液是否可接续、返工或只能隔离？ | 待确认 |
| OP-02 表征 | 是，OP-01完成后 | 是 | 不支持 / 不支持 | 已取样是否消耗？部分测量数据能否使用？是否需清洗/重校准？ | 待确认 |
| OP-03 注液／一封 | 是，OP-02完成后 | 否 | 不支持 / 不支持 | 能否在注液前、注液后封口前取消？半成品如何处置？ | 待确认 |
| OP-04 化成分容 | 是，OP-03完成后 | 否 | 不支持 / 不支持 | 是否支持受控停机？停机后的SOC/温度及恢复协议是什么？ | 待确认 |
| OP-05 二注排气 | 是，OP-04完成后 | 否 | 不支持 / 不支持 | 补液、抽真空、封口之间是否有可控边界？停止后密封状态是什么？ | 待确认 |
| OP-06 测试 | 是，OP-05完成后 | 是 | 不支持 / 不支持 | 部分曲线如何标记？电芯当前状态、可复测条件是什么？ | 待确认 |

`stop_job` 当前只针对运行中的 job；不可中断时返回 `NOT_INTERRUPTIBLE`。它不是急停接口。真实设备急停、正常取消、暂停、恢复应由平台分别定义，不可用一个 boolean 推断全部能力。

当前 tools 为以上六个 operation。当前唯一注册的 `run_electrolyte_cell_line` skill 覆盖六阶段，中途不能控制；模拟会预先为完整计划占用资源，并在整体完成时创建全部中间产物，产物metadata记录各阶段逻辑完成时间。它不是已确认的真实全线原子调度能力。

**skill划分 DEC-03：**平台应先标明各 operation 之间是否可观察、可选择下一步、可取消，再决定哪些连续片段可以打包为不可中断 skill。暂不指定新的分组。面向多智能体共享的是已确认的同一套动作契约；增加多个调用者不能改变物理可控粒度，调度器仍需串行化对同一实体的冲突操作。

## 5. 异常及停止后的实体状态

| 阶段 | 当前模拟行为 | 真正执行失败 / 停止后必须补充的状态证据 | 确认前建议的adapter规则（待实现） |
|---|---|---|---|
| OP-01 | 接受前可拒绝；运行中可stop，不生成产物、不退费；尚无工艺失败注入 | 投料/溶解/混合进度、余量、容器、污染和可恢复性 | 未取得明确样品状态时隔离，不把“停止成功”解释为可重试同批次 |
| OP-02 | stop释放锁，原输入不标consumed；完成时输入标consumed | 取样损耗、已完成测量、原液与样品ID、数据是否有效 | 部分报告单独标记，不自动放行到注液 |
| OP-03 | stop被拒绝；默认接受后到时完成 | 注液完成量、封口状态、受影响电芯ID及报废/返工结论 | 不生成完整first_sealed状态，除非有有效完成证据 |
| OP-04 | stop被拒绝；默认接受后到时完成 | 每个通道状态、SOC/温度、异常曲线、可恢复协议 | 未明确放行的电芯不得进入二注排气 |
| OP-05 | stop被拒绝；默认接受后到时完成 | 补液量、真空过程、排气及封口状态、泄漏检查 | 未知或不完整密封状态不得进入正式测试 |
| OP-06 | stop释放锁，不生成报告；原输入仍可用（模拟） | 部分/完整结果、测量有效性、电芯状态和复测条件 | 部分报告不能伪装成完整测试或科学达标 |

当前模拟停止仅改变 job 为 stopped 并释放资源/输入锁；它不模拟真实样品受损、耗材损失或部分输出。不能把其“原输入仍可用”直接移植到真实设备。`JobStatus.FAILED`虽有枚举，但当前没有真实执行失败、超时回调或断连后状态恢复的完整路径。

## 6. 资源、耗时、成本及其来源

| 阶段 | 当前资源 / 容量 | 配置时长（min） | 配置成本（单位未定义） | 当前来源 | 待提供证据 |
|---|---|---:|---:|---|---|
| OP-01 | mixer-01 / 1 | 30 | 12 | Python常量；模拟配置 | 设备ID、容量单位、批量依赖、时长日志、计费范围/单位 |
| OP-02 | characterization-01 / 1 | 45 | 20 | 同上 | 各method时长、校准/清洗耗时、取样/耗材成本 |
| OP-03 | injection-seal-01 / 1 | 60 | 35 | 同上 | 单芯/批次时长、注液耗材、等待与封口时间 |
| OP-04 | formation-01 / 2 | 480 | 80 | 同上 | 容量2指job/批次/通道？协议时长、电耗/设备占用 |
| OP-05 | degas-01 / 1 | 50 | 30 | 同上 | 补液/排气/封口分段时长及材料消耗 |
| OP-06 | cell-test-01 / 2 | 240 | 55 | 同上 | 通道容量、测试协议时长、复测/中止计费 |

整条模拟链时长合计905 min、配置成本合计232。ETA是 `当前逻辑时钟 + 配置时长`，不是实际完成时间预测；成本在接受job时一次记账，停止不退款。当前 OperationResult 没有显式返回 currency、cost_source、duration_source；本表中的“模拟配置”是对代码来源的说明，尚非已落地的字段。

建议平台adapter明确：`cost_source ∈ {observed, configured, proxy, unknown}`、成本单位/币种、估算与结算区分、计费范围；`duration_source`、排队时间与执行时间、ETA时间基准、`observed_started_at`/`observed_completed_at`。没有证据的金额和时间填 unknown，不由模型补估后当作事实。

## 7. 接口模板：当前可用字段与待补映射

| 语义 | 当前字段 / 行为 | 平台对接待确认 |
|---|---|---|
| 启动信号 | `Action("start_operation", payload)` | 哪个API/消息/幂等键真正触发设备；accepted不等于物理started |
| 配方 | `parameters.recipe`；结构未细化 | `recipe_id` + `recipe_version` 是否由上游注册；与批次ID不能混用 |
| 前序实体 | `input_id` 为episode artifact ID | artifact到真实sample/batch/cell/vessel ID映射；批次拆分与数量 |
| 请求/任务身份 | `request_id` / `job_id` | 客户端请求ID、平台任务ID、设备运行ID之间映射 |
| 接受成功 | `success=true, status=accepted`；有job ID，产物列表为空 | 仅表示接受/预约；dispatch和物理started分别需证据 |
| 完成成功 | `status=completed, produced_artifact_ids=[...]` | 完成事件、真实产物ID、结果引用、质量有效性；物理完成与科学达标分开 |
| 时间 | `estimated_completion_min` | 当前为逻辑绝对时间min；真实接口需定义UTC时间戳或相对ETA，不能混用 |
| 成本 | `incremental_cost` / `total_cost` | 当前total为episode累计；需区分job总成本、episode总成本、估计与实收 |
| 失败 | `success=false, failure_code, failure_reason, retryable` | 区分接受前拒绝、运行失败、状态未知；增加样品处置和人工复核状态 |
| 状态查询 | `poll`读取环境状态；`advance_time`推进模拟 | 真实平台poll/事件回调；不能用advance_time证明真实完成 |

建议沿用异步模板：启动→返回job/ETA/成本估计→查询或事件通知→完成后返回产物ID及结果。不要要求刚启动时就提供“已完成产物”的证据。若业务需预分配批次ID，应明确其planned/running状态。

## 8. 平台确认待办与关闭条件

| ID | 待确认决策 / 交付物 | 建议负责角色 | 当前状态 | 关闭条件 |
|---|---|---|---|---|
| DEC-01 | 表征必选/可选及注液前置条件 | 工艺/SOP负责人 | 待确认 | 有来源版本的流程图、放行条件与代表协议 |
| DEC-02 | 配方/样品/批次/电芯/容器/报告身份及分样、消耗语义 | 平台+数据负责人 | 待确认 | 六阶段实体映射及至少一条真实lineage示例 |
| DEC-03 | 启动/停止/暂停/恢复与skill边界 | 平台+工艺负责人 | 待确认 | 每阶段可控边界、禁止条件和故障处置说明 |
| DEC-04 | 配方schema、参数单位、范围与协议注册表 | 工艺负责人 | 待确认 | 单位明确且版本化的字段字典；压力绝压/表压确认 |
| DEC-05 | 失败、停止、断连、部分完成后的样品处置 | 平台+工艺负责人 | 待确认 | 失败码、可重试条件、样品状态和恢复/隔离规则 |
| DEC-06 | 设备资源与实际并行容量 | 平台负责人 | 待确认 | 容量计量单位、资源表与竞争请求示例 |
| DEC-07 | 耗时、ETA和成本来源 | 平台+业务负责人 | 待确认 | 数据来源、单位、计费/退款与时间基准 |
| DEC-08 | 表征与测试结果schema及质量判据 | 数据+工艺负责人 | 待确认 | 示例结果、数据链接、缺失/异常值与放行规则 |
| DEC-09 | 平台API、状态事件、幂等与真实ID | 平台接口负责人 | 待确认 | API版本、脱敏请求响应、权限范围与事件序列 |

每项确认应记录：阶段/DEC ID、具体结论、负责人、SOP/API或日志链接、来源版本、生效日期、审核人、对应验收case、证据路径。状态从待确认变为已确认后，再更新运行契约并执行验收；本文件不自动修改当前模拟行为。
