# V1.7 — Package / Marketplace Foundation

目标：建立可导入、导出、版本化、带依赖与许可证元数据的包体系（先本地包，不做在线商城）。

## 包结构

```json
{
  "schema_version": 1,
  "manifest": {
    "package_id": "workflow:<id>", "kind": "workflow|agent|model|tool",
    "name": "...", "version": "1.2.0", "license": "MIT",
    "requires": [{"kind": "model", "ref": "3"}, {"kind": "tool", "ref": "filesystem.read"}],
    "description": "...", "exported_at": "...", "...kind specific...": "..."
  },
  "payload": { "definition": {...} | "artifact": {...} | "schema": {...} }
}
```

## 实现

| 组件 | 文件 | 说明 |
|---|---|---|
| 包服务 | `services/package_service.py` | 四类导出、导入、版本列表、删除、依赖校验 |
| 存储 | `platform_packages` 表 | 每次导出/导入都留档（可按 kind/version 查询） |
| API | `api/packages.py` | `GET /packages`、`POST /packages/export`、`POST /packages/import`、`GET/DELETE /packages/{id}` |
| 依赖校验 | `_missing_dependencies()` | 导入时报告缺失的 model/agent/workflow/runtime 依赖及原因 |

## 诚实边界

* **模型包不含权重、不含绝对路径**：payload 只给 format/size，导入返回
  `action_required=download`；
* **工具包不含实现**：只登记 schema 与权限，导入返回
  `action_required=install-plugin`，不会执行代码；
* Agent 包跨机器导入时，若 `model_id` 在本机不存在会被丢弃并保留模型名，
  由用户重新绑定，而不是指向一个不存在的记录；
* 导入默认 `conflict=rename`（生成 `-imported` 后缀），不会覆盖本地定义。

## 验收

| 验收项 | 证据 |
|---|---|
| Model / Agent / Tool / Workflow Package | `tests/test_packages_v17.py`（5 用例） |
| Import / Export | `test_workflow_package_round_trip` |
| Version | `manifest.version` + `GET /packages/{id}` 返回 `versions` |
| Dependency | `test_import_reports_missing_dependencies` |
| License metadata | `manifest.license`（默认 `unspecified`，导出可指定） |
