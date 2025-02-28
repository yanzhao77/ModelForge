import os
from enum import Enum


class model_enum(Enum):
    model = "model"
    interface = "interface"


class interface_type_enum(Enum):
    openai = "OpenAI"
    xinghuo = "星火"

class interface_xinghuo_enum(Enum):
    model_name = "Spark Lite"
    model_type_name = 'general'
    interface_type = 'OpenAI'
    api_key = "lENFVHvOGLIGcTBkZROk:sLkBPDgAFbjqlpDgNRll"
    base_url = 'https://spark-api-open.xf-yun.com/v1'  # 指向讯飞星火的请求地址


# 常量
class common_const():
    # main
    project_name = "ModelForge"
    version = "1.0.0"
    icon_main_view = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'icon/logo.ico')
    transition_main_view = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'icon/android-chrome-512x512.png')
    transition_main_gif = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'icon/guys/神经网络编织.gif')
    icon_clouds_view = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'icon/treeview/clouds.ico')
    icon_model_view = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'icon/treeview/model.ico')
    icon_tree_model_view = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'icon/treeview/tree_model.ico')

    default_model_name = "DeepSeek-R1-Distill-Qwen-1.5B"
    default_model_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'model')

    # model_parameters_setting
    max_tokens = 'max_tokens'
    do_sample = 'do_sample'
    temperature = 'temperature'
    top_k = 'top_k'
    top_p = 'top_p'
    top_n = 'top_n'
    timeout = "timeout"
    input_max_length = 'input_max_length'
    parameters_editable = 'parameters_editable'
    repetition_penalty = "repetition_penalty"
    presence_penalty = "presence_penalty"
    frequency_penalty = "frequency_penalty"

    is_deepSeek = "is_deepSeek"
    online_search = "online_search"

    # model
    model_name = "model_name"
    model_type_name = "model_type_name"
    model_path = "model_path"
    model_type = "model_type"

    interface_type = "interface_type"
    interface_api_key = "interface_api_key"
    interface_base_url = "interface_base_url"

    interface_COLUMN_HEADERS = ["接口名称", "接口类型", "模型名称", "API Key", "Base URL"]

    interface_role = "interface_role",
    interface_message_dict = "interface_message_dict"

    interface_type_dict = [interface_type_enum.openai.value]
