from enum import Enum


class model_enum(Enum):
    model = "model"
    interface = "interface"


class interface_type_enum(Enum):
    openai = "OpenAI"
    xinghuo = "星火"


# 常量
class common_const():
    # main
    project_name = "ModelForge"
    version = "1.0.0"
    icon_dir = "icon/布莱恩.png"
    default_model_path = "model/Qwen2.5-0.5B"

    # model_parameters_setting
    max_new_tokens = 'max_new_tokens'
    do_sample = 'do_sample'
    temperature = 'temperature'
    top_k = 'top_k'
    input_max_length = 'input_max_length'
    parameters_editable = 'parameters_editable'

    # model
    interface_name = "interface_name"  # 接口名称
    interface_type = "interface_type"
    interface_model_name = "interface_model_name"
    interface_api_key = "interface_api_key"
    interface_base_url = "interface_base_url"
    interface_message_dict = "interface_message_dict"
    interface_role = "interface_role",

    interface_type_dict = [interface_type_enum.openai.value, interface_type_enum.xinghuo.value]
