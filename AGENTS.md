# 百度平台项目开发约束

开发前必须优先读取：

1. `E:\百度平台共享\docs\百度平台架构原则.md`
2. `E:\百度平台共享\knowledge\assistant_query_index.md`
3. 常用接口读取 `E:\百度平台共享\knowledge\assistant_core_reference.md`
4. 具体字段读取索引指向的 `E:\百度平台共享\knowledge\documents\`

必须遵守：

- 本项目使用独立的百度应用、OAuth 回调、搜索管家授权和 Token，不得读取或复制百度电商的应用配置、Token 或数据库。
- Token 只能从本项目 PostgreSQL 的 `platform_core` 授权中心读取；本地与阿里云始终只允许一个活跃授权中心。
- 使用管家 Token 操作子账户时必须明确目标账户。
- 禁止复制电商业务代码、Token 或数据库表作为搜索项目底层。
- 禁止新增 SQLite 运行链路。
- API 调用必须经过公共限频、重试、审计和幂等层。
- 搜索项目不得连接或写入电商数据库；搜索业务数据只写入 `search_marketing`，平台授权数据只写入 `platform_core`。
- 前端只读取后台统一口径数据，不自行计算核心指标。
- 接口文档优先使用共享知识层，原 Word 文档只作兜底。
