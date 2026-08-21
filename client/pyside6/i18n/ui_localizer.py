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
    for action in root.findChildren(QAction):
        action.setText(text(_source(action, "text", action.text()), locale))
    if root.windowTitle():
        root.setWindowTitle(text(_source(root, "window_title", root.windowTitle()), locale))
