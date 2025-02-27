from PySide6.QtCore import QRunnable

from common.const.common_const import common_const, model_enum
from pytorch.interface_generate import interface_generate
from pytorch.model_generate import model_generate


# 基类
class BaseRunnable(QRunnable):
    def __init__(self, text_area):
        super().__init__()
        self.text_area = text_area

    def run(self):
        self._run()

    def _run(self):
        pass


# 模型加载基类
class ui_model_lunch(BaseRunnable):
    def __init__(self, models_parameters, text_area):
        super().__init__(text_area)
        self.models_parameters = models_parameters

    def _run(self):
        if self.models_parameters[common_const.model_type] == model_enum.model.model:
            ui_local_model_lunch(self.models_parameters, self.text_area)._run()
        elif self.models_parameters[common_const.model_type] == model_enum.interface.interface:
            ui_interface_lunch(self.models_parameters, self.text_area)._run()

        self.set_model_parameters()

    def set_model_parameters(self):
        self.text_area.model.pipeline_question()
        self.text_area.set_model_name(self.models_parameters[common_const.model_name])

    def stop_model(self):
        if self.text_area.model:
            self.text_area.model.release_resources()
            self.text_area.progress_bar.setVisible(False)  # 隐藏进度条
            self.text_area.print("模型已停止")


class ui_local_model_lunch(ui_model_lunch):
    def __init__(self, models_parameters, text_area):
        super().__init__(models_parameters, text_area)
        self.models_parameters = models_parameters

    def _run(self):
        try:
            self.text_area.model = model_generate(
                self.models_parameters[common_const.model_path],
                self.models_parameters[common_const.max_tokens],
                self.models_parameters[common_const.do_sample],
                self.models_parameters[common_const.temperature],
                self.models_parameters[common_const.top_k],
                self.models_parameters[common_const.input_max_length],
                self.models_parameters[common_const.interface_message_dict],
                self.models_parameters[common_const.repetition_penalty],
                self.models_parameters[common_const.is_deepSeek],
                self.models_parameters[common_const.online_search],
            )
        except Exception as e:
            print(f"Error loading files: {e}")


class ui_interface_lunch(ui_model_lunch):
    def __init__(self, models_parameters, text_area):
        super().__init__(models_parameters, text_area)
        self.models_parameters = models_parameters

    def _run(self):
        try:
            self.text_area.model = interface_generate(
                self.models_parameters[common_const.interface_api_key],
                self.models_parameters[common_const.interface_base_url],
                self.models_parameters[common_const.model_type_name],
                self.models_parameters[common_const.interface_type],
                self.models_parameters[common_const.interface_role],
                self.models_parameters[common_const.temperature],
                self.models_parameters[common_const.top_p],
                self.models_parameters[common_const.top_n],
                self.models_parameters[common_const.max_tokens],
                self.models_parameters[common_const.presence_penalty],
                self.models_parameters[common_const.frequency_penalty],
                self.models_parameters[common_const.timeout],
                self.models_parameters[common_const.interface_message_dict]
            )
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
            self.text_area.append_model(self.model.model_name, result)
            self.text_area.progress_bar.setVisible(False)  # 隐藏进度条
        except Exception as e:
            print(f"Error running model: {e}")
