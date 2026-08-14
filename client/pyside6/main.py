"""ModelForge 2.0 - PySide6 Desktop Client (thin client over the FastAPI backend).

Login -> sessions sidebar -> streaming chat; model center / downloader / knowledge
dialogs call the REST API.
"""
import sys

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QLabel, QTextEdit, QListWidget, QListWidgetItem, QLineEdit,
    QMessageBox, QDialog, QMenu, QInputDialog, QTableWidget, QTableWidgetItem,
    QComboBox, QFileDialog, QProgressBar, QHeaderView, QAbstractItemView,
    QCheckBox, QTabWidget,
)

from api_client.client import ModelForgeClient
from pages.agent_page import AgentPage
from pages.dataset_page import DatasetPage
from pages.knowledge_page import KnowledgePage
from pages.login_dialog import LoginDialog
from pages.training_page import TrainingPage


class StreamWorker(QThread):
    """Consumes the SSE chat stream in a background thread."""
    delta = Signal(str)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, api, model, messages, session_id):
        super().__init__()
        self.api = api
        self.model = model
        self.messages = messages
        self.session_id = session_id

    def run(self):
        try:
            for event in self.api.stream_chat(self.model, self.messages, self.session_id):
                etype = event.get("type")
                if etype == "delta":
                    self.delta.emit(event.get("data", ""))
                elif etype == "done":
                    self.done.emit(event.get("data", {}).get("response", ""))
                    return
                elif etype == "error":
                    self.failed.emit(event.get("data", "未知错误"))
                    return
        except Exception as e:
            self.failed.emit(str(e))


class SessionSidebar(QWidget):
    """会话列表：新建 / 切换 / 右键重命名 / 清空 / 删除。"""
    session_selected = Signal(int)
    session_created = Signal(int)

    def __init__(self, api: ModelForgeClient, parent=None):
        super().__init__(parent)
        self.api = api
        self.current_session_id = None
        self._init_ui()
        self.refresh()

    def _init_ui(self):
        lay = QVBoxLayout()
        lay.setContentsMargins(5, 5, 5, 5)
        title = QLabel("对话列表");
        title.setStyleSheet("font-size: 14px; font-weight: bold; padding: 5px;");
        lay.addWidget(title)

        new_btn = QPushButton("+ 新建对话");
        new_btn.clicked.connect(self.create_new_session);
        lay.addWidget(new_btn)

        self.session_list = QListWidget();
        self.session_list.setContextMenuPolicy(Qt.CustomContextMenu);
        self.session_list.customContextMenuRequested.connect(self._show_menu);
        self.session_list.itemClicked.connect(self._on_clicked);
        lay.addWidget(self.session_list);
        self.setLayout(lay)

    def refresh(self):
        self.session_list.clear()
        try:
            sessions = self.api.list_sessions()
        except Exception:
            sessions = []
        for s in sessions:
            item = QListWidgetItem(f"{s['title']}\n{s.get('message_count', 0)} 条消息")
            item.setData(Qt.UserRole, s["id"]);
            if s["id"] == self.current_session_id:
                item.setSelected(True);
            self.session_list.addItem(item)

    def create_new_session(self):
        try:
            data = self.api.create_session("新对话");
            self.current_session_id = data["id"];
            self.refresh();
            self.session_created.emit(data["id"]);
        except Exception as e:
            QMessageBox.warning(self, "错误", str(e))

    def _on_clicked(self, item):
        sid = item.data(Qt.UserRole);
        if sid != self.current_session_id:
            self.current_session_id = sid;
            self.session_selected.emit(sid)

    def _show_menu(self, pos):
        item = self.session_list.itemAt(pos);
        if not item:
            return
        sid = item.data(Qt.UserRole);
        menu = QMenu(self);
        rename = menu.addAction("重命名");
        clear = menu.addAction("清空消息");
        menu.addSeparator();
        delete = menu.addAction("删除");
        action = menu.exec_(self.session_list.mapToGlobal(pos));
        if action == rename:
            self._rename(sid)
        elif action == clear:
            self._clear(sid)
        elif action == delete:
            self._delete(sid)

    def _rename(self, sid):
        title, ok = QInputDialog.getText(self, "重命名", "新的标题:");
        if ok and title.strip():
            self.api.rename_session(sid, title.strip());
            self.refresh()

    def _clear(self, sid):
        if QMessageBox.question(self, "确认", "确定清空此对话的所有消息？") == QMessageBox.Yes:
            self.api.clear_messages(sid);
            self.refresh()
            self.session_selected.emit(sid)

    def _delete(self, sid):
        if QMessageBox.question(self, "确认", "确定删除此对话？") == QMessageBox.Yes:
            self.api.delete_session(sid);
            if sid == self.current_session_id:
                self.current_session_id = None;
                self.create_new_session();
            else:
                self.refresh()


