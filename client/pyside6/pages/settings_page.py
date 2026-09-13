"""Modern settings workspace for appearance, language, connection and updates."""
from __future__ import annotations

from components.api_worker import AsyncApiMixin
from components.mf.primitives import MFPanel, MFSection, MFStatusBadge
from i18n.ui_localizer import format_api_error
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


def _format_size(value: int) -> str:
    """Render a byte count for the storage status line."""
    amount = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{int(amount)} B" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TB"


class SettingsPage(QWidget, AsyncApiMixin):
    def __init__(self, api, version: str, check_updates, theme_manager, translator, parent=None):
        QWidget.__init__(self, parent)
        self._init_async_api()
        self.api, self.version, self.check_updates = api, version, check_updates
        self.theme_manager, self.translator = theme_manager, translator
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        root.addWidget(MFSection("偏好设置", "设置"))
        body = QHBoxLayout()
        self.categories = QListWidget()
        self.categories.setFixedWidth(168)
        for item in ("通用", "模型", "外观", "语言", "服务连接", "关于"):
            self.categories.addItem(item)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._general())
        self.pages.addWidget(self._models())
        self.pages.addWidget(self._appearance())
        self.pages.addWidget(self._language())
        self.pages.addWidget(self._backend())
        self.pages.addWidget(self._about())
        self.categories.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.categories.setCurrentRow(0)
        body.addWidget(self.categories)
        body.addWidget(self.pages, 1)
        root.addLayout(body, 1)

    def _page(self, title: str, description: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 0, 0, 0)
        heading = QLabel(title)
        heading.setProperty("role", "pageTitle")
        layout.addWidget(heading)
        detail = QLabel(description)
        detail.setProperty("role", "muted")
        detail.setWordWrap(True)
        layout.addWidget(detail)
        return page, layout

    def _general(self) -> QWidget:
        page, layout = self._page("通用", "管理当前 ModelForge 本地工作区的默认设置。")
        panel = MFPanel()
        panel.layout.addWidget(QLabel("工作区"))
        note = QLabel("对话、模型和任务将继续连接到本机 ModelForge 服务。")
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        panel.layout.addWidget(note)
        layout.addWidget(panel)
        layout.addStretch(1)
        return page

    def _models(self) -> QWidget:
        page, layout = self._page("模型", "设置模型的下载来源与默认存放地址。")

        download_panel = MFPanel()
        download_panel.layout.addWidget(QLabel("Hugging Face 下载源"))
        note = QLabel("中国大陆区域可选择 HF Mirror，用于加速 Hugging Face 模型下载、搜索，以及后续 HF 数据集下载能力。")
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        download_panel.layout.addWidget(note)

        row = QHBoxLayout()
        row.addWidget(QLabel("下载源"))
        row.addStretch(1)
        self.download_source_select = QComboBox()
        self.download_source_select.addItem("Hugging Face 官方源", "official")
        self.download_source_select.addItem("HF Mirror 中国大陆镜像", "hf_mirror")
        self.download_source_select.setEnabled(False)
        row.addWidget(self.download_source_select)
        self.download_source_save = QPushButton("保存")
        self.download_source_save.setEnabled(False)
        self.download_source_save.clicked.connect(self._save_download_source)
        row.addWidget(self.download_source_save)
        download_panel.layout.addLayout(row)

        self.download_source_status = QLabel("正在读取下载源设置…")
        self.download_source_status.setWordWrap(True)
        self.download_source_status.setProperty("role", "muted")
        download_panel.layout.addWidget(self.download_source_status)
        layout.addWidget(download_panel)

        storage_panel = MFPanel()
        storage_panel.layout.addWidget(QLabel("默认存放地址"))
        storage_note = QLabel(
            "下载的模型默认保存到该目录，模型扫描也以此为根目录；目录不存在时会自动创建。"
            "修改位置不会移动已下载的文件。"
        )
        storage_note.setWordWrap(True)
        storage_note.setProperty("role", "muted")
        storage_panel.layout.addWidget(storage_note)

        storage_row = QHBoxLayout()
        storage_row.addWidget(QLabel("目录"))
        self.model_dir_input = QLineEdit()
        self.model_dir_input.setPlaceholderText("例如 ./models 或 D:\\models")
        storage_row.addWidget(self.model_dir_input, 1)
        self.model_dir_browse = QPushButton("浏览…")
        self.model_dir_browse.setEnabled(False)
        self.model_dir_browse.clicked.connect(self._browse_model_dir)
        storage_row.addWidget(self.model_dir_browse)
        self.model_dir_save = QPushButton("保存")
        self.model_dir_save.setEnabled(False)
        self.model_dir_save.clicked.connect(self._save_model_storage)
        storage_row.addWidget(self.model_dir_save)
        self.model_dir_reset = QPushButton("恢复默认")
        self.model_dir_reset.setEnabled(False)
        self.model_dir_reset.clicked.connect(self._reset_model_storage)
        storage_row.addWidget(self.model_dir_reset)
        storage_panel.layout.addLayout(storage_row)

        self.model_storage_status = QLabel("正在读取模型存放地址…")
        self.model_storage_status.setWordWrap(True)
        self.model_storage_status.setProperty("role", "muted")
        storage_panel.layout.addWidget(self.model_storage_status)
        layout.addWidget(storage_panel)

        self._model_storage_default = "./models"
        self._load_download_source()
        self._load_model_storage()
        layout.addStretch(1)
        return page

    def _appearance(self) -> QWidget:
        page, layout = self._page("外观", "选择界面主题，不会影响当前工作内容。")
        panel = MFPanel()
        row = QHBoxLayout()
        row.addWidget(QLabel("主题"))
        row.addStretch(1)
        self.theme_select = QComboBox()
        self.theme_select.addItem("浅色", "light")
        self.theme_select.addItem("深色", "dark")
        self.theme_select.addItem("跟随系统", "system")
        index = self.theme_select.findData(self.theme_manager.mode.value)
        self.theme_select.setCurrentIndex(max(index, 0))
        self.theme_select.currentIndexChanged.connect(lambda _: self.theme_manager.set_mode(self.theme_select.currentData()))
        row.addWidget(self.theme_select)
        panel.layout.addLayout(row)
        layout.addWidget(panel)
        layout.addStretch(1)
        return page

    def _language(self) -> QWidget:
        page, layout = self._page("语言", "为导航和已适配的产品界面选择显示语言。")
        panel = MFPanel()
        row = QHBoxLayout()
        row.addWidget(QLabel("显示语言"))
        row.addStretch(1)
        self.language_select = QComboBox()
        self.language_select.addItem("简体中文", "zh_CN")
        self.language_select.addItem("English", "en_US")
        self.language_select.addItem("日本語", "ja_JP")
        index = self.language_select.findData(self.translator.locale)
        self.language_select.setCurrentIndex(max(index, 0))
        self.language_select.currentIndexChanged.connect(lambda _: self.translator.set_locale(self.language_select.currentData()))
        row.addWidget(self.language_select)
        panel.layout.addLayout(row)
        layout.addWidget(panel)
        layout.addStretch(1)
        return page

    def _backend(self) -> QWidget:
        page, layout = self._page("服务连接", "查看当前本地工作区使用的服务连接。")
        panel = MFPanel()
        self.connection = MFStatusBadge("已连接" if self.api and self.api.username else "需要登录", "online" if self.api and self.api.username else "warning")
        panel.layout.addWidget(self.connection)
        endpoint = QLabel(f"Endpoint  {self.api.base_url}\nAccount   {self.api.username or 'Unavailable'}")
        endpoint.setProperty("role", "muted")
        panel.layout.addWidget(endpoint)
        layout.addWidget(panel)
        layout.addStretch(1)
        return page

    def _load_download_source(self) -> None:
        if not self.api or not hasattr(self.api, "get_download_source"):
            self.download_source_status.setText("当前服务不支持下载源设置。")
            return
        self._run_api(
            self.api.get_download_source,
            self._render_download_source,
            self._download_source_failed,
            request_key="settings.download_source",
        )

    def _render_download_source(self, payload: dict) -> None:
        source = str(payload.get("source") or "official")
        endpoint = str(payload.get("endpoint") or "https://huggingface.co")
        index = self.download_source_select.findData(source)
        if index >= 0:
            self.download_source_select.setCurrentIndex(index)
        self.download_source_select.setEnabled(True)
        self.download_source_save.setEnabled(True)
        self.download_source_status.setText(f"当前 endpoint：{endpoint}")

    def _save_download_source(self) -> None:
        source = str(self.download_source_select.currentData() or "official")
        self.download_source_save.setEnabled(False)
        self.download_source_status.setText("正在保存下载源设置…")
        self._run_api(
            lambda: self.api.update_download_source(source),
            self._download_source_saved,
            self._download_source_failed,
            request_key="settings.download_source",
        )

    def _download_source_saved(self, payload: dict) -> None:
        self._render_download_source(payload)
        QMessageBox.information(self, "下载源已更新", "新的 Hugging Face 下载源将用于后续模型搜索和下载。")

    def _download_source_failed(self, message: str) -> None:
        self.download_source_select.setEnabled(True)
        self.download_source_save.setEnabled(True)
        self.download_source_status.setText(f"下载源设置不可用：{format_api_error(message)}")

    # ---- 模型默认存放地址 ----

    def _set_model_storage_controls(self, enabled: bool) -> None:
        for widget in (self.model_dir_browse, self.model_dir_save, self.model_dir_reset):
            widget.setEnabled(enabled)

    def _load_model_storage(self) -> None:
        if not self.api or not hasattr(self.api, "get_model_storage"):
            self.model_storage_status.setText("当前服务不支持自定义模型存放地址。")
            return
        self._run_api(
            self.api.get_model_storage,
            self._render_model_storage,
            self._model_storage_failed,
            request_key="settings.model_storage",
        )

    def _render_model_storage(self, payload: dict) -> None:
        model_dir = str(payload.get("model_dir") or "./models")
        resolved = str(payload.get("resolved_path") or model_dir)
        self.model_dir_input.setText(model_dir)
        self._model_storage_default = str(payload.get("default_path") or "./models")
        self._set_model_storage_controls(True)
        self.model_storage_status.setText(self._model_storage_summary(payload, resolved))

    @staticmethod
    def _model_storage_summary(payload: dict, resolved: str) -> str:
        exists = bool(payload.get("exists", False))
        writable = bool(payload.get("writable", False))
        if not exists:
            state = "目录尚不存在，保存时会自动创建"
        elif not writable:
            state = "目录不可写"
        else:
            state = "已就绪"
        lines = [f"当前目录：{resolved}", f"状态：{state}"]
        free_bytes = int(payload.get("free_bytes", 0) or 0)
        if free_bytes:
            lines[1] += f" · 剩余空间 {_format_size(free_bytes)}"
        if exists:
            entries = int(payload.get("entries", 0) or 0)
            model_files = int(payload.get("model_files", 0) or 0)
            more = "+" if bool(payload.get("truncated", False)) else ""
            lines.append(f"目录内条目：{entries}{more} · 识别到模型文件：{model_files}")
        return "\n".join(lines)

    def _browse_model_dir(self) -> None:
        start = self.model_dir_input.text().strip() or self._model_storage_default
        chosen = QFileDialog.getExistingDirectory(self, "选择模型存放目录", start)
        if chosen:
            self.model_dir_input.setText(chosen)

    def _save_model_storage(self) -> None:
        target = self.model_dir_input.text().strip()
        if not target:
            self.model_storage_status.setText("请输入模型存放目录。")
            return
        self._set_model_storage_controls(False)
        self.model_storage_status.setText("正在保存模型存放地址…")
        self._run_api(
            lambda: self.api.update_model_storage(target),
            self._model_storage_saved,
            self._model_storage_failed,
            request_key="settings.model_storage",
        )

    def _model_storage_saved(self, payload: dict) -> None:
        self._render_model_storage(payload)
        QMessageBox.information(
            self,
            "模型存放地址已更新",
            "后续模型下载与扫描将使用该目录。已下载的模型文件不会被移动。",
        )

    def _model_storage_failed(self, message: str) -> None:
        self._set_model_storage_controls(True)
        self.model_storage_status.setText(f"模型存放地址不可用：{format_api_error(message)}")

    def _reset_model_storage(self) -> None:
        self.model_dir_input.setText(self._model_storage_default)
        self._save_model_storage()

    def closeEvent(self, event):
        self.shutdown_async_api()
        super().closeEvent(event)

    def _about(self) -> QWidget:
        page, layout = self._page("关于", "通过经过验证的 GitHub Release 获取 ModelForge 更新。")
        panel = MFPanel()
        panel.layout.addWidget(QLabel(f"ModelForge {self.version}"))
        info = QLabel("安装包将在打开前通过 SHA-256 清单验证完整性。")
        info.setWordWrap(True)
        info.setProperty("role", "muted")
        panel.layout.addWidget(info)
        check = QPushButton("检查更新")
        check.clicked.connect(self.check_updates)
        panel.layout.addWidget(check)
        layout.addWidget(panel)
        layout.addStretch(1)
        return page
