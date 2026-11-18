# TubeAiFolw 优云智算 GPU 图片生成 Provider 初步开发计划

日期：2026-11-18  
状态：初步方案，尚未实现；供后续开发、技术验证与验收使用。  
首期范围：只在云 GPU 上执行图片生成；不迁移 TTS、字幕对齐、LLM、视频生成或渲染。

## 1. 目标与范围决策

增加优云智算 GPU Provider，使没有高性能本地显卡的 Windows 用户能够使用远程图片生成。项目、Scene、风格、素材、任务记录和工程交付仍保存在本地。保留现有 Seedream Pro / Flash，用户显式选择出图路径，失败时不得静默切换到另一条付费路径。

本次用户需求允许在租赁云 GPU 上运行图片模型，是对旧规则“仅 Seedream 云 API”的扩展；仍禁止在用户本地电脑运行图片或视频生成模型。旧的本地 FLUX / SDXL / ComfyUI 安装、启动、GPU 探测和图片 QC 管线不得恢复。远程实例中的 ComfyUI 仅作为云端执行实现，业务层通过 Provider 访问。

建议首期采用用户自己的优云智算账号、已有专用实例和凭证，算力由用户直接支付。年度授权覆盖软件及更新，不包含无限算力。现有开发账号只用于验证，不在发行客户端中分发开发者公私钥或共享生产实例。统一代付、多租户共享 GPU、积分售卖和 License Server 不属于本期。

首期以“一个连接配置绑定一个已有专用实例、一个固定出图模板、单实例串行执行”为边界。不自动购买、创建、删除、重装、扩容实例，不管理任意社区工作流，不接入云视频。仅预留未来能力字段，不提前实现通用计算平台。

## 2. 已核实信息与未核实信息

### 2.1 控制台只读检查

2026-11-18 在用户已登录的 Chrome 实例列表中观察到：

| 项目 | 观察结果 |
| --- | --- |
| 实例名称 / 类型 | host / 容器 |
| 状态 | 关机 |
| 地域展示名 | 华北二A |
| GPU | RTX50系 × 1 |
| CPU / 内存 | 16 核 / 96 GB |
| 镜像 | ComfyUI基础镜像纯净版0.43.0-5090 |
| 计费 | 按量；关机页面显示实例费为 0 |

实例 ID 不写入通用开发文档，后续通过用户选择绑定。不记录 SSH、实例密码、公私钥或带访问令牌的 URL。规格详情展开受浏览器自动化几何信息不可用影响，未进一步核实。

不能从镜像名称推断真实 GPU 型号、显存、已安装模型、可用节点或性能；关机页面的 0 元不能当作运行价格。本次没有开机、修改实例、创建凭证或生成图片。

待验证：Region / Zone / ProjectId 的实际 API 值、是否抢占式、GPU 与显存、磁盘容量和持久性、启动与模型加载耗时、实际运行费率、模型文件与许可证、模板、软件端口、认证、HTTPS、下载带宽。不得用猜测值写入默认配置。

### 2.2 平台接口与出图接口是两层服务

