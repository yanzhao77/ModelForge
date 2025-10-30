import json
import random
from http import HTTPStatus
from openai import OpenAI
import requests


# dashscope.api_key = "sk-3f2d7473809f4f0492976b33f3146299"
#
#
# def call_with_messages():
#     messages = [
#         {'role': 'user', 'content': '用萝卜、土豆、茄子做饭，给我个菜谱'}]
#     response = dashscope.Generation.call(
#         'qwen1.5-0.5b-chat',
#         messages=messages,
#         # set the random seed, optional, default to 1234 if not set
#         seed=random.randint(1, 10000),
#         result_format='message',  # set the result to be "message" format.
#     )
#     if response.status_code == HTTPStatus.OK:
#         print(response)
#     else:
#         print('Request id: %s, Status code: %s, error code: %s, error message: %s' % (
#             response.request_id, response.status_code,
#             response.code, response.message
#         ))


def get_response():
    client = OpenAI(
        api_key='sk-3f2d7473809f4f0492976b33f3146299',  # 如果您没有配置环境变量，请在此处用您的API Key进行替换
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",  # 填写DashScope SDK的base_url
    )
    completion = client.chat.completions.create(
        model="qwen1.5-0.5b-chat",
        messages=[{'role': 'system', 'content': 'You are a helpful assistant.'},
                  {'role': 'user', 'content': '你能做什么'}]
    )
    print(completion.model_dump_json())


def get_spark_response():
    client = OpenAI(
        # 控制台获取key和secret拼接，假使控制台获取的APIPassword是123456
        api_key="lENFVHvOGLIGcTBkZROk:sLkBPDgAFbjqlpDgNRll",
        base_url='https://spark-api-open.xf-yun.com/v1'  # 指向讯飞星火的请求地址
    )
    completion = client.chat.completions.create(
        model='general',  # 指定请求的版本
        messages=[
            {
                "role": "user",
                "content": '你是谁？你是哪个版本的模型'
            }
        ]
    )
    print(completion.choices[0].message)


def get_http_response():
    url = "https://spark-api-open.xf-yun.com/v1/chat/completions"
    data = {
        "model": "general",  # 指定请求的模型
        "messages": [
            {
                "role": "user",
                "content": "你是谁"
            }
        ]
    }
    header = {
        "Authorization": "Bearer 3e1295178045e81ac519b8e3477e95d5:OTU3MjNkMmIxZTYzOTY5NWVmZDRjMzA3"
        # 注意此处替换自己的key和secret
    }
    response = requests.post(url, headers=header, json=data)
    # 流式响应解析示例
    response.encoding = "utf-8"
    result_dict = json.loads(response.text)['choices'][0]['message']
    result_content = result_dict['content']
    print(result_content)


def get_glm_4_response():
    client = OpenAI(
        # 控制台获取key和secret拼接，假使控制台获取的APIPassword是123456
        api_key="0d62ab35210808d52040993cd53788a5.NrIcZR8TpXjbUwrz",
        base_url='https://open.bigmodel.cn/api/paas/v4/'  # 指向讯飞星火的请求地址
    )
    completion = client.chat.completions.create(
        model='glm-4-flash',  # 指定请求的版本
        messages=[
            {"role": "system", "content": "你是一个聪明且富有创造力的小说作家"},
            {"role": "user", "content": "请你作为童话故事大王，写一篇短篇童话故事，故事的主题是要永远保持一颗善良的心。"}
        ],
        top_p=0.7,
        temperature=0.9
    )
    print(completion.choices[0].message)


def deeget_glm_4_free():
    client = OpenAI(
        # 控制台获取key和secret拼接，假使控制台获取的APIPassword是123456
        api_key="lENFVHvOGLIGcTBkZROk:sLkBPDgAFbjqlpDgNRll",
        base_url='https://spark-api-open.xf-yun.com/v1'  # 指向讯飞星火的请求地址
    )
    completion = client.chat.completions.create(
        model='general',  # 指定请求的版本
        messages=[
            {"role": "system", "content": "你是一个聪明且富有创造力的小说作家"},
            {"role": "user", "content": "请你作为童话故事大王，写一篇短篇童话故事，故事的主题是要永远保持一颗善良的心。"}
        ],
        top_p=0.7,
        temperature=0.9
    )
    print(completion.choices[0].message)


# def get_glm_4_2_response():
#     client = ZhipuAI(api_key="0d62ab35210808d52040993cd53788a5.NrIcZR8TpXjbUwrz")  # 请填写您自己的APIKey
#     response = client.chat.completions.create(
#         model="glm-4-flash",  # 请填写您要调用的模型名称
#         messages=[
#             {"role": "user", "content": "说一个程序员才懂的笑话"}
#         ],
#     )
#     print(response.choices[0].message)


def get_deepseek():
    client = OpenAI(
        # 控制台获取key和secret拼接，假使控制台获取的APIPassword是123456
        api_key="sk-9079b4507d3943a299487270de3055f4",
        base_url='https://api.deepseek.com'  # 指向讯飞星火的请求地址
    )
    completion = client.chat.completions.create(
        model="deepseek-chat",  # 指定请求的版本
        messages=[
            {
                "role": "user",
                "content": '说一个程序员才懂的笑话'
            }
        ],
        stream=False
    )
    print(completion.choices[0].message)


