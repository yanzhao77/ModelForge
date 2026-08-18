"""Responsive session navigation backed by background API calls."""
from __future__ import annotations

from components.api_worker import AsyncApiMixin
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class SessionSidebar(QWidget, AsyncApiMixin):
    session_selected = Signal(int)
    session_created = Signal(int)

    def __init__(self, api, parent=None):
        QWidget.__init__(self, parent)
        self._init_async_api()
        self.api = api
        self.current_session_id = None
        self._loading = False
        self._init_ui()
        self.refresh()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        title = QLabel("对话列表")
        title.setStyleSheet("font-size: 14px; font-weight: bold; padding: 5px;")
        layout.addWidget(title)
        self.new_btn = QPushButton("+ 新建对话")
        self.new_btn.clicked.connect(self.create_new_session)
        layout.addWidget(self.new_btn)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.session_list = QListWidget()
        self.session_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.session_list.customContextMenuRequested.connect(self._show_menu)
        self.session_list.itemClicked.connect(self._on_clicked)
        layout.addWidget(self.session_list)

    def _set_loading(self, loading):
        self._loading = loading
        self.new_btn.setEnabled(not loading)

    def refresh(self):
        if self._loading:
            return
        self._set_loading(True)
        self.status.setText("正在同步会话…")
        self._run_api(self.api.list_sessions, self._render_sessions, self._load_failed)

    def _render_sessions(self, sessions):
        self._set_loading(False)
        self.session_list.clear()
        for session in sessions:
            item = QListWidgetItem(f"{session['title']}\n{session.get('message_count', 0)} 条消息")
            item.setData(Qt.UserRole, session["id"])
            self.session_list.addItem(item)
            if session["id"] == self.current_session_id:
                self.session_list.setCurrentItem(item)
        self.status.setText(f"已同步 {len(sessions)} 个会话。")

    def _load_failed(self, error):
        self._set_loading(False)
        self.status.setText(f"会话同步失败：{error}")

    def create_new_session(self):
        if self._loading:
            return
        self._set_loading(True)
        self.status.setText("正在创建新对话…")
        self._run_api(lambda: self.api.create_session("新对话"), self._created, self._action_failed)

    def _created(self, data):
        self._set_loading(False)
        self.current_session_id = data["id"]
        self.session_created.emit(data["id"])
        self.refresh()

    def _on_clicked(self, item):
        session_id = item.data(Qt.UserRole)
        if session_id != self.current_session_id:
            self.current_session_id = session_id
            self.session_selected.emit(session_id)

    def _show_menu(self, pos):
        item = self.session_list.itemAt(pos)
        if not item or self._loading:
            return
        session_id = item.data(Qt.UserRole)
        menu = QMenu(self)
        rename = menu.addAction("重命名")
        clear = menu.addAction("清空消息")
        menu.addSeparator()
        delete = menu.addAction("删除")
        action = menu.exec_(self.session_list.mapToGlobal(pos))
        if action == rename:
            self._rename(session_id)
        elif action == clear:
            self._clear(session_id)
        elif action == delete:
            self._delete(session_id)

    def _rename(self, session_id):
        title, ok = QInputDialog.getText(self, "重命名", "新的标题:")
        if not ok or not title.strip():
            return
        self._set_loading(True)
        self._run_api(lambda: self.api.rename_session(session_id, title.strip()), lambda _result: self._refresh_after_action(), self._action_failed)

    def _clear(self, session_id):
        if QMessageBox.question(self, "确认", "确定清空此对话的所有消息？") != QMessageBox.Yes:
            return
        self._set_loading(True)
        self._run_api(lambda: self.api.clear_messages(session_id), lambda _result: self._cleared(session_id), self._action_failed)

    def _cleared(self, session_id):
        self._set_loading(False)
        self.session_selected.emit(session_id)
        self.refresh()

    def _delete(self, session_id):
        if QMessageBox.question(self, "确认", "确定删除此对话？") != QMessageBox.Yes:
            return
        self._set_loading(True)
        self._run_api(lambda: self.api.delete_session(session_id), lambda _result: self._deleted(session_id), self._action_failed)

    def _deleted(self, session_id):
        self._set_loading(False)
        if session_id == self.current_session_id:
            self.current_session_id = None
            self.create_new_session()
        else:
            self.refresh()

    def _refresh_after_action(self):
        self._set_loading(False)
        self.refresh()

    def _action_failed(self, error):
        self._set_loading(False)
        self.status.setText(f"会话操作失败：{error}")
        QMessageBox.warning(self, "会话操作失败", error)