官方文档提供 GPU 实例管理 OpenAPI；其公私钥与平台模型 API Key 是不同凭证。它解决实例管理，不等于镜像自动拥有图片生成任务 API。[接口操作范例](https://www.compshare.cn/docs/gpus/operationexample)

计划使用的实例管理能力：

| 能力 | 官方 Action / 文档 | 首期策略 |
| --- | --- | --- |
| 查询实例 | [DescribeCompShareInstance](https://www.compshare.cn/docs/gpus/instance/describecompshareinstance) | 读取白名单字段，绑定已有实例 |
| 启动实例 | [StartCompShareInstance](https://www.compshare.cn/docs/gpus/instance/startcompshareinstance) | 用户开启自动管理后使用；超时先查状态 |
| 关闭实例 | [StopCompShareInstance](https://www.compshare.cn/docs/gpus/instance/stopcompshareinstance) | 仅关闭本软件取得管理权的专用实例 |
| 查询软件地址 | [GetSoftwareURL](https://www.compshare.cn/docs/gpus/instance/getsoftwareurl) | 发现地址后还需独立健康与认证检查 |
| 定时关机 | [UpdateCompShareStopScheduler](https://www.compshare.cn/docs/gpus/instance/updatecompsharestopscheduler) | 验证成功后才允许自动开机模式 |

软件地址可变，不能永久缓存为可靠连接。查询实例的原始响应可能含密码等敏感字段，禁止整体写日志、返回前端或写入任务快照。[实例查询字段](https://www.compshare.cn/docs/gpus/instance/describecompshareinstance)

定时关机文档要求至少提前五分钟，且不支持抢占式实例；自动管理模式应优先验证非抢占式专用实例。计费还可能包含存储、带宽、镜像等项目，停止实例不代表全部费用归零。[定时关机限制](https://www.compshare.cn/docs/gpus/instance/updatecompsharestopscheduler)、[计费概览](https://www.compshare.cn/docs/operation/charge/bill)

## 3. 推荐架构

```text
Vue：连接设置 / 项目出图 / 风格测试 / 状态和恢复
                     |
FastAPI Local Engine + SQLite + TaskRun / Checkpoint
                     |
Image Provider Registry
  ├─ Seedream Pro / Flash（现有）
  └─ image.compshare_gpu（新增，名称暂定）
       ├─ ComputeProvider：实例发现、状态、启停、关机期限
       └─ RemoteImageClient：提交、查询、取消、下载
                     |
优云智算已有专用 GPU 实例
  认证与 HTTPS 入口 → TubeAiFolw Image Worker → 固定 ComfyUI 模板
                     |
本地校验与原子落盘 → GeneratedImageVariant → StyleAsset / SceneAssignment
```

建议增加薄层 Image Worker，负责持久任务 ID、幂等、任务隔离、下载与取消；ComfyUI 作为内部执行器。不要把任意 ComfyUI 图 JSON、节点端口和模型路径暴露为普通用户配置。

Worker 的接口是本项目拟开发的契约，不是优云智算已提供的官方功能。技术验证阶段可检查当前镜像接口，但正式接入不能仅依赖浏览器 UI 自动点击出图。若平台访问入口无法用于程序认证或安全传输，应先解决部署入口，不能关闭证书校验或公开裸服务作为绕过方式。

ComputeProvider 与 ImageProvider 分离：前者只管理租赁资源，后者只表达图片能力。云 GPU 不占用本地 GPU Resource Class；沿用 API / NETWORK 调度，并通过实例级持久租约限制远程并发。只为将来保留能力声明，暂不注册 TTS 等未实现能力。

## 4. 正常工作流与资源管理

1. 用户选择优云智算图片 Provider，配置凭证，列出并绑定专用实例。
2. “检查连接”只执行查询，不自动开机、不生成图片。
3. 本地先完成风格编译、锁定检查、有效缓存检查和 StyleAsset 保守复用。全部命中时不启动云 GPU。
4. 为剩余候选建立持久任务和实例租约，冻结 Provider、连接版本、模型与模板参数。
5. 首版先支持用户手动开机。自动模式须用户明确启用；启动前核对实例、费用提示和已配置的运行时限。
6. 自动模式设置平台侧关机期限并读取确认；若必须先启动才可设置，应将其作为不可分割的启动事务，失败时停止派发并尝试关机，显示异常。
7. 等待实例 Running，再检查 Worker ready、模型、模板与输出规格；实例运行不等于模型可用。
8. 按候选逐个提交，持久保存远程 ID，轮询状态，下载图片，检查解码、尺寸、格式、文件大小和哈希后原子落盘。
9. 复用现有图片注册、StyleAsset 归档、SceneAssignment、锁定保护和交付产物失效规则。
10. 本地确认产物可用后才确认远程结果可清理；租约释放后，按策略进入空闲关机。

建议默认并发为 1，风格测试与正式项目、批次共享实例级限额。租约键至少包含连接和实例标识，防止两个本地 Worker 重复派发。首期不支持同一实例由多台电脑共同自动管理；检测到冲突时阻止自动启停。

仅本软件自动启动并取得租约的实例允许自动停止。对于原先已运行或手动管理的实例，只提示状态。停止前再次核对远程队列、当前任务和本地下载状态。取消单个 Scene 不得中断其他项目的任务。

本地空闲计时不是可靠费用保险：电脑关机后不会执行。应采用平台定时关机硬期限，Worker 可补充空闲保护。到达期限可能中断长任务，应在截止前停止接收新任务；自动延长期限必须属于用户已选择的策略且有最大上限，不能无限续期。

## 5. 图片 Worker 拟定契约

接口命名可在实施时调整，语义必须保留：

| 方法 | 拟定路径 | 要求 |
| --- | --- | --- |
| GET | /v1/health | 存活状态，不泄露系统敏感信息 |
| GET | /v1/capabilities | 就绪状态、协议、模型、模板版本、尺寸和并发限制 |
| POST | /v1/image-jobs | 接受幂等键和参数摘要，返回稳定任务 ID |
| GET | /v1/image-jobs/by-request/{request_id} | 提交响应丢失时找回任务 |
| GET | /v1/image-jobs/{job_id} | 排队、运行、成功、失败或取消状态 |
| POST | /v1/image-jobs/{job_id}/cancel | 任务级取消；重复请求安全 |
| GET | /v1/image-jobs/{job_id}/artifacts/{artifact_id} | 认证下载，禁止任意路径读取 |

请求包含 request_id、input_hash、模板版本、model_revision、Prompt、Negative Prompt、seed、width、height。首期一个远程任务对应一个候选；候选数量在本地展开。相同幂等键和相同输入返回原任务，不同输入返回冲突。

模型、模板、节点版本固定并记录摘要，不允许从用户请求执行任意脚本、下载任意模型或改变输出目录。模型选择先验证画质、中文理解、横屏输出、显存和商业使用条件，再冻结首个模板；本计划不预定未经实测的模型或 2848×1600 原生出图能力。

提交前先落盘幂等记录，后调用执行器。Worker 与执行器之间的接受状态也要可核对；若无法证明是否已提交，记录 unknown，不能声称实现了端到端 exactly-once。Worker 重启后若执行器任务或结果丢失，不自动重跑；有明确失败记录才允许人工重试。

取消必须验证当前 ComfyUI 版本的行为。若其取消能力只能全局中断，应由 Worker 保证串行且只中断当前目标；否则仅停止后续派发，显示取消待确认，不能误报已停止或已停止计费。

## 6. 状态、恢复与数据模型

实例状态与任务状态分开保存。任务建议状态为：queued、waiting_instance、submitting、submitted、running、downloading、completed、failed、cancel_requested、cancelled、unknown。网络断开属于连接状态，不能直接等同于生成失败。

建议增加版本化迁移，表名为设计建议：

| 模型 | 核心字段 |
| --- | --- |
| ComputeConnection | Provider、Region、Zone、ProjectId、实例 ID、credential_id、endpoint 引用、配置版本、启停策略 |
| RemoteGenerationTask | 本地任务 ID、TaskRun / StyleTestRun / Scene / Variant 引用、request_id、remote_job_id、input_hash、状态、尝试序号、时间、错误码 |
| RemoteArtifact | 所属任务、远程 artifact_id、本地路径、哈希、尺寸、下载与校验状态 |
| ComputeLease | 实例、owner、到期时间、heartbeat、自动启动标记、关机期限 |

不得预先锁定 Schema v27：实施时读取当前最新迁移再追加。表结构采用独立字段保存恢复所需标识，原始响应不作为权威记录。继续以现有全局 SQLite 为权威，不在本期迁移到 project.db。

关键恢复规则：

- 提交超时或发送后断线：先按 request_id 找回；找不到且无法证明未接收则 unknown，不自动重复生成。
- 轮询失败：退避查询原任务，不能创建新任务。
- 下载中断：重新下载同一产物，不重新生成；远程结果不存在时给出明确提示。
- 图片损坏：先重新获取原产物，仍无效则失败，重新出图需显式操作。
- 应用重启：恢复远程 ID 和下载状态；不重新提交已接受的任务。
- Worker 重启 / 实例关机 / 回收：核对任务账本、执行器状态和结果文件；证据不足进入 unknown。
- Scene 在生成期间被锁定或改动：结果可保留，但输入签名不匹配时不得覆盖当前分配。
- 用户重新生成：创建新的请求版本和幂等键，保留旧成功结果及审计。

建议错误码：COMPUTE_AUTH_FAILED、COMPUTE_INSTANCE_UNAVAILABLE、COMPUTE_START_TIMEOUT、COMPUTE_STOP_UNCONFIRMED、REMOTE_WORKER_NOT_READY、REMOTE_JOB_UNKNOWN、REMOTE_MODEL_UNAVAILABLE、REMOTE_ARTIFACT_INVALID。UI 同时提供处理建议，禁止直接展示包含凭证的异常原文。

## 7. 当前代码的改造位置

以下为本次定向读取确认的接入点；路径均相对仓库根目录。

| 文件 / 模块 | 计划改造 |
| --- | --- |
| backend/app/providers/image.py | 保留 ImageProviderRuntime 外部入口，增加能力与远程任务契约；避免迫使 Seedream 改成同一远程协议 |
| backend/app/providers/registry.py | 注册新云端图片 Provider，声明 local=false 和配置要求 |
| backend/app/services/image_generation/image_generation_service.py | 移除仅 Seedream 白名单和专用 Key 前置条件；由 Provider 校验；参数、模型签名和尺寸来自实际能力 |
| 同上 | 当前 model_ref、model_revision、workflow_version 及素材 Provider 判断包含 Seedream 假设，需要逐项泛化 |
| backend/app/integrations/image_generation/ | 新增云 GPU 图片适配器；现有 seedream.py 保留 |
| backend/app/services/visual_styles/style_test_queue.py | 当前直接调用 SeedreamClient；改为共享 Provider 执行路径与远程恢复语义 |
| backend/app/services/visual_styles/style_service.py | 风格测试冻结 Provider / 模型 / 模板 / 连接版本，不随全局设置中途切换 |
| backend/app/services/visual_styles/style_asset_service.py | 归档真实远程模型与模板元数据；保持复用风险约束 |
| backend/app/config.py、models/settings.py、api/settings.py | 扩展 Provider 设置、连接和策略；检查其他 Pydantic 白名单 |
| backend/app/services/settings/system_settings_service.py | 扩展 SECRET_FIELDS，正确脱敏与迁移 |
| backend/app/infrastructure/credential_store.py | 复用 DPAPI，按 credential_id 引用公私钥及 Worker Token |
| backend/app/workflows/、TaskRun 与迁移模块 | 关联远程状态、租约、恢复和取消；不占用本地 GPU 配额 |
| frontend/src/pages/settings/SystemSettings.vue、frontend/src/api/settings.ts | GPU 连接管理、只读检查、状态、启动费用提示和启停策略 |

实现前还需定向核对项目设置、风格测试序列化、数据库迁移和 TaskRun 恢复测试，避免仅改全局设置入口。

缓存输入签名需包含 Provider、模型版本、模板摘要、输出尺寸、seed、风格修订与 Prompt。切换模型或模板不得错误命中 Seedream 旧缓存。已下载图片继续作为本地 MediaFile 使用，PRPROJ 不得依赖云实例 URL。

## 8. 用户界面、凭证与运营边界

设置页增加“云 GPU 图片生成”连接区：凭证录入、实例选择、检查连接、状态、手动/自动管理模式、最大运行时间、空闲策略。项目页保持出图操作简单，只展示等待启动、加载模型、排队、生成、下载、完成和需要处理的错误。

风格中心与项目均可选择 Provider；一次运行固定配置快照。未选择新 Provider 的旧项目保持 Seedream 行为。未知任务应显示“结果待确认”和查询/处理入口，不以自动重试掩盖不确定性。

公私钥与 Worker Token 仅在 Local Engine 解密，前端仅显示是否已配置；API 不返回原密钥。凭证不进入 project.json、任务快照、Prompt 清单、日志或诊断报告。访问 URL 可能含令牌，也按 Secret 处理。Worker 不持有优云智算控制平面私钥。

仅上传生成所需 Prompt 与参数；首期不上传完整脚本、音频和本地素材库。Worker 按连接身份隔离任务与结果。下载限制来源、重定向、大小和路径，不能接受远端返回的任意本地文件路径。

远程结果保留期限需实测磁盘后确定，建议本地确认后清理、未确认结果保留可配置期限；磁盘不足时拒绝新任务并提示，不能无提示删除尚未下载的结果。关机和平台回收不作为数据备份策略。

只记录耗时、数量、实例运行窗口和费用来源，不开发统一图片费用统计或承诺精确预算。运行时限不是绝对金额上限。年费、设备激活与离线宽限在后续独立 License 方案中实现。

## 9. 分阶段开发与交付门槛

| 阶段 | 工作 | 完成标准 |
| --- | --- | --- |
| P0 技术验证 | 核实实例、模型、模板、端口、认证、持久磁盘和费用；经用户安排再进行开机实测 | 一张横屏图能经程序接口生成、下载；记录冷启动、单图耗时、显存、质量与模型许可；确定模板版本 |
| P1 控制平面 | 凭证、只读实例发现、连接持久化、状态与错误映射 | 检查连接不启动实例；无 Secret 泄漏；界面能选择绑定实例 |
| P2 远程执行 | Worker、幂等账本、固定模板、任务查询、取消、下载 | 断线和重启后找到同一任务；重复提交不重复执行；损坏产物不能登记成功 |
| P3 业务接入 | 泛化 Seedream 假设，接入项目、Scene 重生成、风格测试与资产归档 | 两条出图路径共存；锁定、复用和输入签名正确；工程只链接本地图片 |
| P4 自动管理与恢复 | 实例租约、平台关机期限、空闲保护、跨项目排队 | 电脑退出仍有平台期限；不关闭外部管理实例；关机失败明确显示 |
| P5 发布验收 | 安装/升级说明、模板版本、迁移回滚、真实长项目验证 | 下述矩阵通过；更新 AGENTS.md 已实现状态和用户文档 |

P0 是正式模型和模板选型的门槛；不应在未验证镜像能力前承诺固定上线日期。可先交付手动开机试用版本，再交付 P4 自动管理。发布时关闭功能开关可回到 Seedream，新表保留审计；已有生成文件不删除。

## 10. 验证与验收矩阵

- 控制平面模拟：鉴权失败、分页、实例丢失、启动超时、查询限流、关机未确认、定时关机不支持。只读检查零启停调用。
- 幂等与恢复：提交响应丢失、应用崩溃、Worker 重启、执行器提交边界崩溃、实例停止、下载失败。结果不确定时零自动重发。
- 并发：项目与风格测试竞争同一实例、批次多个项目、租约过期与旧 Worker 回来；同一候选最多一个有效接受记录。
- 取消与锁定：取消不影响其他任务；生成期间锁定、改 Prompt、切风格后不覆盖当前结果。
- 产物：损坏 PNG、错误尺寸、截断文件、错误哈希、路径穿越、下载 URL 变化；只有校验成功才登记 completed。
- 现有回归：Seedream Pro / Flash、风格测试、StyleAsset 复用、SceneAssignment 和项目导出测试；Frontend 设置交互测试与构建。
- 真实验证：先单 Scene，再 1～4 张风格测试，再至少一个代表性 20～60 分钟项目。记录实际 Scene / 图片数、成功率、排队和下载耗时、人工干预次数、运行及存储费用。
- 费用与退出：缓存全命中不启动实例；自动管理模式电脑关闭后平台仍按期限关机；原先运行实例不被自动停止。
- 交付：图片下载后关闭云实例，仍可完成本地素材预览、工程导出与交付 QC。Premiere / 目标剪映实际打开验收仍是独立人工步骤。

本次只编写计划，没有运行生成测试、迁移或应用测试，也不宣称已通过上述验收。

## 11. 实施前需要收敛的事项

1. 开发验证使用当前实例；正式首版按用户自有账号、专用实例执行。若改为开发者统一托管，必须另补租户隔离、服务端密钥、配额与成本方案。
2. 选择并验证首个模型、模型版本、模板和支持尺寸；不把镜像名当作模型契约。
3. 确认当前镜像是否可安全部署 Worker、持久化账本及通过 HTTPS 程序访问；不能满足则更换受控镜像方案。
4. 核实华北二A 的实际 API 标识、数据盘与回收政策，配置结果备份和清理期限。
5. 以真实吞吐与使用成本决定是否优于现有 Seedream；不能仅凭 GPU 时租判断单图成本。

这些事项不妨碍先实现接口和模拟测试，但决定 P0 能否通过。后续业务扩展在本期稳定后逐项立项，不因预留 Provider 接口而提前迁移。
