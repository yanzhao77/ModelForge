"""Tree-based localization for legacy Qt widgets and dialogs.

New UI code should use explicit translation keys. This adapter makes existing
pages cleanly switchable while they are progressively migrated.
"""
from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QWidget,
)

_CURRENT = None


def set_current(translator) -> None:
    global _CURRENT
    _CURRENT = translator


def current():
    return _CURRENT


# (简体中文, English, 日本語). Include both previous English literals and the
# current Chinese UI so all three modes remain coherent through migration.
_TEXT = {
    "首页": ("首页", "Home", "ホーム"), "概览": ("概览", "Overview", "概要"),
    "对话": ("对话", "Chat", "チャット"), "模型": ("模型", "Models", "モデル"),
    "数据集": ("数据集", "Datasets", "データセット"), "训练": ("训练", "Training", "トレーニング"),
    "知识库": ("知识库", "Knowledge", "ナレッジ"), "智能体": ("智能体", "Agents", "エージェント"),
    "任务": ("任务", "Tasks", "タスク"), "运行时": ("运行时", "Runtime", "ランタイム"),
    "活动": ("活动", "Activity", "アクティビティ"), "设置": ("设置", "Settings", "設定"),
    "模型管理": ("模型管理", "Model Management", "モデル管理"), "管理远程模型": ("管理远程模型", "Manage Remote Models", "リモートモデルを管理"),
    "刷新": ("刷新", "Refresh", "更新"), "示例": ("示例", "Examples", "例"), "管理": ("管理", "Manage", "管理"),
    "对话内容将显示在这里。": ("对话内容将显示在这里。", "Your conversation will appear here.", "会話内容がここに表示されます。"),
    "向 ModelForge 发送消息…": ("向 ModelForge 发送消息…", "Message ModelForge…", "ModelForge にメッセージ…"),
    "发送": ("发送", "Send", "送信"), "使用模型": ("使用模型", "Use Model", "モデルを使用"),
    "使用远程服务": ("使用远程服务", "Use Provider", "プロバイダーを使用"), "使用知识库": ("使用知识库", "Use Knowledge", "ナレッジを使用"),
    "本地运行时": ("本地运行时", "Local Runtime", "ローカルランタイム"), "未选择模型": ("未选择模型", "No Model Selected", "モデル未選択"),
    "远程模型服务": ("远程模型服务", "Remote Model Providers", "リモートモデルサービス"),
    "OpenAI 兼容模型服务": ("OpenAI 兼容模型服务", "OpenAI-Compatible Provider", "OpenAI 互換プロバイダー"),
    "默认模型": ("默认模型", "Default Model", "既定モデル"), "API 密钥": ("API 密钥", "API Key", "API キー"),
    "保存": ("保存", "Save", "保存"), "验证连接": ("验证连接", "Verify Connection", "接続を検証"), "删除": ("删除", "Delete", "削除"), "新建": ("新建", "New", "新規"),
    "通用": ("通用", "General", "一般"), "外观": ("外观", "Appearance", "外観"), "语言": ("语言", "Language", "言語"),
    "服务连接": ("服务连接", "Service Connection", "サービス接続"), "关于": ("关于", "About", "について"),
    "浅色": ("浅色", "Light", "ライト"), "深色": ("深色", "Dark", "ダーク"), "跟随系统": ("跟随系统", "System", "システム"),
    "显示语言": ("显示语言", "Display Language", "表示言語"), "工作区": ("工作区", "Workspace", "ワークスペース"),
    "已连接": ("已连接", "Connected", "接続済み"), "需要登录": ("需要登录", "Login Required", "ログインが必要"),
    "起步示例": ("起步示例", "Starter Examples", "スターター例"), "复制模板": ("复制模板", "Copy Template", "テンプレートをコピー"),
    "作为起点使用": ("作为起点使用", "Use as Starting Point", "開始点として使う"),
    "新建智能体": ("新建智能体", "New Agent", "新しいエージェント"), "删除智能体": ("删除智能体", "Delete Agent", "エージェントを削除"),
    "运行智能体": ("运行智能体", "Run Agent", "エージェントを実行"), "取消运行": ("取消运行", "Cancel Run", "実行をキャンセル"),
    "Agent 工作台": ("Agent 工作台", "Agent Workbench", "エージェントワークベンチ"), "定义": ("定义", "Definitions", "定義"),
    "模板": ("模板", "Templates", "テンプレート"), "定义版本与权限审阅": ("定义版本与权限审阅", "Definition Versions & Permission Review", "定義バージョンと権限レビュー"),
    "将所选定义保存为模板": ("将所选定义保存为模板", "Save Selected Definition as Template", "選択した定義をテンプレートとして保存"),
    "前往智能体页面并显式运行": ("前往智能体页面并显式运行", "Open Agents Page for Explicit Run", "エージェント画面で明示的に実行"),
    "删除所选模板": ("删除所选模板", "Delete Selected Template", "選択したテンプレートを削除"), "刷新工作台": ("刷新工作台", "Refresh Workbench", "ワークベンチを更新"),
    "自动化": ("自动化", "Automation", "自動化"), "控制中心": ("控制中心", "Control Center", "コントロールセンター"),
    "新建计划草稿": ("新建计划草稿", "New Schedule Draft", "新しいスケジュール下書き"), "计划默认是草稿。只有点击“启用”后才会在设定时间创建 Agent Run。": ("计划默认是草稿。只有点击“启用”后才会在设定时间创建 Agent Run。", "Schedules start as drafts. Only selecting Enable can create an Agent Run at the configured time.", "スケジュールは下書きとして始まります。有効化を選択した場合のみ、設定時刻に Agent Run が作成されます。"),
    "选择一个计划查看详情。": ("选择一个计划查看详情。", "Select a schedule to view details.", "詳細を表示するスケジュールを選択してください。"), "启用": ("启用", "Enable", "有効化"), "暂停": ("暂停", "Pause", "一時停止"), "立即运行": ("立即运行", "Run Now", "今すぐ実行"), "查看下五次": ("查看下五次", "View Next Five", "次の5回を表示"), "查看执行历史": ("查看执行历史", "View Execution History", "実行履歴を表示"), "删除计划": ("删除计划", "Delete Schedule", "スケジュールを削除"),
    "控制中心": ("控制中心", "Control Center", "コントロールセンター"), "刷新控制中心": ("刷新控制中心", "Refresh Control Center", "コントロールセンターを更新"), "记忆": ("记忆", "Memory", "メモリ"), "产物": ("产物", "Artifacts", "成果物"), "知识集合": ("知识集合", "Knowledge Collections", "ナレッジコレクション"), "模型洞察": ("模型洞察", "Model Insights", "モデルインサイト"),
    "新建记忆": ("新建记忆", "New Memory", "新しいメモリ"), "编辑所选记忆": ("编辑所选记忆", "Edit Selected Memory", "選択したメモリを編集"), "删除所选记忆": ("删除所选记忆", "Delete Selected Memory", "選択したメモリを削除"), "查看所选产物": ("查看所选产物", "View Selected Artifact", "選択した成果物を表示"), "删除所选产物": ("删除所选产物", "Delete Selected Artifact", "選択した成果物を削除"), "新建集合": ("新建集合", "New Collection", "新しいコレクション"), "归类现有文档": ("归类现有文档", "Add Existing Document", "既存ドキュメントを追加"), "管理所选集合": ("管理所选集合", "Manage Selected Collection", "選択したコレクションを管理"), "新建配置档": ("新建配置档", "New Profile", "新しいプロファイル"), "预览所选配置档": ("预览所选配置档", "Preview Selected Profile", "選択したプロファイルをプレビュー"), "删除所选配置档": ("删除所选配置档", "Delete Selected Profile", "選択したプロファイルを削除"), "设置洞察预算": ("设置洞察预算", "Set Insight Budget", "インサイト予算を設定"), "查看预算摘要": ("查看预算摘要", "View Budget Summary", "予算サマリーを表示"),
    "扩展治理": ("扩展治理", "Extension Governance", "拡張機能ガバナンス"), "检查健康状态": ("检查健康状态", "Check Health", "ヘルスを確認"), "启动扩展": ("启动扩展", "Start Extension", "拡張機能を開始"), "停止扩展": ("停止扩展", "Stop Extension", "拡張機能を停止"), "挂载扩展": ("挂载扩展", "Mount Extension", "拡張機能をマウント"), "卸载挂载": ("卸载挂载", "Unmount Extension", "拡張機能をアンマウント"), "卸载扩展": ("卸载扩展", "Unload Extension", "拡張機能をアンロード"), "刷新已加载扩展": ("刷新已加载扩展", "Refresh Loaded Extensions", "読み込まれた拡張機能を更新"),
    "在这里审阅定义、模板、模型目标、工具权限和知识范围。查看、保存模板和版本回放均不会创建 Agent Run。": ("在这里审阅定义、模板、模型目标、工具权限和知识范围。查看、保存模板和版本回放均不会创建 Agent Run。", "Review definitions, templates, model targets, tool permissions, and knowledge scope here. Viewing, saving templates, and replaying versions never creates an Agent Run.", "ここでは定義、テンプレート、モデルターゲット、ツール権限、ナレッジ範囲を確認できます。表示、テンプレート保存、バージョン再生で Agent Run は作成されません。"),
    "选择定义、模板或版本查看模型目标、工具、策略和知识范围。": ("选择定义、模板或版本查看模型目标、工具、策略和知识范围。", "Select a definition, template, or version to inspect model targets, tools, policy, and knowledge scope.", "定義、テンプレート、またはバージョンを選択して、モデルターゲット、ツール、ポリシー、ナレッジ範囲を確認します。"),
    "管理记忆、运行产物、知识集合、插件配置与模型洞察。页面不会启动模型、运行 Agent 或安装扩展。": ("管理记忆、运行产物、知识集合、插件配置与模型洞察。页面不会启动模型、运行 Agent 或安装扩展。", "Manage memory, artifacts, knowledge collections, plugin profiles, and model insights. This page never starts models, runs Agents, or installs extensions.", "メモリ、成果物、ナレッジコレクション、プラグインプロファイル、モデルインサイトを管理します。このページはモデルの起動、Agent の実行、拡張機能のインストールを行いません。"),
    "页面只显示已加载扩展。健康检查和生命周期变更均需管理员显式点击；操作前会显示依赖、工具与影响范围。": ("页面只显示已加载扩展。健康检查和生命周期变更均需管理员显式点击；操作前会显示依赖、工具与影响范围。", "Only already-loaded extensions appear here. An administrator must explicitly select health and lifecycle actions; dependencies, tools, and impact are shown first.", "ここには読み込み済みの拡張機能のみが表示されます。ヘルス確認とライフサイクル操作は管理者が明示的に選択し、依存関係、ツール、影響範囲を先に表示します。"),
    "添加数据集": ("添加数据集", "Add Dataset", "データセットを追加"), "加载模板": ("加载模板", "Load Template", "テンプレートを読み込む"),
    "开始训练": ("开始训练", "Start Training", "トレーニングを開始"), "停止运行": ("停止运行", "Stop Run", "実行を停止"),
    "注册模型": ("注册模型", "Register Model", "モデルを登録"), "检索": ("检索", "Search", "検索"), "提问": ("提问", "Ask", "質問"),
    "启动运行时": ("启动运行时", "Start Runtime", "ランタイムを起動"), "停止运行时": ("停止运行时", "Stop Runtime", "ランタイムを停止"),
    "刷新状态": ("刷新状态", "Refresh Status", "状態を更新"), "批量重试": ("批量重试", "Batch Retry", "一括再試行"),
    "命令面板": ("命令面板", "Command Palette", "コマンドパレット"), "搜索命令…": ("搜索命令…", "Search Commands…", "コマンドを検索…"),
    "你想先完成什么工作？": ("你想先完成什么工作？", "What would you like to work on?", "まず何に取り組みますか？"),
    "向 ModelForge 提问…": ("向 ModelForge 提问…", "Ask ModelForge anything…", "ModelForge に質問…"),
    "开始对话": ("开始对话", "Start Chat", "チャットを開始"), "最近使用": ("最近使用", "Recent", "最近使用した項目"),
    "这里还没有内容": ("这里还没有内容", "Nothing Here Yet", "まだ何もありません"),
    "ModelForge · 本地工作区登录": ("ModelForge · 本地工作区登录", "ModelForge · Local Workspace Login", "ModelForge · ローカルワークスペースにログイン"),
    "登录": ("登录", "Sign In", "ログイン"), "创建账号": ("创建账号", "Create Account", "アカウントを作成"),
    "正在检查模型就绪状态…": ("正在检查模型就绪状态…", "Checking model readiness…", "モデルの準備状態を確認中…"),
    "将自动识别本地模型与已验证的远程模型服务。": ("将自动识别本地模型与已验证的远程模型服务。", "Local models and verified remote providers are detected automatically.", "ローカルモデルと検証済みリモートプロバイダーを自動検出します。"),
    "配置模型": ("配置模型", "Configure Models", "モデルを設定"), "修复配置": ("修复配置", "Fix Configuration", "設定を修復"),
    "重新检查": ("重新检查", "Check Again", "再確認"), "稍后处理": ("稍后处理", "Not Now", "後で行う"),
    "准备你的第一个模型": ("准备你的第一个模型", "Set Up Your First Model", "最初のモデルを設定"),
    "开始配置 ModelForge": ("开始配置 ModelForge", "Set Up ModelForge", "ModelForge を設定"),
    "使用已有本地模型": ("使用已有本地模型", "Use an Existing Local Model", "既存のローカルモデルを使用"),
    "模型已准备完成": ("模型已准备完成", "Models Are Ready", "モデルの準備が完了しました"),
    "服务预设": ("服务预设", "Provider Preset", "プロバイダープリセット"),
    "名称": ("名称", "Name", "名前"), "服务地址": ("服务地址", "Base URL", "ベース URL"),
    "协议": ("协议", "Protocol", "プロトコル"),
    "智谱 AI（GLM-4.5-Flash）": ("智谱 AI（GLM-4.5-Flash）", "Zhipu AI (GLM-4.5-Flash)", "Zhipu AI（GLM-4.5-Flash）"),
    "自定义 OpenAI 兼容服务": ("自定义 OpenAI 兼容服务", "Custom OpenAI-Compatible Provider", "カスタム OpenAI 互換プロバイダー"),
    "数据库": ("数据库", "Database", "データベース"),
    "运行只读迁移预检": ("运行只读迁移预检", "Run Read-Only Migration Preflight", "読み取り専用の移行事前確認を実行"),
    "查看并发/事件诊断": ("查看并发/事件诊断", "View Concurrency/Event Diagnostics", "並行性・イベント診断を表示"),
    "查看生命周期/保留诊断": ("查看生命周期/保留诊断", "View Lifecycle/Retention Diagnostics", "ライフサイクル・保持診断を表示"),
    "迁移预检": ("迁移预检", "Migration Preflight", "移行事前確認"),
    "查看操作审计": ("查看操作审计", "View Operation Audit", "操作監査を表示"),
    "操作审计": ("操作审计", "Operation Audit", "操作監査"),
    "审计": ("审计", "Audit", "監査"),
    "暂无脱敏操作审计记录。": ("暂无脱敏操作审计记录。", "No redacted operation audit records.", "匿名化された操作監査記録はありません。"),
    "并发/事件诊断": ("并发/事件诊断", "Concurrency/Event Diagnostics", "並行性・イベント診断"),
    "生命周期诊断": ("生命周期诊断", "Lifecycle Diagnostics", "ライフサイクル診断"),
    "只读生命周期/保留诊断": ("只读生命周期/保留诊断", "Read-Only Lifecycle/Retention Diagnostics", "読み取り専用のライフサイクル・保持診断"),
    "控制中心": ("控制中心", "Control Center", "コントロールセンター"),
    "自动化": ("自动化", "Automation", "自動化"),
    "刷新": ("刷新", "Refresh", "更新"),
    "新建计划草稿": ("新建计划草稿", "New Schedule Draft", "新しいスケジュール下書き"),
    "启用": ("启用", "Enable", "有効化"), "暂停": ("暂停", "Pause", "一時停止"),
    "立即运行": ("立即运行", "Run Now", "今すぐ実行"), "查看下五次": ("查看下五次", "View Next Five", "次の5回を表示"),
    "查看执行历史": ("查看执行历史", "View Execution History", "実行履歴を表示"), "删除计划": ("删除计划", "Delete Schedule", "スケジュールを削除"),
    "开始对话": ("开始对话", "Start Chat", "チャットを開始"), "查看运行时": ("查看运行时", "View Runtime", "ランタイムを表示"), "管理服务": ("管理服务", "Manage Provider", "プロバイダーを管理"),
    "正在检查模型": ("正在检查模型", "Checking Models", "モデルを確認中"), "在此统一管理本地模型和远程 OpenAI 兼容模型服务。": ("在此统一管理本地模型和远程 OpenAI 兼容模型服务。", "Manage local models and remote OpenAI-compatible providers in one place.", "ローカルモデルとリモート OpenAI 互換プロバイダーをここで一元管理します。"),
    "尚未添加模型": ("尚未添加模型", "No Models Added", "モデルが追加されていません"), "添加本地模型或配置远程服务后，即可开始对话。": ("添加本地模型或配置远程服务后，即可开始对话。", "Add a local model or configure a remote provider to start chatting.", "ローカルモデルを追加するかリモートプロバイダーを設定すると会話を開始できます。"),
    "知识工作区": ("知识工作区", "Knowledge Workspace", "ナレッジワークスペース"), "文档索引": ("文档索引", "Document Index", "ドキュメント索引"), "添加文档": ("添加文档", "Add Document", "ドキュメントを追加"), "查看分块": ("查看分块", "View Chunks", "チャンクを表示"), "删除文档": ("删除文档", "Delete Document", "ドキュメントを削除"),
    "模型：": ("模型：", "Model:", "モデル："), "默认模型": ("默认模型", "Default Model", "既定モデル"), "输入问题（回车先检索，再生成回答）...": ("输入问题（回车先检索，再生成回答）...", "Enter a question (Enter searches first, then generates an answer)...", "質問を入力してください（Enter で検索後に回答を生成します）..."),
    "推理服务": ("推理服务", "Inference Service", "推論サービス"), "模型生命周期、权限响应和运行时诊断均来自已连接服务。": ("模型生命周期、权限响应和运行时诊断均来自已连接服务。", "Model lifecycle, permission responses, and runtime diagnostics come from the connected service.", "モデルのライフサイクル、権限応答、ランタイム診断は接続済みサービスから取得されます。"), "运行时状态将在此显示。": ("运行时状态将在此显示。", "Runtime status will appear here.", "ランタイムの状態がここに表示されます。"),
    "运行记录": ("运行记录", "Run History", "実行履歴"), "暂无活动记录": ("暂无活动记录", "No Activity Yet", "アクティビティはまだありません"), "已连接的 ModelForge 服务发布任务事件后，将显示在这里。": ("已连接的 ModelForge 服务发布任务事件后，将显示在这里。", "Task events from the connected ModelForge service will appear here.", "接続済みの ModelForge サービスがタスクイベントを公開すると、ここに表示されます。"),
    "选择已加载扩展查看详情。": ("选择已加载扩展查看详情。", "Select a loaded extension to view details.", "読み込み済みの拡張機能を選択して詳細を確認します。"), "尚无已加载扩展。此页面不会自动发现、加载或安装扩展。": ("尚无已加载扩展。此页面不会自动发现、加载或安装扩展。", "No extensions are loaded. This page never discovers, loads, or installs extensions automatically.", "読み込み済みの拡張機能はありません。この画面で自動検出、読み込み、インストールは行われません。"),
}

