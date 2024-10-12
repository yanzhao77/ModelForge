import sys
from PyQt6.QtCore import QRunnable

from common.const.common_const import common_const
from pytorch.interface_generate import interface_generate
from pytorch.model_generate import model_generate


# 定义一个用于重定向标准输出的类
class CustomStdout:
    def __init__(self, text_area):
        self.text_area = text_area

    def write(self, text):
        self.text_area.print(text)
        self.flush()

    def flush(self):
        # 在这里可以实现缓冲区刷新的逻辑
        pass


class CustomStdin:
    def __init__(self, input_line_edit):
        self.input_line_edit = input_line_edit
        self.buffer = []

    def readline(self):
        if not self.buffer and not self.input_line_edit.text().strip() == "":
            self.buffer.append(self.input_line_edit.text())
            self.input_line_edit.clear()
        return self.buffer.pop(0) + '\n' if self.buffer else ''


# 基类
class BaseRunnable(QRunnable):
    def __init__(self, text_area):
        super().__init__()
        self.text_area = text_area

    def run(self):
        # 重定向标准输出
        sys.stdout = CustomStdout(self.text_area)
        self._run()

    def _run(self):
        raise NotImplementedError("Subclasses must implement the _run method")


# 模型加载基类
class ui_model_lunch(BaseRunnable):
    def __init__(self, models_parameters, text_area):
        super().__init__(text_area)
        self.models_parameters = models_parameters

    def _run(self):
        try:
            if self.models_parameters:
                self.text_area.model = model_generate(
                    self.models_parameters[common_const.model_path],
                    self.models_parameters[common_const.max_new_tokens],
                    self.models_parameters[common_const.do_sample],
                    self.models_parameters[common_const.temperature],
                    self.models_parameters[common_const.top_k],
                    self.models_parameters[common_const.input_max_length]
                )
            else:
                self.text_area.model = model_generate(self.models_parameters[common_const.model_path])
            self.text_area.model.pipeline_question()
            self.text_area.set_model_name(self.models_parameters[common_const.model_name])
        except Exception as e:
            print(f"Error loading files: {e}")


# 模型运行基类
class ui_model_run(BaseRunnable):
    def __init__(self, text, model, text_area):
        super().__init__(text_area)
        self.text = text
        self.model = model

    def _run(self):
        try:
            result = self.model.pipeline_answer(self.text)
            self.text_area.append_model(self.model.model_name,result)
            self.text_area.progress_bar.setVisible(False)  # 隐藏进度条
        except Exception as e:
            print(f"Error running model: {e}")


class ui_interface_lunch(ui_model_lunch):
    def __init__(self, models_parameters, text_area):
        super().__init__(models_parameters, text_area)
        self.models_parameters = models_parameters
        self.text_area = text_area

    def _run(self):
        try:
            self.text_area.model = interface_generate(
                self.models_parameters[common_const.interface_api_key],
                self.models_parameters[common_const.interface_base_url],
                self.models_parameters[common_const.interface_model_name],
                self.models_parameters[common_const.interface_type],
                self.models_parameters[common_const.interface_role]
            )
            self.text_area.model.pipeline_question()
            self.text_area.set_model_name(self.models_parameters[common_const.model_name])
        except Exception as e:
            print(f"Error loading files: {e}")


class ui_interface_run(ui_model_run):
    def __init__(self, text, model, text_area):
        super().__init__(text, model, text_area)
