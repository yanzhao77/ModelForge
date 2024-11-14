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
    icon_main_view = "icon/logo.ico"
    icon_clouds_view = "icon/treeview/clouds.ico"
    icon_model_view = "icon/treeview/model.ico"
    icon_tree_model_view = "icon/treeview/tree_model.ico"


    default_model_path = "model/Qwen2.5-0.5B"

    # model_parameters_setting
    max_new_tokens = 'max_new_tokens'
    do_sample = 'do_sample'
    temperature = 'temperature'
    top_k = 'top_k'
    input_max_length = 'input_max_length'
    parameters_editable = 'parameters_editable'

    # model
    model_name = "model_name"
    model_path = "model_path"
    model_type = "model_type"

    interface_type = "interface_type"
    interface_model_name = "interface_model_name"
    interface_api_key = "interface_api_key"
    interface_base_url = "interface_base_url"

    interface_temperature = "interface_temperature"
    interface_top_p = "interface_top_p"
    interface_n = "interface_n"
    interface_max_tokens = "interface_max_tokens"
    interface_presence_penalty = "interface_presence_penalty"
    interface_frequency_penalty = "interface_frequency_penalty"
    interface_timeout = "interface_timeout"

    interface_COLUMN_HEADERS = ["接口名称", "接口类型", "模型名称", "API Key", "Base URL"]

    interface_role = "interface_role",
    interface_message_dict = "interface_message_dict"

    interface_type_dict = [interface_type_enum.openai.value]
