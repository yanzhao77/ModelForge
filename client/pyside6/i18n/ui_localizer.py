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
    "刷新控制中心": ("刷新控制中心", "Refresh Control Center", "コントロールセンターを更新"), "记忆": ("记忆", "Memory", "メモリ"), "产物": ("产物", "Artifacts", "成果物"), "知识集合": ("知识集合", "Knowledge Collections", "ナレッジコレクション"), "模型洞察": ("模型洞察", "Model Insights", "モデルインサイト"),
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
    "预览": ("预览", "Preview", "プレビュー"), "训练预检": ("训练预检", "Training Preflight", "学習プリフライト"), "删除所选": ("删除所选", "Delete Selected", "選択項目を削除"),
    "正在同步数据集": ("正在同步数据集", "Syncing datasets", "データセットを同期中"), "数据集不可用": ("数据集不可用", "Datasets unavailable", "データセットを利用できません"),
    "任务更新中": ("任务更新中", "Tasks Updating", "タスク更新中"), "运行时已同步": ("运行时已同步", "Runtime Synchronized", "ランタイム同期済み"),
    "训练配置": ("训练配置", "Training Configuration", "学習設定"), "运行详情": ("运行详情", "Run Detail", "実行詳細"),
    "已选择 {name}": ("已选择 {name}", "{name} selected", "{name} を選択中"),
    "协议": ("协议", "Protocol", "プロトコル"),
    "远程 · 已验证": ("远程 · 已验证", "Remote · Verified", "リモート・検証済み"), "远程 · 需要验证": ("远程 · 需要验证", "Remote · Verification Needed", "リモート・要検証"), "远程 · 需要密钥": ("远程 · 需要密钥", "Remote · API Key Needed", "リモート・要 API キー"),
    "凭据状态：已配置": ("凭据状态：已配置", "Credential: Configured", "認証情報：設定済み"), "凭据状态：未配置": ("凭据状态：未配置", "Credential: Not Configured", "認証情報：未設定"),
    "连接状态：已验证": ("连接状态：已验证", "Connection: Verified", "接続状態：検証済み"), "连接状态：未验证": ("连接状态：未验证", "Connection: Not Verified", "接続状態：未検証"), "连接状态：验证失败（{code}）": ("连接状态：验证失败（{code}）", "Connection: Verification Failed ({code})", "接続状態：検証失敗（{code}）"),
    "服务端点：{endpoint}": ("服务端点：{endpoint}", "Service Endpoint: {endpoint}", "サービスエンドポイント：{endpoint}"),
    "验证模型服务": ("验证模型服务", "Verify Model Provider", "モデルプロバイダーを検証"), "验证将访问此服务并请求模型列表，是否继续？": ("验证将访问此服务并请求模型列表，是否继续？", "Verification will contact this provider and request its model list. Continue?", "検証ではこのプロバイダーに接続し、モデル一覧を取得します。続行しますか？"),
    "新建模型服务配置。点击验证连接前不会发起网络请求。": ("新建模型服务配置。点击验证连接前不会发起网络请求。", "Create a model provider configuration. No network request is sent until Verify Connection is explicitly selected.", "モデルプロバイダー設定を作成します。［接続を検証］を明示的に選択するまでネットワーク要求は送信されません。"),
    "正在加载模型服务…": ("正在加载模型服务…", "Loading model providers…", "モデルプロバイダーを読み込み中…"), "选择已有模型服务，或新建一个配置。": ("选择已有模型服务，或新建一个配置。", "Select an existing model provider or create a configuration.", "既存のモデルプロバイダーを選択するか、設定を作成してください。"),
    "正在验证连接并获取模型列表…": ("正在验证连接并获取模型列表…", "Verifying the connection and retrieving the model list…", "接続を検証し、モデル一覧を取得中…"), "连接验证成功，发现 {count} 个模型。": ("连接验证成功，发现 {count} 个模型。", "Connection verified. Found {count} models.", "接続を検証しました。{count} 個のモデルが見つかりました。"),
    "远程模型服务请求未完成（{code}）。关联标识：{correlation}": ("远程模型服务请求未完成（{code}）。关联标识：{correlation}", "Remote model provider request did not complete ({code}). Correlation ID: {correlation}", "リモートモデルプロバイダーの要求は完了しませんでした（{code}）。相関 ID：{correlation}"),
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
    "事件总线：写入失败 {write_failures}；队列溢出 {queue_overflows}；队列 {queue_depth}/{queue_capacity}；订阅者 {subscriber_count}；写入器活跃 {writer_active}": ("事件总线：写入失败 {write_failures}；队列溢出 {queue_overflows}；队列 {queue_depth}/{queue_capacity}；订阅者 {subscriber_count}；写入器活跃 {writer_active}", "Event Bus: write failures {write_failures}; queue overflows {queue_overflows}; queue {queue_depth}/{queue_capacity}; subscribers {subscriber_count}; writer active {writer_active}", "イベントバス：書き込み失敗 {write_failures}；キューあふれ {queue_overflows}；キュー {queue_depth}/{queue_capacity}；購読者 {subscriber_count}；ライター稼働中 {writer_active}"),
    "后台任务：追踪 {tracked}；失败 {failed}；无循环拒绝 {rejected}；最近类型 {last_type}": ("后台任务：追踪 {tracked}；失败 {failed}；无循环拒绝 {rejected}；最近类型 {last_type}", "Background Tasks: tracked {tracked}; failures {failed}; no-loop rejections {rejected}; latest type {last_type}", "バックグラウンドタスク：追跡 {tracked}；失敗 {failed}；ループなし拒否 {rejected}；最新型 {last_type}"),
    "并发/事件诊断": ("并发/事件诊断", "Concurrency/Event Diagnostics", "並行性・イベント診断"),
    "生命周期诊断": ("生命周期诊断", "Lifecycle Diagnostics", "ライフサイクル診断"),
    "只读生命周期/保留诊断": ("只读生命周期/保留诊断", "Read-Only Lifecycle/Retention Diagnostics", "読み取り専用のライフサイクル・保持診断"),
    "查看运行时": ("查看运行时", "View Runtime", "ランタイムを表示"), "管理服务": ("管理服务", "Manage Provider", "プロバイダーを管理"),
    "正在检查模型": ("正在检查模型", "Checking Models", "モデルを確認中"), "在此统一管理本地模型和远程 OpenAI 兼容模型服务。": ("在此统一管理本地模型和远程 OpenAI 兼容模型服务。", "Manage local models and remote OpenAI-compatible providers in one place.", "ローカルモデルとリモート OpenAI 互換プロバイダーをここで一元管理します。"),
    "尚未添加模型": ("尚未添加模型", "No Models Added", "モデルが追加されていません"), "添加本地模型或配置远程服务后，即可开始对话。": ("添加本地模型或配置远程服务后，即可开始对话。", "Add a local model or configure a remote provider to start chatting.", "ローカルモデルを追加するかリモートプロバイダーを設定すると会話を開始できます。"),
    "知识工作区": ("知识工作区", "Knowledge Workspace", "ナレッジワークスペース"), "文档索引": ("文档索引", "Document Index", "ドキュメント索引"), "添加文档": ("添加文档", "Add Document", "ドキュメントを追加"), "查看分块": ("查看分块", "View Chunks", "チャンクを表示"), "删除文档": ("删除文档", "Delete Document", "ドキュメントを削除"),
    "模型：": ("模型：", "Model:", "モデル："), "输入问题（回车先检索，再生成回答）...": ("输入问题（回车先检索，再生成回答）...", "Enter a question (Enter searches first, then generates an answer)...", "質問を入力してください（Enter で検索後に回答を生成します）..."),
    "推理服务": ("推理服务", "Inference Service", "推論サービス"), "模型生命周期、权限响应和运行时诊断均来自已连接服务。": ("模型生命周期、权限响应和运行时诊断均来自已连接服务。", "Model lifecycle, permission responses, and runtime diagnostics come from the connected service.", "モデルのライフサイクル、権限応答、ランタイム診断は接続済みサービスから取得されます。"), "运行时状态将在此显示。": ("运行时状态将在此显示。", "Runtime status will appear here.", "ランタイムの状態がここに表示されます。"),
    "运行记录": ("运行记录", "Run History", "実行履歴"), "暂无活动记录": ("暂无活动记录", "No Activity Yet", "アクティビティはまだありません"), "已连接的 ModelForge 服务发布任务事件后，将显示在这里。": ("已连接的 ModelForge 服务发布任务事件后，将显示在这里。", "Task events from the connected ModelForge service will appear here.", "接続済みの ModelForge サービスがタスクイベントを公開すると、ここに表示されます。"),
    "选择已加载扩展查看详情。": ("选择已加载扩展查看详情。", "Select a loaded extension to view details.", "読み込み済みの拡張機能を選択して詳細を確認します。"), "尚无已加载扩展。此页面不会自动发现、加载或安装扩展。": ("尚无已加载扩展。此页面不会自动发现、加载或安装扩展。", "No extensions are loaded. This page never discovers, loads, or installs extensions automatically.", "読み込み済みの拡張機能はありません。この画面で自動検出、読み込み、インストールは行われません。"),
    "请求未完成（{code}）。": ("请求未完成（{code}）。", "The request did not complete ({code}).", "要求は完了しませんでした（{code}）。"),
    "请求未完成（{code}）。关联标识：{correlation}": ("请求未完成（{code}）。关联标识：{correlation}", "The request did not complete ({code}). Correlation ID: {correlation}", "要求は完了しませんでした（{code}）。相関 ID：{correlation}"),
    "执行意图预览（只读）": ("执行意图预览（只读）", "Execution Intent Preview (Read-Only)", "実行意図プレビュー（読み取り専用）"),
    "预览动作：{action}｜对象：{object_type}｜风险：{risk_tier}｜目标：{target_count}": ("预览动作：{action}｜对象：{object_type}｜风险：{risk_tier}｜目标：{target_count}", "Preview action: {action} | Object: {object_type} | Risk: {risk_tier} | Targets: {target_count}", "プレビュー操作：{action}｜対象：{object_type}｜リスク：{risk_tier}｜対象数：{target_count}"),
    "版本绑定状态：{state}": ("版本绑定状态：{state}", "Version binding: {state}", "バージョンバインド：{state}"),
    "完整": ("完整", "Complete", "完全"), "未完整": ("未完整", "Incomplete", "不完全"),
    "预览已阻断执行，确认不会启动任何操作。": ("预览已阻断执行，确认不会启动任何操作。", "Execution is blocked for this preview; confirmation will not start any action.", "このプレビューでは実行がブロックされています。確認しても操作は開始されません。"),
    "已启用": ("已启用", "Enabled", "有効"), "草稿/暂停": ("草稿/暂停", "Draft/Paused", "下書き/一時停止"),
    "一次": ("一次", "Once", "1 回"), "间隔": ("间隔", "Interval", "間隔"), "每日": ("每日", "Daily", "毎日"), "每周": ("每周", "Weekly", "毎週"), "自定义": ("自定义", "Custom", "カスタム"),
    "无法加载计划：{error}": ("无法加载计划：{error}", "Schedules could not be loaded: {error}", "スケジュールを読み込めませんでした：{error}"),
    "暂无计划。先创建草稿，再显式启用。": ("暂无计划。先创建草稿，再显式启用。", "No schedules. Create a draft, then explicitly enable it.", "スケジュールはありません。下書きを作成してから明示的に有効化してください。"),
    "确认{action}": ("确认{action}", "Confirm {action}", "{action} を確認"), "确定{action}“{name}”吗？": ("确定{action}“{name}”吗？", "{action} “{name}”?", "「{name}」を{action}しますか？"),
    "确认立即运行": ("确认立即运行", "Confirm Run Now", "今すぐ実行を確認"), "这会创建一个新的 Agent Run。是否继续？": ("这会创建一个新的 Agent Run。是否继续？", "This creates a new Agent Run. Continue?", "新しい Agent Run が作成されます。続行しますか？"),
    "计划已{action}。": ("计划已{action}。", "Schedule {action}.", "スケジュールを{action}しました。"), "已创建新的 Agent Run。": ("已创建新的 Agent Run。", "A new Agent Run was created.", "新しい Agent Run を作成しました。"),
    "计划已删除。": ("计划已删除。", "Schedule deleted.", "スケジュールを削除しました。"),
    "计划预览": ("计划预览", "Schedule Preview", "スケジュールプレビュー"), "时区：{timezone}": ("时区：{timezone}", "Time zone: {timezone}", "タイムゾーン：{timezone}"), "暂无后续执行。": ("暂无后续执行。", "No upcoming executions.", "次回以降の実行はありません。"),
    "计划执行历史": ("计划执行历史", "Schedule Execution History", "スケジュール実行履歴"), "暂无执行历史。读取历史不会创建 Agent Run。": ("暂无执行历史。读取历史不会创建 Agent Run。", "No execution history. Reading history does not create an Agent Run.", "実行履歴はありません。履歴の読み取りで Agent Run は作成されません。"),
    "确认删除": ("确认删除", "Confirm Deletion", "削除を確認"), "删除计划不会删除历史执行记录。是否继续？": ("删除计划不会删除历史执行记录。是否继续？", "Deleting the schedule does not delete execution history. Continue?", "スケジュールを削除しても実行履歴は削除されません。続行しますか？"),
    "确认重试": ("确认重试", "Confirm Retry", "再試行の確認"), "确定重试“{title}”？": ("确定重试“{title}”？", "Retry “{title}”?", "「{title}」を再試行しますか？"),
    "确认批量重试": ("确认批量重试", "Confirm Batch Retry", "一括再試行の確認"), "将为所选的 {count} 个失败任务创建受审计的重试任务，是否继续？": ("将为所选的 {count} 个失败任务创建受审计的重试任务，是否继续？", "Create audited retry tasks for {count} selected failures?", "選択した {count} 件の失敗タスクについて、監査対象の再試行タスクを作成しますか？"),
    "批量重试结果": ("批量重试结果", "Batch Retry Result", "一括再試行の結果"), "已创建 {count} 个重试任务。": ("已创建 {count} 个重试任务。", "Created {count} retry task(s).", "{count} 件の再試行タスクを作成しました。"), "未创建：": ("未创建：", "Not created:", "作成されませんでした："), "任务 {task_id} 未创建（{code}）。": ("任务 {task_id} 未创建（{code}）。", "Task {task_id} was not created ({code}).", "タスク {task_id} は作成されませんでした（{code}）。"),
    "确认取消": ("确认取消", "Confirm Cancellation", "キャンセルの確認"), "确定请求取消“{title}”？": ("确定请求取消“{title}”？", "Request cancellation of “{title}”?", "「{title}」のキャンセルを要求しますか？"),
    "任务未成功完成（{code}）。请查看脱敏日志或在确认后重试。": ("任务未成功完成（{code}）。请查看脱敏日志或在确认后重试。", "The task did not complete successfully ({code}). Review redacted logs or retry after confirmation.", "タスクは正常に完了しませんでした（{code}）。匿名化されたログを確認するか、確認後に再試行してください。"),
    "日志加载失败": ("日志加载失败", "Log Loading Failed", "ログの読み込みに失敗しました"), "导出失败": ("导出失败", "Export Failed", "エクスポートに失敗しました"), "无法写入所选文件。请检查文件路径和权限后重试。": ("无法写入所选文件。请检查文件路径和权限后重试。", "The selected file could not be written. Check its path and permissions, then retry.", "選択したファイルに書き込めませんでした。パスと権限を確認して再試行してください。"),
    "提示": ("提示", "Notice", "お知らせ"), "请先在数据集页上传并选择一个数据集": ("请先在数据集页上传并选择一个数据集", "Upload and select a dataset on the Datasets page first.", "先に［データセット］画面でデータセットをアップロードして選択してください。"),
    "配置错误": ("配置错误", "Configuration Error", "設定エラー"), "训练配置无效。请检查轮次、学习率和批量大小。": ("训练配置无效。请检查轮次、学习率和批量大小。", "The training configuration is invalid. Check epochs, learning rate, and batch size.", "トレーニング設定が無効です。エポック数、学習率、バッチサイズを確認してください。"),
    "确认启动训练": ("确认启动训练", "Confirm Training Start", "トレーニング開始の確認"), "训练将读取所选数据集并启动后台训练进程，是否继续？": ("训练将读取所选数据集并启动后台训练进程，是否继续？", "Training will read the selected dataset and start a background training process. Continue?", "トレーニングでは選択したデータセットを読み込み、バックグラウンドのトレーニングプロセスを開始します。続行しますか？"),
    "启动失败": ("启动失败", "Start Failed", "開始に失敗しました"), "训练任务已提交。任务标识：{task_id}": ("训练任务已提交。任务标识：{task_id}", "Training task submitted. Task ID: {task_id}", "トレーニングタスクを送信しました。タスク ID：{task_id}"),
    "训练完成": ("训练完成", "Training Complete", "トレーニング完了"), "可以点击“注册到模型列表”": ("可以点击“注册到模型列表”", "You can select “Register Model” to add the result to the model list.", "［モデルを登録］を選択して、結果をモデル一覧に追加できます。"),
    "确认停止训练": ("确认停止训练", "Confirm Training Stop", "トレーニング停止の確認"), "确定请求停止当前训练任务？": ("确定请求停止当前训练任务？", "Request that the current training task stop?", "現在のトレーニングタスクの停止を要求しますか？"), "停止失败": ("停止失败", "Stop Failed", "停止に失敗しました"), "已请求停止": ("已请求停止", "Stop Requested", "停止を要求しました"), "已向训练进程发送停止请求。": ("已向训练进程发送停止请求。", "A stop request was sent to the training process.", "トレーニングプロセスに停止要求を送信しました。"),
    "确认注册模型": ("确认注册模型", "Confirm Model Registration", "モデル登録の確認"), "确定将当前训练产物注册到本地模型列表？": ("确定将当前训练产物注册到本地模型列表？", "Register the current training artifact in the local model list?", "現在のトレーニング成果物をローカルモデル一覧に登録しますか？"), "注册失败": ("注册失败", "Registration Failed", "登録に失敗しました"), "已注册": ("已注册", "Registered", "登録済み"), "模型已注册：{name}": ("模型已注册：{name}", "Model registered: {name}", "モデルを登録しました：{name}"),
    "训练状态：{status}｜轮次 {current_epoch}/{total_epochs}｜损失：{loss}": ("训练状态：{status}｜轮次 {current_epoch}/{total_epochs}｜损失：{loss}", "Training status: {status} | Epoch {current_epoch}/{total_epochs} | Loss: {loss}", "トレーニング状態：{status}｜エポック {current_epoch}/{total_epochs}｜損失：{loss}"),
    "确认运行 Agent": ("确认运行 Agent", "Confirm Agent Run", "Agent 実行の確認"), "将为 Agent“{agent}”创建新的 Run 并调用已选模型，是否继续？": ("将为 Agent“{agent}”创建新的 Run 并调用已选模型，是否继续？", "Create a new Run for Agent “{agent}” and call the selected model?", "Agent「{agent}」の新しい Run を作成し、選択したモデルを呼び出します。続行しますか？"),
    "正在创建 Agent Run：{agent}…": ("正在创建 Agent Run：{agent}…", "Creating Agent Run: {agent}…", "Agent Run を作成中：{agent}…"), "Agent Run 已创建。运行标识：{run_id}": ("Agent Run 已创建。运行标识：{run_id}", "Agent Run created. Run ID: {run_id}", "Agent Run を作成しました。Run ID：{run_id}"),
    "确认取消 Agent Run": ("确认取消 Agent Run", "Confirm Agent Run Cancellation", "Agent Run キャンセルの確認"), "确定请求取消 Run“{run_id}”？": ("确定请求取消 Run“{run_id}”？", "Request cancellation of Run “{run_id}”?", "Run「{run_id}」のキャンセルを要求しますか？"), "正在请求取消 Run：{run_id}…": ("正在请求取消 Run：{run_id}…", "Requesting cancellation of Run: {run_id}…", "Run のキャンセルを要求中：{run_id}…"), "取消请求已提交，正在刷新运行记录。": ("取消请求已提交，正在刷新运行记录。", "Cancellation request submitted. Refreshing run history.", "キャンセル要求を送信しました。実行履歴を更新しています。"),
    "控制面操作未完成：{action}。{error}": ("控制面操作未完成：{action}。{error}", "Control-plane action did not complete: {action}. {error}", "コントロールプレーン操作は完了しませんでした：{action}。{error}"), "启动 Agent Run": ("启动 Agent Run", "Start Agent Run", "Agent Run を開始"), "取消 Agent Run": ("取消 Agent Run", "Cancel Agent Run", "Agent Run をキャンセル"), "获取运行记录": ("获取运行记录", "Load Run History", "実行履歴を取得"), "运行记录刷新未完成。{error}": ("运行记录刷新未完成。{error}", "Run history refresh did not complete. {error}", "実行履歴の更新は完了しませんでした。{error}"),
    "任务快照不可达。{error}": ("任务快照不可达。{error}", "Task snapshot is unavailable. {error}", "タスクスナップショットを利用できません。{error}"), "实时任务流已断开，正在重连。{error}": ("实时任务流已断开，正在重连。{error}", "Live task stream is disconnected and reconnecting. {error}", "リアルタイムタスクストリームは切断され、再接続中です。{error}"), "任务同步未完成。{error}": ("任务同步未完成。{error}", "Task synchronization did not complete. {error}", "タスク同期は完了しませんでした。{error}"),
    "已启动": ("已启动", "Started", "開始済み"),
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


def format_text(source: str, **values) -> str:
    """Format a dynamic UI string through the active locale without exposing raw errors."""
    translator = current()
    locale = translator.locale if translator is not None else "zh_CN"
    return text(source, locale).format(**values)


def format_api_error(error) -> str:
    """Render only the stable code and optional correlation identifier at UI boundaries."""
    code = getattr(error, "code", None) or "OPERATION_FAILED"
    correlation = getattr(error, "correlation_id", None)
    if correlation:
        return format_text("请求未完成（{code}）。关联标识：{correlation}", code=code, correlation=correlation)
    return format_text("请求未完成（{code}）。", code=code)


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
