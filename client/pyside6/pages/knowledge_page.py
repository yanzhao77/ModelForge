"""Knowledge base page with non-blocking API operations."""

from api_client.client import ModelForgeClient
from components.api_worker import AsyncApiMixin
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class KnowledgePage(QWidget, AsyncApiMixin):
    """Knowledge document and RAG UI that never performs HTTP I/O on the GUI thread."""

    def __init__(self, api: ModelForgeClient, parent=None):
        super().__init__(parent)
        self.api = api
        self._init_async_api()
        self._init_ui()
        self.refresh()

    def _init_ui(self):
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self._build_docs_panel())
        splitter.addWidget(self._build_qa_panel())
        splitter.setSizes([280, 320])
        layout = QVBoxLayout(self)
        layout.addWidget(splitter)

    def _build_docs_panel(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        top = QHBoxLayout()
        for label, handler in (("上传文档...", self.upload), ("刷新", self.refresh), ("查看分块", self.show_chunks), ("删除", self.delete_selected)):
            button = QPushButton(label)
            button.clicked.connect(handler)
            top.addWidget(button)
        top.addStretch()
        layout.addLayout(top)
        self.doc_table = QTableWidget()
        self.doc_table.setColumnCount(4)
        self.doc_table.setHorizontalHeaderLabels(["文件名", "类型", "分块数", "时间"])
        self.doc_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.doc_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.doc_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        layout.addWidget(self.doc_table)
        return widget

    def _build_qa_panel(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("模型:"))
        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText("default-model")
        model_row.addWidget(self.model_input, 1)
        layout.addLayout(model_row)
        query_row = QHBoxLayout()
        self.question_input = QLineEdit()
        self.question_input.setPlaceholderText("输入问题（回车先检索，再生成回答）...")
        self.question_input.returnPressed.connect(self.answer)
        query_row.addWidget(self.question_input, 1)
        search_button = QPushButton("仅检索")
        search_button.clicked.connect(self.search_only)
        query_row.addWidget(search_button)
        answer_button = QPushButton("RAG 问答")
        answer_button.clicked.connect(self.answer)
        query_row.addWidget(answer_button)
        layout.addLayout(query_row)
        self.result_view = QTextEdit()
        self.result_view.setReadOnly(True)
        layout.addWidget(self.result_view, 1)
        return widget

    def refresh(self):
        self._run_api(self.api.knowledge_documents, self._render_documents, lambda error: self.result_view.append(f"[加载文档失败] {error}"))

    def _render_documents(self, docs):
        self.doc_table.setRowCount(len(docs))
        for row, document in enumerate(docs):
            for col, key in enumerate(["filename", "filetype", "chunk_count", "created_at"]):
                text = str(document.get(key, ""))
                if key == "created_at" and text:
                    text = text[:19].replace("T", " ")
                self.doc_table.setItem(row, col, QTableWidgetItem(text))
            self.doc_table.item(row, 0).setData(Qt.UserRole, document.get("filename"))

    def upload(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择文档", "", "文档 (*.txt *.md *.py *.json *.yaml *.pdf)")
        if not path:
            return
        self.result_view.append("[上传中...]")
        self._run_api(lambda: self.api.knowledge_upload(path), self._on_uploaded, lambda error: QMessageBox.warning(self, "上传失败", error))

    def _on_uploaded(self, result):
        self.result_view.append(f"[上传] {result}")
        self.refresh()

    def _selected_filename(self):
        rows = self.doc_table.selectionModel().selectedRows()
        return self.doc_table.item(rows[0].row(), 0).data(Qt.UserRole) if rows else None

    def delete_selected(self):
        name = self._selected_filename()
        if not name:
            return
        if QMessageBox.question(self, "确认", f"删除文档 {name}？") == QMessageBox.Yes:
            self._run_api(lambda: self.api.knowledge_delete(name), lambda _: self.refresh(), lambda error: QMessageBox.warning(self, "失败", error))

    def show_chunks(self):
        name = self._selected_filename()
        if name:
            self._run_api(lambda: self.api.knowledge_chunks(name), self._show_chunks, lambda error: QMessageBox.warning(self, "失败", error))

    def _show_chunks(self, chunks):
        self.result_view.clear()
        for chunk in chunks:
            self.result_view.append(f"[块 {chunk.get('chunk_index')}] {chunk.get('content', '')}\n")

    def search_only(self):
        question = self.question_input.text().strip()
        if not question:
            return
        operation = (lambda: self.api.knowledge_query(question, top_k=5)) if hasattr(self.api, "knowledge_query") else (lambda: self.api._post("/api/v1/knowledge/query", json={"question": question, "top_k": 5}))
        self._run_api(operation, self._show_search, lambda error: QMessageBox.warning(self, "失败", error))

    def _show_search(self, result):
        self.result_view.clear()
        for item in result.get("results", []):
            self.result_view.append(f"[{item.get('source', '?')} @{item.get('score', 0)}] {item.get('text', '')}\n")

    def answer(self):
        question = self.question_input.text().strip()
        model = self.model_input.text().strip() or "default-model"
        if not question:
            return
        self.result_view.append("\n[生成中...]")
        self._run_api(lambda: self.api.knowledge_answer(model, question, top_k=3), self._show_answer, lambda error: QMessageBox.warning(self, "失败", error))

    def _show_answer(self, result):
        self.result_view.clear()
        self.result_view.append("【回答】")
        self.result_view.append(result.get("answer", ""))
        self.result_view.append("\n【引用来源】")
        for source in result.get("sources", []):
            self.result_view.append(f"- [{source.get('source')}] @{source.get('score', 0)}: {source.get('text', '')}")
