import json

from pytorch.interface_generate import interface_generate

if __name__ == '__main__':
    # def __init__(self, api_key=str, base_url=str, model_name=str, model_type=interface_type_enum.openai.value,
    #              role=str):
    # base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"  # 填写DashScope SDK的base_url
    # api_key='sk-3f2d7473809f4f0492976b33f3146299' # 如果您没有配置环境变量，请在此处用您的API Key进行替换
    # model_type = "OpenAI"
    # model_name="qwen1.5-0.5b-chat"
    # role = "user"
    #
    # value = "你好啊"
    #
    # model = interface_generate(api_key, base_url, model_name,model_type,  role)
    # model.pipeline_question()
    #
    # result = model.pipeline_answer(value)
    # print(result)

    # 定义 JSON 格式的字符串

    # 定义 JSON 格式的字符串
    a = f'{{"role": "user", "content": "你是谁"}}'
    b = f'{{"role": "assistant", "content": "我是你的助手"}}'

    # 将字符串解析为字典
    dict_a = json.loads(a)
    dict_b = json.loads(b)

    # 将字典放入元组
    tuple_ab = (dict_a, dict_b)

    # 将元组转换为 JSON 字符串
    json_string = json.dumps(tuple_ab, ensure_ascii=False, indent=4)

    # 打印结果
    print(json_string)