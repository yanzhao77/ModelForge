import json
from datetime import datetime
from openai import OpenAI

client = OpenAI(
    api_key='sk-3f2d7473809f4f0492976b33f3146299',  # 如果您没有配置环境变量，请在此处用您的API Key进行替换
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",  # 填写DashScope SDK的base_url
)

# 定义工具列表，模型在选择使用哪个工具时会参考工具的name和description
tools = [
    # 工具1 获取当前时刻的时间
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "当你想知道现在的时间时非常有用。",
            "parameters": {}  # 因为获取当前时间无需输入参数，因此parameters为空字典
        }
    },
    # 工具2 获取指定城市的天气
    {
        "type": "function",
        "function": {
            "name": "get_current_weather",
            "description": "当你想查询指定城市的天气时非常有用。",
            "parameters": {  # 查询天气时需要提供位置，因此参数设置为location
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "城市或县区，比如北京市、杭州市、余杭区等。"
                    }
                }
            },
            "required": [
                "location"
            ]
        }
    }
]


# 模拟天气查询工具。返回结果示例：“北京今天是晴天。”
def get_current_weather(location):
    return f"{location}今天是雨天。"


# 查询当前时间的工具。返回结果示例：“当前时间：2024-04-15 17:15:18。“
def get_current_time():
    current_datetime = datetime.now()
    formatted_time = current_datetime.strftime('%Y-%m-%d %H:%M:%S')
    return f"当前时间：{formatted_time}。"


# 封装模型响应函数
def get_response(messages):
    completion = client.chat.completions.create(
        model="qwen-plus",
        messages=messages,
        tools=tools
    )
    return completion.model_dump()


def call_with_messages():
    print('\n')
    messages = [
        {
            "content": "杭州和北京天气怎么样？现在几点了？",
            "role": "user"
        }
    ]
    print("-" * 60)
    i = 1
    first_response = get_response(messages)
    assistant_output = first_response['choices'][0]['message']
    print(f"\n第{i}轮大模型输出信息：{first_response}\n")

    if assistant_output['content'] is None:
        assistant_output['content'] = ""
    messages.append(assistant_output)

    # 如果不需要调用工具，则直接返回最终答案
    if assistant_output.get('tool_calls') is None:
        print(f"无需调用工具，我可以直接回复：{assistant_output['content']}")
        return

    # 如果需要调用工具，则进行模型的多轮调用，直到模型判断无需调用工具
    while assistant_output.get('tool_calls'):
        tool_call = assistant_output['tool_calls'][0]
        function_name = tool_call['function']['name']
        arguments = json.loads(tool_call['function']['arguments'])  # 解析参数

        if function_name == 'get_current_weather':
            location = arguments['location']
            tool_info = {"name": "get_current_weather", "role": "tool"}
            tool_info['content'] = get_current_weather(location)
        elif function_name == 'get_current_time':
            tool_info = {"name": "get_current_time", "role": "tool"}
            tool_info['content'] = get_current_time()

        print(f"工具输出信息：{tool_info['content']}\n")
        print("-" * 60)
        messages.append(tool_info)
        assistant_output = get_response(messages)['choices'][0]['message']

        if assistant_output['content'] is None:
            assistant_output['content'] = ""
        messages.append(assistant_output)
        i += 1
        print(f"第{i}轮大模型输出信息：{assistant_output}\n")

    print(f"最终答案：{assistant_output['content']}")


if __name__ == '__main__':
    call_with_messages()