class ChatPage(QWidget):
    """聊天区：模型选择 + 消息流（SSE 流式）+ 输入框。"""

    def __init__(self, api: ModelForgeClient, parent=None):
        super().__init__(parent)
        self.api = api
        self.session_id = None
        self.messages: list = []
        self.worker = None
        self.session_refresher = None
        self._init_ui()

    def _init_ui(self):
        lay = QVBoxLayout()

        top = QHBoxLayout();
        top.addWidget(QLabel("模型:"));
        self.model_input = QLineEdit();
        self.model_input.setPlaceholderText("模型名（Ollama 模型 或 已注册模型名）");
        top.addWidget(self.model_input);
        load_btn = QPushButton("加载");
        load_btn.clicked.connect(self.load_model);
        top.addWidget(load_btn);
        self.kb_check = QCheckBox("知识库(RAG)");
        top.addWidget(self.kb_check);
        top.addStretch();
        lay.addLayout(top)

        self.display = QTextEdit();
        self.display.setReadOnly(True);
        self.display.setStyleSheet("background-color: #fafafa; border: 1px solid #ddd; padding: 8px;");
        lay.addWidget(self.display, 1)

        bottom = QHBoxLayout();
        self.msg_input = QLineEdit();
        self.msg_input.setPlaceholderText("输入消息，Enter 发送...");
        self.msg_input.returnPressed.connect(self.send_message);
        bottom.addWidget(self.msg_input);
        self.send_btn = QPushButton("发送");
        self.send_btn.clicked.connect(self.send_message);
        bottom.addWidget(self.send_btn);
        lay.addLayout(bottom)
        self.setLayout(lay)

    def set_session(self, session_id):
        self.session_id = session_id;
        self.display.clear();
        self.messages = []
        try:
            for msg in self.api.list_messages(session_id):
                self._append_msg(msg["role"], msg["content"]);
                self.messages.append({"role": msg["role"], "content": msg["content"]});
        except Exception as e:
            self.display.append(f"[加载消息失败] {e}")

    def load_model(self):
        model = self.model_input.text().strip();
        if not model:
            QMessageBox.warning(self, "提示", "请输入模型名");
            return
        try:
            self.api.runtime_start(model);
            self.display.append(f"<b style='color:#4CAF50'>[系统]</b> 模型已加载: {model}<br>");
        except Exception as e:
            QMessageBox.warning(self, "加载失败", str(e))

    def _append_msg(self, role: str, content: str):
        color = "#2196F3" if role == "user" else "#4CAF50"
        name = "用户" if role == "user" else "助手"
        self.display.append(f"<div style='margin:6px 0'><b style='color:{color}'>{name}:</b> {content}</div>")

    def send_message(self):
        text = self.msg_input.text().strip();
        model = self.model_input.text().strip();
        if not text:
            return
        if not model:
            QMessageBox.warning(self, "提示", "请先填写模型名");
            return
        if self.worker and self.worker.isRunning():
            return
        self._append_msg("user", text);
        self.messages.append({"role": "user", "content": text});
        self.msg_input.clear();
        self.send_btn.setEnabled(False);

        if self.kb_check.isChecked():
            self._answer_with_kb(model, text)
            return

        self.display.append("<b style='color:#4CAF50'>助手:</b> ");
        self.display.moveCursor(self.display.textCursor().End)

        self.worker = StreamWorker(self.api, model, self.messages, self.session_id);
        self.worker.delta.connect(self._on_delta);
        self.worker.done.connect(self._on_done);
        self.worker.failed.connect(self._on_failed);
        self.worker.start()

    def _answer_with_kb(self, model: str, question: str):
        """知识库开关开启时：走 RAG 问答（检索 + 生成）。"""
        try:
            result = self.api.knowledge_answer(model, question, top_k=3)
        except Exception as e:
            self.display.append(f"<b style='color:#FF5722'>[错误]</b> {e}<br>")
            self.send_btn.setEnabled(True)
            return
        answer = result.get("answer", "")
        self.display.append(f"<b style='color:#4CAF50'>助手:</b> {answer}<br>")
        for s in result.get("sources", []):
            self.display.append(f"<span style='color:#888'>[来源: {s.get('source')} @{s.get('score', 0)}]</span><br>")
        self.send_btn.setEnabled(True)

    def _on_delta(self, chunk: str):
        cur = self.display.textCursor();
        cur.movePosition(cur.End);
        self.display.setTextCursor(cur);
        self.display.insertPlainText(chunk);
        sb = self.display.verticalScrollBar();
        sb.setValue(sb.maximum());

    def _on_done(self, full: str):
        self.display.append("<br>");
        self.messages.append({"role": "assistant", "content": full});
        self.send_btn.setEnabled(True);
        if self.session_id:
            try:
                self.api.auto_title(self.session_id);
            except Exception:
                pass
            if getattr(self, "session_refresher", None):
                self.session_refresher()

    def _on_failed(self, err: str):
        self.display.append(f"<b style='color:#FF5722'>[错误]</b> {err}<br>");
        self.send_btn.setEnabled(True)