def get_deepseek1():
    # Please install OpenAI SDK first: `pip3 install openai`
    client = OpenAI(api_key="sk-d0072ee63cc14e82be849eb5f92d8c63", base_url="https://api.deepseek.com")
    response = client.chat.completions.create(
        model="deepseek-chat",
        # model="deepseek-reasoner",
        messages=[
            {"role": "system",
             "content": "你是一位历史学专家，用户将提供一系列问题，你的回答应当简明扼要，并以`Answer:`开头"},
            {"role": "user", "content": "请问秦始皇统一六国是在哪一年？"},
            {"role": "assistant", "content": "Answer:公元前221年"},
            {"role": "user", "content": "请问汉朝的建立者是谁？"},
            {"role": "assistant", "content": "Answer:刘邦"},
            {"role": "user", "content": "请问唐朝最后一任皇帝是谁"},
            {"role": "assistant", "content": "Answer:李柷"},
            {"role": "user", "content": "请问明朝的开国皇帝是谁？"},
            {"role": "assistant", "content": "Answer:朱元璋"},
            {"role": "user", "content": "请问商朝是什么时候灭亡的"},
        ],
        stream=False
    )
    print(response.choices[0].message.content)


def xinghuo():
    client = OpenAI(
        # 控制台获取key和secret拼接，假使控制台获取的APIPassword是123456
        # api_key="lENFVHvOGLIGcTBkZROk:sLkBPDgAFbjqlpDgNRll",
        api_key="GjbdckSJbPhzZrISUUeL:gWVwFNweCUyBUthigoXN",
        base_url='https://spark-api-open.xf-yun.com/v1/chat/completions'  # 指向讯飞星火的请求地址
    )
    completion = client.chat.completions.create(
        model='Spark4.0 Ultra',  # 指定请求的版本
        messages=[
            {
                "role": "user",
                "content": '说一个程序员才懂的笑话'
            }
        ]
    )
    print(completion.choices[0].message)


def qwq_32b():
    # 初始化OpenAI客户端
    client = OpenAI(
        # 如果没有配置环境变量，请用百炼API Key替换：api_key="sk-xxx"
        api_key="sk-3c4575995aab473789a617d0f23fccf7",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )

    reasoning_content = ""  # 定义完整思考过程
    answer_content = ""  # 定义完整回复
    is_answering = False  # 判断是否结束思考过程并开始回复

    # 创建聊天完成请求
    completion = client.chat.completions.create(
        model="qwq-32b",  # 此处以 qwq-32b 为例，可按需更换模型名称
        messages=[
            {"role": "user", "content": "9.9和9.11谁大"}
        ],
        stream=True,
        # 解除以下注释会在最后一个chunk返回Token使用量
        stream_options={
            "include_usage": True
        }
    )

    print("\n" + "=" * 20 + "思考过程" + "=" * 20 + "\n")

    for chunk in completion:
        # 如果chunk.choices为空，则打印usage
        if not chunk.choices:
            print("\nUsage:")
            print(chunk.usage)
        else:
            delta = chunk.choices[0].delta
            # 打印思考过程
            if hasattr(delta, 'reasoning_content') and delta.reasoning_content != None:
                print(delta.reasoning_content, end='', flush=True)
                reasoning_content += delta.reasoning_content
            else:
                # 开始回复
                if delta.content != "" and is_answering is False:
                    print("\n" + "=" * 20 + "完整回复" + "=" * 20 + "\n")
                    is_answering = True
                # 打印回复过程
                print(delta.content, end='', flush=True)
                answer_content += delta.content

    print("=" * 20 + "完整思考过程" + "=" * 20 + "\n")
    print(reasoning_content)
    print("=" * 20 + "完整回复" + "=" * 20 + "\n")
    print(answer_content)


def qwq_32b_2():
    from openai import OpenAI
    import os

    # 初始化OpenAI客户端
    client = OpenAI(
        # 如果没有配置环境变量，请用百炼API Key替换：api_key="sk-xxx"
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )

    reasoning_content = ""  # 定义完整思考过程
    answer_content = ""  # 定义完整回复
    is_answering = False  # 判断是否结束思考过程并开始回复

    messages = []
    conversation_idx = 1
    while True:
        print("=" * 20 + f"第{conversation_idx}轮对话" + "=" * 20)
        conversation_idx += 1
        user_msg = {"role": "user", "content": input("请输入你的消息：")}
        messages.append(user_msg)
        # 创建聊天完成请求
        completion = client.chat.completions.create(
            model="qwq-32b",  # 此处以 qwq-32b 为例，可按需更换模型名称
            messages=messages,
            stream=True
        )
        print("\n" + "=" * 20 + "思考过程" + "=" * 20 + "\n")
        for chunk in completion:
            # 如果chunk.choices为空，则打印usage
            if not chunk.choices:
                print("\nUsage:")
                print(chunk.usage)
            else:
                delta = chunk.choices[0].delta
                # 打印思考过程
                if hasattr(delta, 'reasoning_content') and delta.reasoning_content != None:
                    print(delta.reasoning_content, end='', flush=True)
                    reasoning_content += delta.reasoning_content
                else:
                    # 开始回复
                    if delta.content != "" and is_answering is False:
                        print("\n" + "=" * 20 + "完整回复" + "=" * 20 + "\n")
                        is_answering = True
                    # 打印回复过程
                    print(delta.content, end='', flush=True)
                    answer_content += delta.content
        messages.append({"role": "assistant", "content": answer_content})
        print("\n")
        # print("=" * 20 + "完整思考过程" + "=" * 20 + "\n")
        # print(reasoning_content)
        # print("=" * 20 + "完整回复" + "=" * 20 + "\n")
        # print(answer_content)


def openai():
    client = OpenAI(
        api_key="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"
    )

    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        store=True,
        messages=[
            {"role": "user", "content": "write a haiku about ai"}
        ]
    )
    print(completion.choices[0].message)

if __name__ == '__main__':
    # call_with_messages()
    # get_response()
    # get_spark_response()
    get_deepseek()