from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QFormLayout, QMessageBox


class model_parameters_dialog(QDialog):
    def __init__(self, parent=None, max_new_tokens=500, do_sample=True, temperature=0.9, top_k=50,
                 input_max_length=2048, editable=True):
        super().__init__(parent)
        self.setWindowTitle("Model Parameters Setting")

        self.max_new_tokens = max_new_tokens
        self.do_sample = do_sample
        self.temperature = temperature
        self.top_k = top_k
        self.input_max_length = input_max_length
        self.editable = editable

        self.initUI()

    def initUI(self):
        layout = QFormLayout()

        # 创建输入控件
        self.max_new_tokens_input = QLineEdit(str(self.max_new_tokens))
        self.do_sample_input = QLineEdit(str(self.do_sample))
        self.temperature_input = QLineEdit(str(self.temperature))
        self.top_k_input = QLineEdit(str(self.top_k))
        self.input_max_length_input = QLineEdit(str(self.input_max_length))

        # 设置输入控件的可编辑性
        self.set_editable(self.editable)

        # 添加到布局
        layout.addRow(QLabel("新 tokens 数量:"), self.max_new_tokens_input)
        layout.addRow(QLabel("启用基于温度的采样 (True/False):"), self.do_sample_input)
        layout.addRow(QLabel("控制生成文本的多样性:"), self.temperature_input)
        layout.addRow(QLabel("控制生成文本的质量:"), self.top_k_input)
        layout.addRow(QLabel("指定序列的最大长度:"), self.input_max_length_input)

        # 创建按钮
        button_box = QVBoxLayout()
        save_button = QPushButton("Save")
        cancel_button = QPushButton("Cancel")

        save_button.clicked.connect(self.save_parameters)
        cancel_button.clicked.connect(self.reject)

        button_box.addWidget(save_button)
        button_box.addWidget(cancel_button)

        # 将布局添加到主布局
        main_layout = QVBoxLayout()
        main_layout.addLayout(layout)
        main_layout.addLayout(button_box)

        self.setLayout(main_layout)

    def set_editable(self, editable):
        self.editable = editable
        style = "background-color: lightgray; color: gray;" if not editable else ""
        for widget in [self.max_new_tokens_input, self.do_sample_input, self.temperature_input, self.top_k_input,
                       self.input_max_length_input]:
            widget.setReadOnly(not editable)
            widget.setStyleSheet(style)

    def save_parameters(self):
        if not self.editable:
            QMessageBox.warning(self, "Not Editable", "Parameters are not editable.")
            return

        try:
            self.max_new_tokens = int(self.max_new_tokens_input.text())
            self.do_sample = self.do_sample_input.text().lower() == "true"
            self.temperature = float(self.temperature_input.text())
            self.top_k = int(self.top_k_input.text())
            self.input_max_length = int(self.input_max_length_input.text())

            self.accept()
        except ValueError as e:
            QMessageBox.warning(self, "Invalid Input", f"Please enter valid values: {e}")

    def get_parameters(self):
        return {
            'max_new_tokens': self.max_new_tokens,
            'do_sample': self.do_sample,
            'temperature': self.temperature,
            'top_k': self.top_k,
            'input_max_length': self.input_max_length
        }