class ModelCenterDialog(QDialog):
    """模型中心：列表 / 扫描 / 手动登记 / 删除。"""

    def __init__(self, api: ModelForgeClient, parent=None):
        super().__init__(parent)
        self.api = api
        self.setWindowTitle("模型中心")
        self.resize(640, 460)
        self._init_ui()
        self.refresh()

    def _init_ui(self):
        lay = QVBoxLayout(self)
        scan_row = QHBoxLayout()
        self.scan_path = QLineEdit()
        self.scan_path.setPlaceholderText("扫描路径（留空使用默认模型目录）")
        scan_row.addWidget(self.scan_path)
        scan_btn = QPushButton("扫描")
        scan_btn.clicked.connect(self.scan)
        scan_row.addWidget(scan_btn)
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.refresh)
        scan_row.addWidget(refresh_btn)
        lay.addLayout(scan_row)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["ID", "名称", "提供方", "大小", "状态"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        lay.addWidget(self.table)

        btn_row = QHBoxLayout()
        install_btn = QPushButton("登记模型...")
        install_btn.clicked.connect(self.install)
        btn_row.addWidget(install_btn)
        remove_btn = QPushButton("删除选中")
        remove_btn.clicked.connect(self.remove)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

    def refresh(self):
        try:
            models = self.api.list_models()
        except Exception as e:
            QMessageBox.warning(self, "错误", str(e))
            return
        self.table.setRowCount(len(models))
        for row, m in enumerate(models):
            for col, key in enumerate(["id", "name", "provider", "size", "status"]):
                self.table.setItem(row, col, QTableWidgetItem(str(m.get(key, ""))))
            self.table.item(row, 0).setData(Qt.UserRole, m.get("id"))

    def scan(self):
        try:
            result = self.api.scan_models(self.scan_path.text().strip() or None)
            self.refresh()
            QMessageBox.information(self, "完成", f"发现 {len(result)} 个模型")
        except Exception as e:
            QMessageBox.warning(self, "扫描失败", str(e))

    def install(self):
        name, ok1 = QInputDialog.getText(self, "登记模型", "模型名称:")
        if not ok1 or not name.strip():
            return
        path, ok2 = QInputDialog.getText(self, "登记模型", "模型路径:")
        if not ok2 or not path.strip():
            return
        try:
            self.api.install_model(name.strip(), "local", path.strip())
            self.refresh()
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e))

    def remove(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        mid = self.table.item(rows[0].row(), 0).data(Qt.UserRole)
        if QMessageBox.question(self, "确认", "删除该模型记录？") == QMessageBox.Yes:
            try:
                self.api.remove_model(mid)
                self.refresh()
            except Exception as e:
                QMessageBox.warning(self, "失败", str(e))


class DownloadDialog(QDialog):
    """GGUF 模型下载器：HF 搜索（作者/量化）+ 后台下载 + 进度轮询。"""

    def __init__(self, api: ModelForgeClient, parent=None):
        super().__init__(parent)
        self.api = api
        self.setWindowTitle("GGUF 模型下载器")
        self.resize(720, 520)
        self._task_id = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._init_ui()

    def _init_ui(self):
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.author_combo = QComboBox()
        self.author_combo.addItem("所有作者", None)
        for author in ["TheBloke", "lmstudio-community", "QuantFactory", "bartowski", "mradermacher"]:
            self.author_combo.addItem(author, author)
        row.addWidget(QLabel("作者:"))
        row.addWidget(self.author_combo)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索 GGUF 模型...")
        self.search_input.returnPressed.connect(self.search)
        row.addWidget(self.search_input, 1)
        search_btn = QPushButton("搜索")
        search_btn.clicked.connect(self.search)
        row.addWidget(search_btn)
        lay.addLayout(row)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["模型", "作者", "下载量", "ID"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        lay.addWidget(self.table)

        self.status = QLabel("就绪")
        lay.addWidget(self.status)
        download_btn = QPushButton("下载选中模型")
        download_btn.clicked.connect(self.download)
        lay.addWidget(download_btn)

    def search(self):
        query = self.search_input.text().strip()
        author = self.author_combo.currentData()
        self.status.setText("搜索中...")
        try:
            results = self.api.search_models(query, author, 20)
        except Exception as e:
            self.status.setText(f"搜索失败: {e}")
            return
        self.table.setRowCount(len(results))
        for row, m in enumerate(results):
            self.table.setItem(row, 0, QTableWidgetItem(str(m.get("id", ""))))
            self.table.setItem(row, 1, QTableWidgetItem(str(m.get("author", ""))))
            self.table.setItem(row, 2, QTableWidgetItem(str(m.get("downloads", ""))))
            self.table.setItem(row, 3, QTableWidgetItem(str(m.get("id", ""))))
        self.status.setText(f"找到 {len(results)} 个模型")

    def download(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.warning(self, "提示", "请先选择一个模型")
            return
        repo_id = self.table.item(rows[0].row(), 3).text()
        try:
            task = self.api.download_model(repo_id)
            self._task_id = task["task_id"]
            self.status.setText(f"开始下载: {repo_id}")
            self._timer.start(1500)
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e))

    def _poll(self):
        if not self._task_id:
            self._timer.stop()
            return
        try:
            task = self.api.download_status(self._task_id)
        except Exception:
            return
        self.status.setText(f"{task['repo_id']} - {task['status']} - {task.get('message', '')}")
        if task["status"] in ("done", "error"):
            self._timer.stop()
            self._task_id = None
            if task["status"] == "done":
                QMessageBox.information(self, "完成", f"下载完成:\n{task.get('target_path')}")
            else:
                QMessageBox.warning(self, "失败", task.get("error", ""))


class KnowledgeDialog(QDialog):
    """知识库：上传文档 + 检索问答。"""

    def __init__(self, api: ModelForgeClient, parent=None):
        super().__init__(parent)
        self.api = api
        self.setWindowTitle("知识库")
        self.resize(560, 420)
        lay = QVBoxLayout(self)
        upload_row = QHBoxLayout()
        upload_btn = QPushButton("上传文档...")
        upload_btn.clicked.connect(self.upload)
        upload_row.addWidget(upload_btn)
        upload_row.addStretch()
        lay.addLayout(upload_row)

        self.query_input = QLineEdit()
        self.query_input.setPlaceholderText("输入问题检索知识库...")
        self.query_input.returnPressed.connect(self.query)
        lay.addWidget(self.query_input)
        query_btn = QPushButton("检索")
        query_btn.clicked.connect(self.query)
        lay.addWidget(query_btn)

        self.result = QTextEdit()
        self.result.setReadOnly(True)
        lay.addWidget(self.result)

    def upload(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择文档", "", "文档 (*.txt *.md *.py *.json *.yaml *.pdf)")
        if not path:
            return
        try:
            result = self.api.knowledge_upload(path)
            self.result.append(f"[上传] {result}")
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e))

    def query(self):
        q = self.query_input.text().strip()
        if not q:
            return
        try:
            result = self.api.knowledge_query(q)
            self.result.clear()
            for item in result.get("results", []):
                self.result.append(f"[{item.get('source', '?')}] (score={item.get('score', 0)})\n{item.get('text', '')}\n")
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e))


