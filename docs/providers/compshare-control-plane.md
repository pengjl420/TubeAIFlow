# TubeAiFolw 优云智算控制平面基础接口

2026-11-18：实现计划中的 P1 后端基础部分；手动开关机已接入；Worker 与图片业务接入尚未实现。前端通过“资源与系统 → 云 GPU 平台”（`/cloud-gpu`）提供基础接口测试页面。连接检查不会开机或提交生成任务。没有使用真实账号或产生租赁调用费用。

应用启动时自动追加 Schema v27；旧数据库沿用现有迁移前备份机制。凭证通过 Windows DPAPI 独立保存，SQLite 仅保存随机 credential_id；列表、绑定和检查响应均不包含凭证或平台原始响应。管理模式固定为 manual。

接口均位于 `/api/compute/connections`，可通过本地 FastAPI `/docs` 调用：

| 方法 | 路径后缀 | 参数 / 行为 |
| --- | --- | --- |
| POST | 空 | name、public_key、private_key；可选 region、zone、project_id。创建连接，不查询或开机 |
| GET | 空 | 列出已保存的连接 |
| GET | /{id}/instances | offset 默认 0，limit 默认 20、最大 100；返回 total 与当前页 instances |
| PUT | /{id}/instance | instance_id；向平台查询确认存在后绑定，配置版本递增 |
| POST | /{id}/check | 查询已绑定实例；返回实例状态、manual 和 worker_ready=false |

地域、可用区和项目 ID 无猜测默认值。首次可留空查询全部实例，再绑定已存在的专用实例。API 公私钥来自控制台账户中心，不能使用模型 API Key 替代。公私钥均按 Secret 保存。

网络错误、HTTP 鉴权失败、限流、超时、平台拒绝和无效响应映射为固定错误码；不返回平台 Message，不自动重试，不跟随重定向。实例结果只包含 ID、名称、状态、地域、可用区、GPU 类型/数量和是否抢占式。

协议依据：[实例查询](https://www.compshare.cn/docs/gpus/instance/describecompshareinstance)、[平台接口范例](https://www.compshare.cn/docs/gpus/operationexample)、[UCloud 签名规则](https://www.ucloud-global.com/en/docs/api/summary/signature)。模拟测试不能替代真实平台认证和地域参数验证。

## 页面测试步骤

1. 打开“系统设置 → 云 GPU 平台”（`/settings/cloud-gpu`），填写连接名称、AccessKey ID（公钥）和 AccessKey Secret（私钥）并保存；地域、可用区和项目 ID 可留空。凭证沿用 DPAPI 加密保存，保存后清空输入且不回显；已有连接继续可用，新凭证另存新连接。
2. 进入“云 GPU 平台”（`/cloud-gpu`），自动读取全部已保存连接并拉取各连接全部分页实例，每 5 秒刷新，慢请求不重叠且不阻塞其他连接。当前仅适配优云智算，可配置多个账号/查询范围连接。
3. 实例行直接点击开机或关机，无需绑定；确认框显示目标及费用/任务中断说明。
4. 实例行点击“操作日志”打开右侧抽屉，显示该资源本次页面会话的全部启停结果，不截断条数；刷新浏览器或离开页面会清空。

查询失败时保留旧数据并标记过期、禁用该连接启停；恢复成功查询后可继续操作。实例运行不代表远程出图服务就绪。旧绑定和检查接口仅保留兼容。

## 手动开关机（2026-11-18）

- `POST /api/compute/connections/{id}/start` 和 `/stop`，请求体为 `{"instance_id":"目标实例 ID"}`。
- 调用前在所属连接范围重新查询目标实例，校验目标 ID 与状态；开机仅允许 Stopped，关机仅允许 Running 且非抢占式实例。Region / Zone 取实时实例信息，缺少时使用连接配置，仍缺失则拒绝。
- 平台分别调用 StartCompShareInstance / StopCompShareInstance；成功响应只表示请求已接受，不表示启停完成。
- 实例行根据状态控制按钮可用性，操作提交后通过自动刷新确认状态；日志不包含凭证或原始平台响应。
- 不自动重试、不自动开关机。超时、5xx、异常响应等返回 COMPUTE_OPERATION_UNKNOWN，需先检查平台状态；平台明确拒绝返回 COMPUTE_OPERATION_REJECTED。不返回平台原始 Message。
- 模拟测试覆盖签名、参数、状态限制与不确定结果；未进行真实平台启停验收。更新后需重启后端服务以加载新路由。

依据：[启动实例](https://www.compshare.cn/docs/gpus/instance/startcompshareinstance)、[关闭实例](https://www.compshare.cn/docs/gpus/instance/stopcompshareinstance)。