# Make English source literals equivalent to their Chinese migration counterparts.
for _zh, _en, _ja in list(_TEXT.values()):
    _TEXT.setdefault(_en, (_zh, _en, _ja))
    _TEXT.setdefault(_ja, (_zh, _en, _ja))


def text(source: str, locale: str) -> str:
    value = _TEXT.get(source)
    if not value:
        return source
    return value[{"zh_CN": 0, "en_US": 1, "ja_JP": 2}.get(locale, 0)]


def _source(obj, attr: str, value: str) -> str:
    key = f"mf_i18n_{attr}"
    saved = obj.property(key)
    if not saved:
        obj.setProperty(key, value)
        return value
    return str(saved)


def localize_tree(root: QWidget, translator=None) -> None:
    translator = translator or _CURRENT
    if translator is None:
        return
    locale = translator.locale
    for widget in [root, *root.findChildren(QWidget)]:
        if isinstance(widget, (QLabel, QPushButton)):
            widget.setText(text(_source(widget, "text", widget.text()), locale))
        elif isinstance(widget, QLineEdit):
            widget.setPlaceholderText(text(_source(widget, "placeholder", widget.placeholderText()), locale))
        elif isinstance(widget, QTextEdit):
            widget.setPlaceholderText(text(_source(widget, "placeholder", widget.placeholderText()), locale))
        elif isinstance(widget, QGroupBox):
            widget.setTitle(text(_source(widget, "title", widget.title()), locale))
        elif isinstance(widget, QComboBox):
            sources = widget.property("mf_i18n_items")
            if not sources:
                sources = [widget.itemText(index) for index in range(widget.count())]
                widget.setProperty("mf_i18n_items", sources)
            for index, source in enumerate(sources):
                if index < widget.count():
                    widget.setItemText(index, text(str(source), locale))
        elif isinstance(widget, QTabWidget):
            sources = widget.property("mf_i18n_tabs")
            if not sources:
                sources = [widget.tabText(index) for index in range(widget.count())]
                widget.setProperty("mf_i18n_tabs", sources)
            for index, source in enumerate(sources):
                if index < widget.count():
                    widget.setTabText(index, text(str(source), locale))
    for action in root.findChildren(QAction):
        action.setText(text(_source(action, "text", action.text()), locale))
    if root.windowTitle():
        root.setWindowTitle(text(_source(root, "window_title", root.windowTitle()), locale))