class MainWindow(QMainWindow):
    """主窗口：会话侧边栏 + 聊天区 + 菜单。"""

    def __init__(self, api: ModelForgeClient):
        super().__init__()
        self.api = api
        self.setWindowTitle(f"ModelForge 2.1 - {api.username or ''}")
        self.resize(1080, 680)
        self._init_ui()
        self._load_status()

    def _init_ui(self):
        # 主标签页：聊天 / 数据集 / 训练 / 知识库
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        # --- 标签 0: 聊天 ---
        chat_tab = QWidget()
        chat_layout = QVBoxLayout(chat_tab)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal)
        self.session_sidebar = SessionSidebar(self.api)
        self.session_sidebar.session_selected.connect(self._on_session_selected)
        self.session_sidebar.session_created.connect(self._on_session_selected)
        splitter.addWidget(self.session_sidebar)

        self.chat_page = ChatPage(self.api)
        self.chat_page.session_refresher = self.session_sidebar.refresh
        splitter.addWidget(self.chat_page)
        splitter.setSizes([240, 840])
        chat_layout.addWidget(splitter)
        self.tabs.addTab(chat_tab, "聊天")

        # --- 标签 1-3: 数据集 / 训练 / 知识库 ---
        self.dataset_page = DatasetPage(self.api)
        self.tabs.addTab(self.dataset_page, "数据集")

        self.training_page = TrainingPage(self.api)
        self.tabs.addTab(self.training_page, "训练")

        self.knowledge_page = KnowledgePage(self.api)
        self.tabs.addTab(self.knowledge_page, "知识库")

        # --- 标签 4: Agent 3.0 ---
        self.agent_page = AgentPage(self.api)
        self.tabs.addTab(self.agent_page, "Agent")

        menubar = self.menuBar()
        model_menu = menubar.addMenu("模型")
        model_center = QAction("模型中心", self)
        model_center.triggered.connect(lambda: ModelCenterDialog(self.api, self).exec_())
        model_menu.addAction(model_center)
        download = QAction("下载 GGUF 模型", self)
        download.triggered.connect(lambda: DownloadDialog(self.api, self).exec_())
        model_menu.addAction(download)

        tools_menu = menubar.addMenu("工具")
        nav = QAction("刷新训练数据", self)
        nav.triggered.connect(self.training_page.refresh_all)
        tools_menu.addAction(nav)
        refresh = QAction("刷新会话", self)
        refresh.triggered.connect(self.session_sidebar.refresh)
        tools_menu.addAction(refresh)

        about_menu = menubar.addMenu("帮助")
        about = QAction("关于", self)
        about.triggered.connect(lambda: QMessageBox.about(
            self, "关于 ModelForge",
            "<h3>ModelForge 2.1</h3><p>本地 AI Agent 工作站</p>"
            "<p>FastAPI 后端 + PySide6 瘦客户端</p>",
        ))
        about_menu.addAction(about)

        self.statusBar().showMessage(f"后端: {self.api.base_url}")

    def _load_status(self):
        try:
            info = self.api.get_info()
            self.statusBar().showMessage(f"后端: {self.api.base_url}  v{info.get('version')}  用户: {self.api.username}")
        except Exception as e:
            self.statusBar().showMessage(f"后端连接失败: {e}")

    def _on_session_selected(self, session_id: int):
        self.chat_page.set_session(session_id)


def main():
    app = QApplication(sys.argv)
    api = ModelForgeClient()

    # 登录 / 注册
    login = LoginDialog(api)
    if login.exec_() != LoginDialog.Accepted:
        sys.exit(0)

    window = MainWindow(api)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
