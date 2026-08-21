"""Non-executing starter examples for ModelForge product workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from i18n.ui_localizer import localize_tree
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)


@dataclass(frozen=True)
class Example:
    title: str
    description: str
    template: str


EXAMPLES: dict[str, list[Example]] = {
    "chat": [
        Example(
            "Review a code change",
            "Ask for a focused review with concrete risks and next steps.",
            "Review this change for correctness, edge cases, and maintainability. Return findings grouped by severity, then suggest the smallest safe fixes.",
        ),
        Example(
            "Summarize a document",
            "Turn long material into an actionable brief.",
            "Summarize the following material for a busy engineer. Include: key decisions, open questions, risks, and next actions.\n\n[paste material]",
        ),
        Example(
            "Plan an implementation",
            "Create a bounded technical plan before writing code.",
            "Help me plan this feature. First ask any essential clarifying questions, then propose a staged implementation plan with risks, tests, and a rollback approach.\n\nFeature: [describe it]",
        ),
    ],
    "models": [
        Example(
            "Local coding assistant",
            "Choose a model for code completion and code review.",
            "Look for an instruction-tuned coding model that fits local memory limits. Validate the model in Chat with a small review prompt before using it for Agent runs.",
        ),
        Example(
            "Multilingual assistant",
            "Evaluate a model across Chinese, English, and Japanese.",
            "Use the same short question in Chinese, English, and Japanese. Compare clarity, factual caution, formatting, and response speed before selecting a default.",
        ),
        Example(
            "Private document Q&A",
            "Select a model for a local knowledge base.",
            "Prefer a stable instruction model with enough context for retrieved passages. Test it with one source-backed question before using it for sensitive local documents.",
        ),
    ],
    "datasets": [
        Example(
            "Instruction-tuning JSONL",
            "Prepare supervised chat examples before training.",
            "Create a UTF-8 JSONL file with one instruction/response pair per line. Keep a small holdout set for evaluation and run Training preflight before creating a job.",
        ),
        Example(
            "Evaluation CSV",
            "Measure a model consistently across representative prompts.",
            "Create a CSV with columns: id, prompt, expected_behavior, notes. Include difficult examples and failures you want to avoid, not only happy paths.",
        ),
        Example(
            "Knowledge source bundle",
            "Import project documentation for retrieval.",
            "Collect concise Markdown or text documents with clear titles and headings. Remove duplicate drafts, then import and validate a few retrieval queries.",
        ),
    ],
    "training": [
        Example(
            "LoRA domain assistant",
            "Fine-tune a local model on a focused style or domain.",
            "Use LoRA with a clean instruction dataset. Start with a small sample run, inspect loss and outputs, then scale only after the evaluation set improves.",
        ),
        Example(
            "Support-answer style",
            "Teach a model a consistent response format.",
            "Use examples that include the desired tone, structured steps, and safe uncertainty. Keep policies and factual sources out of the target response unless they are verified.",
        ),
        Example(
            "Regression training check",
            "Compare a candidate run to a known baseline.",
            "Before launching a full run, define 10–20 evaluation prompts. Record baseline answers, train a small job, and compare quality plus safety before registering the model.",
        ),
    ],
    "knowledge": [
        Example(
            "Project documentation Q&A",
            "Ask grounded questions against imported project docs.",
            "What are the deployment steps for this project? Cite the source document and section for each step. If the source does not answer, say so.",
        ),
        Example(
            "Research digest",
            "Extract decisions and caveats from a paper set.",
            "Compare the imported research documents. Summarize the shared conclusion, major disagreements, and the evidence that supports each claim.",
        ),
        Example(
            "Release-note lookup",
            "Find user-impacting changes in product notes.",
            "What changed that could affect existing users? Return a short migration checklist and quote the relevant release-note passages.",
        ),
    ],
    "agents": [
        Example(
            "Research Agent",
            "Collect sources, contrast evidence, and produce a cited brief.",
            "Research [topic]. Use reliable primary sources where possible. Separate confirmed facts from assumptions, list open questions, and return a concise brief with citations.",
        ),
        Example(
            "Code Review Agent",
            "Review a change without silently modifying it.",
            "Review the proposed change. Identify correctness, security, and maintainability concerns. Do not modify files. Return findings by severity and include suggested tests.",
        ),
        Example(
            "Data Quality Agent",
            "Audit a dataset before training or retrieval.",
            "Inspect this dataset for duplicates, malformed records, missing fields, privacy risks, and class imbalance. Return an actionable validation report; do not delete data.",
        ),
    ],
    "tasks": [
        Example(
            "Review a training run",
            "Inspect real progress before acting.",
            "Open the running training task, review progress and logs, then decide whether the current loss trend and output samples justify waiting, stopping, or iterating.",
        ),
        Example(
            "Investigate an Agent failure",
            "Use the task timeline to find the first failing step.",
            "Open the failed Agent run. Read its event timeline in order, identify the first non-recoverable error, export logs if needed, and propose the smallest retry-safe fix.",
        ),
        Example(
            "Archive an execution record",
            "Save a reproducible trace for later review.",
            "Open the task log, export JSON for structured analysis and text for human review. Include task ID, environment, input, output, and the final status.",
        ),
    ],
    "runtime": [
        Example(
            "First local chat",
            "Start one model and validate a basic response.",
            "Start a local model, wait until it reports Ready, then open Chat and send one concise test prompt before using advanced features.",
        ),
        Example(
            "Switch active model",
            "Avoid leaving unused runtimes running.",
            "Before starting another model, review active runtimes. Stop models you no longer need, then start the new one and verify it responds in Chat.",
        ),
        Example(
            "Backend troubleshooting",
            "Confirm service state before deeper diagnosis.",
            "If the runtime is unavailable, verify ModelForge Server is running, review the connection status, then inspect the task or service error before retrying any operation.",
        ),
    ],
}


class ExampleLibraryDialog(QDialog):
    def __init__(
        self, area: str, on_use: Callable[[Example], None] | None = None, parent=None
    ):
        super().__init__(parent)
        self.area, self.on_use = area, on_use
        self.setWindowTitle("起步示例")
        self.resize(620, 420)
        layout = QHBoxLayout(self)
        self.list = QListWidget()
        for example in EXAMPLES.get(area, []):
            item = QListWidgetItem(example.title)
            item.setData(Qt.UserRole, example)
            self.list.addItem(item)
        self.list.currentItemChanged.connect(self._show)
        layout.addWidget(self.list, 1)
        right = QVBoxLayout()
        self.description = QLabel("选择示例，查看可安全复用的起步模板。")
        self.description.setWordWrap(True)
        right.addWidget(self.description)
        self.template = QTextEdit()
        self.template.setReadOnly(True)
        right.addWidget(self.template, 1)
        buttons = QHBoxLayout()
        copy = QPushButton("复制模板")
        copy.clicked.connect(self._copy)
        use = QPushButton("作为起点使用")
        use.setProperty("accent", True)
        use.clicked.connect(self._use)
        buttons.addWidget(copy)
        buttons.addWidget(use)
        right.addLayout(buttons)
        layout.addLayout(right, 2)
        localize_tree(self)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _example(self) -> Example | None:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _show(self, item) -> None:
        example = item.data(Qt.UserRole) if item else None
        if example:
            self.description.setText(example.description)
            self.template.setPlainText(example.template)

    def _copy(self) -> None:
        example = self._example()
        if example:
            QApplication.clipboard().setText(example.template)

    def _use(self) -> None:
        example = self._example()
        if example and self.on_use:
            self.on_use(example)
        self.accept()


def open_examples(
    area: str, parent=None, on_use: Callable[[Example], None] | None = None
) -> None:
    ExampleLibraryDialog(area, on_use, parent).exec()
