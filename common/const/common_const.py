from enum import Enum


# 常量
class common_const(Enum):
    project_name = "ModelForge"
    version = "1.0.0"
    icon_dir = "icon/布莱恩.png"
    default_model_path = "model/Qwen2.5-0.5B"


class model_enum(Enum):
    model = "model"
    interface = "interface"
