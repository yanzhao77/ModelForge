"""ModelForge 2.0 - PySide6 Desktop Client.

A thin client that delegates all business logic to the FastAPI backend.
"""
import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QStackedWidget, QWidget,
    QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTextEdit,
    QListWidget, QLineEdit, QMessageBox, QGroupBox,
)
from PySide6.QtCore import Qt

from api_client.client import ModelForgeClient


class HomePage(QWidget):
    """Home page showing server status and quick actions."""

    def __init__(self, api: ModelForgeClient, parent=None):
        super().__init__(parent)
        self.api = api
        layout = QVBoxLayout(self)

        title = QLabel("<h1>ModelForge 2.0</h1>")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self.status_label = QLabel("Connecting...")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        refresh_btn = QPushButton("Refresh Status")
        refresh_btn.clicked.connect(self.refresh_status)
        layout.addWidget(refresh_btn)

        layout.addStretch()

    def refresh_status(self):
        try:
            info = self.api.get_info()
            self.status_label.setText(
                f"Server: {info.get('name')} v{info.get('version')} - Connected"
            )
        except Exception as e:
            self.status_label.setText(f"Disconnected: {e}")


class ModelCenterPage(QWidget):
    """Model management page."""

    def __init__(self, api: ModelForgeClient, parent=None):
        super().__init__(parent)
        self.api = api
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("<h2>Model Center</h2>"))

        # Scan section
        scan_group = QGroupBox("Scan Models")
        scan_layout = QHBoxLayout()
        self.scan_path = QLineEdit()
        self.scan_path.setPlaceholderText("Model directory path (default)")
        scan_layout.addWidget(QLabel("Path:"))
        scan_layout.addWidget(self.scan_path)
        scan_btn = QPushButton("Scan")
        scan_btn.clicked.connect(self.scan_models)
        scan_layout.addWidget(scan_btn)
        scan_group.setLayout(scan_layout)
        layout.addWidget(scan_group)

        # Model list
        self.model_list = QListWidget()
        layout.addWidget(QLabel("Installed Models:"))
        layout.addWidget(self.model_list)

        # Buttons
        btn_layout = QHBoxLayout()
        refresh_btn = QPushButton("Refresh List")
        refresh_btn.clicked.connect(self.refresh_list)
        btn_layout.addWidget(refresh_btn)
        layout.addLayout(btn_layout)

    def refresh_list(self):
        try:
            models = self.api.list_models()
            self.model_list.clear()
            for m in models:
                self.model_list.addItem(
                    f"{m.get('name', '?')} ({m.get('provider', '?')}) - {m.get('status', '?')}"
                )
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))

    def scan_models(self):
        try:
            path = self.scan_path.text().strip() or None
            result = self.api.scan_models(path)
            self.refresh_list()
            QMessageBox.information(self, "Scan Complete",
                                    f"Found {len(result)} model(s)")
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))


class ChatPage(QWidget):
    """Chat interface page."""

    def __init__(self, api: ModelForgeClient, parent=None):
        super().__init__(parent)
        self.api = api
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("<h2>Chat</h2>"))

        # Model input
        model_layout = QHBoxLayout()
        model_layout.addWidget(QLabel("Model:"))
        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText("e.g., llama2")
        model_layout.addWidget(self.model_input)
        load_btn = QPushButton("Load")
        load_btn.clicked.connect(self.load_model)
        model_layout.addWidget(load_btn)
        layout.addLayout(model_layout)

        # Chat display
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        layout.addWidget(self.chat_display)

        # Message input
        input_layout = QHBoxLayout()
        self.msg_input = QLineEdit()
        self.msg_input.setPlaceholderText("Type your message...")
        self.msg_input.returnPressed.connect(self.send_message)
        input_layout.addWidget(self.msg_input)
        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self.send_message)
        input_layout.addWidget(send_btn)
        layout.addLayout(input_layout)

    def load_model(self):
        model = self.model_input.text().strip()
        if not model:
            return
        try:
            result = self.api.runtime_start(model)
            self.chat_display.append(f"[System] Loaded: {result.get('model')}")
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))

    def send_message(self):
        model = self.model_input.text().strip()
        msg = self.msg_input.text().strip()
        if not model or not msg:
            return
        self.chat_display.append(f"<b>You:</b> {msg}")
        self.msg_input.clear()
        try:
            result = self.api.runtime_chat(model, [{"role": "user", "content": msg}])
            reply = result.get("content", "(no response)")
            self.chat_display.append(f"<b>Assistant:</b> {reply}")
        except Exception as e:
            self.chat_display.append(f"<b>Error:</b> {e}")


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ModelForge 2.0")
        self.resize(900, 600)

        self.api = ModelForgeClient()

        # Central stacked widget for pages
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        # Pages
        self.home_page = HomePage(self.api)
        self.model_page = ModelCenterPage(self.api)
        self.chat_page = ChatPage(self.api)

        self.stack.addWidget(self.home_page)
        self.stack.addWidget(self.model_page)
        self.stack.addWidget(self.chat_page)

        # Navigation tool bar
        nav = self.addToolBar("Navigation")
        home_btn = QPushButton("Home")
        home_btn.clicked.connect(lambda: self.stack.setCurrentWidget(self.home_page))
        nav.addWidget(home_btn)

        model_btn = QPushButton("Models")
        model_btn.clicked.connect(lambda: self.stack.setCurrentWidget(self.model_page))
        nav.addWidget(model_btn)

        chat_btn = QPushButton("Chat")
        chat_btn.clicked.connect(lambda: self.stack.setCurrentWidget(self.chat_page))
        nav.addWidget(chat_btn)

        self.stack.setCurrentWidget(self.home_page)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
