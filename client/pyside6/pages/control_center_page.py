"""Privacy-first control center for memory, artifacts, collections, extensions and insights."""
from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from components.api_worker import AsyncApiMixin


class ControlCenterPage(QWidget, AsyncApiMixin):
    """A read-first workspace; all persistence and export actions remain explicit."""

    def __init__(self, api, parent=None):
        super().__init__(parent)
        self._init_async_api()
        self.api = api
        layout = QVBoxLayout(self)
        title = QLabel("控制中心")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        hint = QLabel("管理记忆、运行产物、知识集合、插件配置与模型洞察。页面不会启动模型、运行 Agent 或安装扩展。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.tabs = QTabWidget()
        self.memory_list = QListWidget()
        self.artifact_list = QListWidget()
        self.collection_list = QListWidget()
        self.profile_list = QListWidget()
        self.insight_list = QListWidget()
        self.database_list = QListWidget()
        self.audit_list = QListWidget()
        self._memories: list[dict] = []
        self._artifacts: list[dict] = []
        self._collections: list[dict] = []
        self._profiles: list[dict] = []
        self._insight_preferences: dict = {}
        self._budget_status: dict = {}
        self.tabs.addTab(self._tab(self.memory_list, "新建记忆", self._create_memory, "编辑所选记忆", self._edit_selected_memory, "删除所选记忆", self._delete_selected_memory), "记忆")
        self.tabs.addTab(self._tab(self.artifact_list, "查看所选产物", self._view_selected_artifact, "删除所选产物", self._delete_selected_artifact), "产物")
        self.tabs.addTab(self._tab(self.collection_list, "新建集合", self._create_collection, "归类现有文档", self._bind_document, "管理所选集合", self._manage_collection), "知识集合")
        self.tabs.addTab(self._tab(self.profile_list, "新建配置档", self._create_profile, "预览所选配置档", self._preview_selected_profile, "删除所选配置档", self._delete_selected_profile), "插件/MCP")
        self.tabs.addTab(self._tab(self.insight_list, "设置洞察预算", self._configure_insight_budget, "查看预算摘要", self._show_budget_summary), "模型洞察")
        self.tabs.addTab(self._tab(self.database_list, "运行只读迁移预检", self._run_migration_preflight, "查看并发/事件诊断", self._run_runtime_diagnostics, "查看生命周期/保留诊断", self._run_lifecycle_diagnostics), "数据库")
        self.tabs.addTab(self._tab(self.audit_list, "查看操作审计", self._run_operation_audits), "审计")
        layout.addWidget(self.tabs, 1)
        self.refresh_button = QPushButton("刷新控制中心")
        self.refresh_button.clicked.connect(self.refresh)
        layout.addWidget(self.refresh_button)
        self.refresh()

    def _tab(self, target, action_text, callback, secondary_text=None, secondary_callback=None, tertiary_text=None, tertiary_callback=None):
        page = QWidget()
        layout = QVBoxLayout(page)
        if callback:
            button = QPushButton(action_text)
            button.clicked.connect(callback)
            layout.addWidget(button)
        if secondary_callback:
            button = QPushButton(secondary_text)
            button.clicked.connect(secondary_callback)
            layout.addWidget(button)
        if tertiary_callback:
            button = QPushButton(tertiary_text)
            button.clicked.connect(tertiary_callback)
            layout.addWidget(button)
        layout.addWidget(target, 1)
        return page

    def refresh(self):
        self.refresh_button.setEnabled(False)
        worker = self._run_api(lambda: {
            "memories": self.api.list_memories(),
            "artifacts": self.api.list_artifacts(),
            "collections": self.api.list_knowledge_collections(),
            "profiles": self.api.list_plugin_profiles(),
            "insight_data": self.api.model_insights(),
        }, self._loaded, lambda error: self.insight_list.addItem(f"无法加载控制中心：{error}"), request_key="control-refresh")
        worker.finished.connect(lambda: self.refresh_button.setEnabled(True))
        self._worker = worker

    def _loaded(self, data):
        self._memories = data.get("memories", [])
        self._artifacts = data.get("artifacts", [])
        self._collections = data.get("collections", [])
        self._profiles = data.get("profiles", [])
        self._fill(self.memory_list, [f"{item.get('key')} · {item.get('type')} · 重要性 {item.get('importance')}" for item in self._memories], "暂无记忆。")
        self._fill(self.artifact_list, [f"{item.get('title')} · {item.get('source_kind')} · 已脱敏={item.get('redacted')}" for item in self._artifacts], "暂无运行产物。")
        self._fill(self.collection_list, [f"{item.get('name')} · {item.get('document_count', 0)} 个文档" for item in self._collections], "暂无知识集合。")
        self._fill(self.profile_list, [item.get("name", "未命名配置档") for item in self._profiles], "暂无插件/MCP 配置档。")
        insight_data = data.get("insight_data") or {}
        self._insight_preferences = insight_data.get("preferences") or {}
        self._budget_status = insight_data.get("budget_status") or {}
        self._fill(self.insight_list, [f"{item.get('model_ref')} · 成功 {item.get('success_count')}/{item.get('request_count')} · 失败 {item.get('error_count', 0)}（429={item.get('error_429_count', 0)} / 超时={item.get('timeout_count', 0)}）· 平均延迟 {item.get('average_latency_ms') or '—'} ms · 估算成本 {item.get('cost_estimate', 0)}" for item in insight_data.get("insights", [])], "尚无脱敏聚合调用指标。")

    @staticmethod
    def _fill(target, lines, empty):
        target.clear()
        target.addItems(lines or [empty])

    def _create_memory(self):
        key, ok = QInputDialog.getText(self, "新建记忆", "键")
        if not ok or not key.strip():
            return
        value, ok = QInputDialog.getMultiLineText(self, "新建记忆", "内容")
        if ok and value.strip():
            self._call(lambda: self.api.create_memory("context", key.strip(), value.strip()))

    def _create_collection(self):
        name, ok = QInputDialog.getText(self, "新建知识集合", "名称")
        if ok and name.strip():
            self._call(lambda: self.api.create_knowledge_collection(name.strip()))

    def _bind_document(self):
        row = self.collection_list.currentRow()
        if row < 0 or row >= len(self._collections):
            return
        document_id, ok = QInputDialog.getInt(self, "归类现有文档", "知识文档 ID", minimum=1)
        if ok:
            self._call(lambda: self.api.add_document_to_knowledge_collection(self._collections[row]["id"], document_id))

    def _manage_collection(self):
        row = self.collection_list.currentRow()
        if row < 0 or row >= len(self._collections):
            return
        collection = self._collections[row]
        worker = self._run_api(lambda: self.api.get_knowledge_collection(collection["id"]), lambda data: self._show_collection_dialog(collection, data), lambda message: QMessageBox.warning(self, "知识集合", str(message)), request_key="collection-detail")
        self._worker = worker

    def _show_collection_dialog(self, collection, data):
        documents = data.get("documents") or []
        summary = "\n".join(f"#{item.get('id')} · {item.get('filename')}" for item in documents) or "暂无文档。"
        box = QMessageBox(self)
        box.setWindowTitle("管理知识集合")
        box.setText(f"{collection.get('name')}\n\n{summary}\n\n选择操作：")
        remove_button = box.addButton("移除文档", QMessageBox.ButtonRole.ActionRole)
        delete_button = box.addButton("删除集合", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is remove_button:
            document_id, ok = QInputDialog.getInt(self, "移除集合文档", "知识文档 ID", minimum=1)
            if ok and QMessageBox.question(self, "确认移除", "仅移除此集合关联，文档本体和其他集合不会删除。是否继续？") == QMessageBox.StandardButton.Yes:
                self._call(lambda: self.api.remove_document_from_knowledge_collection(collection["id"], document_id))
        elif box.clickedButton() is delete_button:
            if QMessageBox.question(self, "确认删除集合", f"删除“{collection.get('name')}”只会移除集合关联，不会删除文档本体。是否继续？") == QMessageBox.StandardButton.Yes:
                self._call(lambda: self.api.delete_knowledge_collection(collection["id"]))

    def _create_profile(self):
        name, ok = QInputDialog.getText(self, "新建插件/MCP 配置档", "名称")
        if ok and name.strip():
            self._call(lambda: self.api.create_plugin_profile(name.strip()))

    def _delete_selected_memory(self):
        row = self.memory_list.currentRow()
        if row < 0 or row >= len(self._memories):
            return
        memory = self._memories[row]
        if QMessageBox.question(self, "删除记忆", f"删除记忆“{memory.get('key')}”？") == QMessageBox.StandardButton.Yes:
            self._call(lambda: self.api.delete_memory(memory["id"]))

    def _edit_selected_memory(self):
        row = self.memory_list.currentRow()
        if row < 0 or row >= len(self._memories):
            return
        memory = self._memories[row]
        value, ok = QInputDialog.getMultiLineText(self, "编辑记忆", "内容", memory.get("value") or "")
        if not ok or not value.strip():
            return
        importance, ok = QInputDialog.getDouble(self, "编辑记忆重要性", "重要性（0 到 1）", float(memory.get("importance") or 0), 0, 1, 3)
        if ok:
            self._call(lambda: self.api.update_memory(memory["id"], value=value.strip(), importance=importance))

    def _view_selected_artifact(self):
        row = self.artifact_list.currentRow()
        if row < 0 or row >= len(self._artifacts):
            return
        artifact = self._artifacts[row]
        worker = self._run_api(lambda: self.api.get_artifact(artifact["id"]), lambda data: QMessageBox.information(self, "已脱敏运行产物", f"{data.get('title')}\n\n来源：{data.get('source_kind')} · {data.get('source_id')}\n已脱敏：{data.get('redacted')}\n\n{data.get('text') or json.dumps(data.get('content') or {}, ensure_ascii=False, indent=2)}"), lambda message: QMessageBox.warning(self, "运行产物", str(message)), request_key="artifact-detail")
        self._worker = worker

    def _preview_selected_profile(self):
        row = self.profile_list.currentRow()
        if row < 0 or row >= len(self._profiles):
            return
        profile = self._profiles[row]
        worker = self._run_api(lambda: self.api.preview_plugin_profile(profile["id"]), lambda data: QMessageBox.information(self, "配置档预览", f"{data.get('name')}\n\n插件：{data.get('declared_plugin_count')}\nMCP 服务：{data.get('declared_mcp_server_count')}\n工具白名单：{data.get('declared_tool_count')}\n\n{data.get('notice')}"), lambda message: QMessageBox.warning(self, "配置档预览", str(message)), request_key="profile-preview")
        self._worker = worker

    def _delete_selected_profile(self):
        row = self.profile_list.currentRow()
        if row < 0 or row >= len(self._profiles):
            return
        profile = self._profiles[row]
        if QMessageBox.question(self, "删除配置档", f"删除配置档“{profile.get('name')}”？该操作不会停止、卸载或变更任何扩展。") == QMessageBox.StandardButton.Yes:
            self._call(lambda: self.api.delete_plugin_profile(profile["id"]))

    def _delete_selected_artifact(self):
        row = self.artifact_list.currentRow()
        if row < 0 or row >= len(self._artifacts):
            return
        artifact = self._artifacts[row]
        if QMessageBox.question(self, "删除产物", f"删除产物“{artifact.get('title')}”？原始运行不会被删除。") == QMessageBox.StandardButton.Yes:
            self._call(lambda: self.api.delete_artifact(artifact["id"]))

    def _configure_insight_budget(self):
        current_daily = self._insight_preferences.get("daily_budget")
        current_weekly = self._insight_preferences.get("weekly_budget")
        daily, ok = QInputDialog.getDouble(self, "设置日预算提醒", "日预算阈值（0 表示关闭提醒）", float(current_daily or 0), 0, 1_000_000, 4)
        if not ok:
            return
        weekly, ok = QInputDialog.getDouble(self, "设置周预算提醒", "周预算阈值（0 表示关闭提醒）", float(current_weekly or 0), 0, 1_000_000, 4)
        if not ok:
            return
        payload = {"daily_budget": daily or None, "weekly_budget": weekly or None, "prices": self._insight_preferences.get("prices") or {}}
        self._call(lambda: self.api.update_model_insight_preferences(payload))

    def _show_budget_summary(self):
        status = self._budget_status
        if not status:
            QMessageBox.information(self, "预算摘要", "尚无指标数据。预算设置只用于提醒，不会阻止或修改模型调用。")
            return
        QMessageBox.information(
            self,
            "预算摘要",
            f"近 24 小时估算成本：{status.get('daily_cost_estimate', 0)} / 预算 {status.get('daily_budget') or '未设置'}\n"
            f"近 7 天估算成本：{status.get('weekly_cost_estimate', 0)} / 预算 {status.get('weekly_budget') or '未设置'}\n"
            f"日预算提醒：{'已达到' if status.get('daily_exceeded') else '未达到'}\n"
            f"周预算提醒：{'已达到' if status.get('weekly_exceeded') else '未达到'}\n\n"
            f"{status.get('notice', '只显示聚合信息。')}",
        )

    def _run_migration_preflight(self):
        """Request diagnostics only; the action never starts a migration."""
        worker = self._run_api(self.api.migration_preflight, self._show_migration_preflight, lambda message: QMessageBox.warning(self, "迁移预检", str(message)), request_key="migration-preflight")
        self._worker = worker

    def _show_migration_preflight(self, data):
        ledger = data.get("ledger") or {}
        tables = data.get("tables") or []
        table_summary = "\n".join(
            f"{item.get('table')}: 缺列={','.join(item.get('missing_columns') or []) or '无'}；"
            f"缺索引={','.join(item.get('missing_indexes') or []) or '无'}"
            for item in tables
        ) or "未发现需要检查的迁移表。"
        warnings = "\n".join(f"- {item}" for item in data.get("warnings") or []) or "无。"
        QMessageBox.information(
            self,
            "只读迁移预检",
            f"状态：{data.get('status')}\n"
            f"只读：{data.get('read_only')}；迁移执行：{data.get('migration_execution')}\n"
            f"已记录版本：{', '.join(ledger.get('applied_versions') or []) or '无'}\n"
            f"缺失版本：{', '.join(ledger.get('missing_versions') or []) or '无'}\n\n"
            f"表/索引摘要：\n{table_summary}\n\n警告：\n{warnings}\n\n"
            "该操作未调用 init_db()，未创建表、未修改 schema、未执行迁移。",
        )

    def _run_runtime_diagnostics(self):
        """Read aggregated state only; no lease, event, or schedule is changed."""
        worker = self._run_api(self.api.runtime_diagnostics, self._show_runtime_diagnostics, lambda message: QMessageBox.warning(self, "并发/事件诊断", str(message)), request_key="runtime-diagnostics")
        self._worker = worker

    def _show_runtime_diagnostics(self, data):
        runs = data.get("runs") or {}
        claims = data.get("schedule_claims") or {}
        events = data.get("events") or {}
        outbox = data.get("task_outbox") or {}
        QMessageBox.information(
            self,
            "只读并发/事件诊断",
            f"运行中：{runs.get('active_count', 0)}；有效执行 lease：{runs.get('leased_count', 0)}；"
            f"过期执行 lease：{runs.get('expired_lease_count', 0)}\n"
            f"有效计划 claim：{claims.get('active_claim_count', 0)}；过期 claim：{claims.get('expired_claim_count', 0)}\n"
            f"事件总数：{events.get('total_count', 0)}；缺失 event key：{events.get('missing_key_count', 0)}；"
            f"重复 key 组：{events.get('duplicate_key_group_count', 0)}\n"
            f"待派送 outbox：{outbox.get('pending_count', 0)}；有效 lease：{outbox.get('active_lease_count', 0)}；"
            f"重试到期：{outbox.get('retry_due_count', 0)}\n\n"
            f"{data.get('notice', '只显示聚合诊断。')}",
        )

    def _run_lifecycle_diagnostics(self):
        worker = self._run_api(self.api.lifecycle_diagnostics, self._show_lifecycle_diagnostics, lambda message: QMessageBox.warning(self, "生命周期诊断", str(message)), request_key="lifecycle-diagnostics")
        self._worker = worker

    def _show_lifecycle_diagnostics(self, data):
        runtime = data.get("runtime") or {}
        scheduler = runtime.get("scheduler") or {}
        schedules = data.get("schedules") or {}
        retention = data.get("retention") or {}
        QMessageBox.information(
            self,
            "只读生命周期/保留诊断",
            f"追踪运行任务：{runtime.get('tracked_task_count', 0)}；运行中：{runtime.get('running_run_count', 0)}；"
            f"等待审批：{runtime.get('awaiting_approval_count', 0)}\n"
            f"调度器已启动：{scheduler.get('started', False)}；注册计划：{scheduler.get('registered_job_count', 0)}；"
            f"失败回调：{scheduler.get('failed_callback_count', 0)}\n"
            f"待处理触发：{schedules.get('pending_trigger_count', 0)}；近 24 小时计划：{schedules.get('next_24h_count', 0)}\n"
            f"保留候选执行记录：{retention.get('execution_candidates', 0)}（策略 {retention.get('policy_days', 30)} 天）\n\n"
            f"{data.get('notice', '只显示状态。')}",
        )

    def _run_operation_audits(self):
        """Read only audit headers; metadata and request bodies are never displayed."""
        worker = self._run_api(
            self.api.operation_audits,
            self._show_operation_audits,
            lambda message: QMessageBox.warning(self, "操作审计", str(message)),
            request_key="operation-audits",
        )
        self._worker = worker

    def _show_operation_audits(self, data):
        rows = data.get("items") or []
        lines = [
            f"{item.get('created_at') or '—'} · #{item.get('user_id')} · {item.get('action')} · "
            f"{item.get('object_type')}:{item.get('object_id')} · {item.get('correlation_id')}"
            for item in rows
        ]
        self._fill(self.audit_list, lines, "暂无脱敏操作审计记录。")

    def _call(self, action):
        worker = self._run_api(action, lambda _result: self.refresh(), lambda message: QMessageBox.warning(self, "控制中心", str(message)), request_key="control-mutation")
        self._worker = worker

    def closeEvent(self, event):
        self.shutdown_async_api()
        super().closeEvent(event)
