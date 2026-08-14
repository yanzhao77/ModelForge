"""知识库页面：文档管理 + 检索测试 + RAG 问答。"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QFileDialog, QMessageBox, QTextEdit,
    QHeaderView, QAbstractItemView, QSplitter,
)
from PySide6.QtCore import Qt

from api_client.client import ModelForgeClient


class KnowledgePage(QWidget):
    """知识库管理：上传 / 文档列表 / 删除 / 分块查看 / 检索 / RAG 问答。"""

    def __init__(self, api: ModelForgeClient, parent=None):
        super().__init__(parent)
        self.api = api
        self._init_ui()
        self.refresh()

    def _init_ui(self):
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self._build_docs_panel());
        splitter.addWidget(self._build_qa_panel());
        splitter.setSizes([280, 320]);
        lay = QVBoxLayout(self);
        lay.addWidget(splitter);
        self.setLayout(lay)

    def _build_docs_panel(self) -> QWidget:
        w = QWidget();
        lay = QVBoxLayout(w);
        top = QHBoxLayout();
        upload_btn = QPushButton("上传文档...");
        upload_btn.clicked.connect(self.upload);
        top.addWidget(upload_btn);
        refresh_btn = QPushButton("刷新");
        refresh_btn.clicked.connect(self.refresh);
        top.addWidget(refresh_btn);
        top.addStretch();
        lay.addLayout(top);

        self.doc_table = QTableWidget();
        self.doc_table.setColumnCount(4);
        self.doc_table.setHorizontalHeaderLabels(["文件名", "类型", "分块数", "时间"]);
        self.doc_table.setSelectionBehavior(QAbstractItemView.SelectRows);
        self.doc_table.setEditTriggers(QAbstractItemView.NoEditTriggers);
        self.doc_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch);
        lay.addWidget(self.doc_table, 1);

        ops = QHBoxLayout();
        chunks_btn = QPushButton("查看分块");
        chunks_btn.clicked.connect(self.show_chunks);
        ops.addWidget(chunks_btn);
        delete_btn = QPushButton("删除选中");
        delete_btn.clicked.connect(self.delete_selected);
        ops.addWidget(delete_btn);
        ops.addStretch();
        lay.addLayout(ops);
        return w

    def _build_qa_panel(self) -> QWidget:
        w = QWidget();
        lay = QVBoxLayout(w);
        row = QHBoxLayout();
        row.addWidget(QLabel("模型:"));
        self.model_input = QLineEdit();
        self.model_input.setPlaceholderText("用于生成回答的模型（如 ollama 模型名）");
        row.addWidget(self.model_input, 1);
        lay.addLayout(row);

        q_row = QHBoxLayout();
        self.question_input = QLineEdit();
        self.question_input.setPlaceholderText("输入问题（回车先检索，再生成回答）...");
        self.question_input.returnPressed.connect(self.answer);
        q_row.addWidget(self.question_input, 1);
        search_btn = QPushButton("仅检索");
        search_btn.clicked.connect(self.search_only);
        q_row.addWidget(search_btn);
        answer_btn = QPushButton("RAG 问答");
        answer_btn.clicked.connect(self.answer);
        q_row.addWidget(answer_btn);
        lay.addLayout(q_row);

        self.result_view = QTextEdit();
        self.result_view.setReadOnly(True);
        lay.addWidget(self.result_view, 1);
        return w

    def refresh(self):
        try:
            docs = self.api.knowledge_documents();
        except Exception as e:
            self.result_view.append(f"[加载文档失败] {e}");
            return;
        self.doc_table.setRowCount(len(docs));
        for row, d in enumerate(docs):
            for col, key in enumerate(["filename", "filetype", "chunk_count", "created_at"]):
                text = str(d.get(key, ""));
                if key == "created_at" and text:
                    text = text[:19].replace("T", " ");
                self.doc_table.setItem(row, col, QTableWidgetItem(text));
            self.doc_table.item(row, 0).setData(Qt.UserRole, d.get("filename"))

    def upload(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择文档", "", "文档 (*.txt *.md *.py *.json *.yaml *.pdf)");
        if not path: return;
        try:
            result = self.api.knowledge_upload(path);
            self.result_view.append(f"[上传] {result}");
            self.refresh();
        except Exception as e:
            QMessageBox.warning(self, "上传失败", str(e))

    def _selected_filename(self):
        rows = self.doc_table.selectionModel().selectedRows();
        if not rows: return None;
        return self.doc_table.item(rows[0].row(), 0).data(Qt.UserRole)

    def delete_selected(self):
        name = self._selected_filename();
        if not name: return;
        if QMessageBox.question(self, "确认", f"删除文档 {name}？") == QMessageBox.Yes:
            try:
                self.api.knowledge_delete(name);
                self.refresh();
            except Exception as e:
                QMessageBox.warning(self, "失败", str(e))

    def show_chunks(self):
        name = self._selected_filename();
        if not name: return;
        try:
            chunks = self.api.knowledge_chunks(name);
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e));
            return;
        self.result_view.clear();
        for c in chunks:
            self.result_view.append(
                f"[块 {c.get('chunk_index')}] {c.get('content', '')}\n"
            );

    def search_only(self):
        q = self.question_input.text().strip();
        if not q: return;
        try:
            result = self.api.knowledge_query(q, top_k=5) if hasattr(self.api, "knowledge_query") else self._legacy_query(q);
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e));
            return;
        self.result_view.clear();
        for item in result.get("results", []):
            self.result_view.append(
                f"[{item.get('source', '?')} @{item.get('score', 0)}] {item.get('text', '')}\n"
            );

    def _legacy_query(self, q):
        return self.api._post(
            "/api/v1/knowledge/query", json={"question": q, "top_k": 5}
        );

    def answer(self):
        q = self.question_input.text().strip();
        model = self.model_input.text().strip() or "default-model";
        if not q: return;
        self.result_view.append("\n[生成中...]");
        try:
            result = self.api.knowledge_answer(model, q, top_k=3);
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e));
            return;
        self.result_view.clear();
        self.result_view.append("【回答】");
        self.result_view.append(result.get("answer", ""));
        self.result_view.append("\n【引用来源】");
        for s in result.get("sources", []):
            self.result_view.append(f"- [{s.get('source')}] @{s.get('score', 0)}: {s.get('text', '')}");