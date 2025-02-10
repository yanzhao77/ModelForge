import json
import random
from http import HTTPStatus
import dashscope
from openai import OpenAI
import requests
from zhipuai import ZhipuAI

dashscope.api_key = "sk-3f2d7473809f4f0492976b33f3146299"


def call_with_messages():
    messages = [
        {'role': 'user', 'content': '用萝卜、土豆、茄子做饭，给我个菜谱'}]
    response = dashscope.Generation.call(
        'qwen1.5-0.5b-chat',
        messages=messages,
        # set the random seed, optional, default to 1234 if not set
        seed=random.randint(1, 10000),
        result_format='message',  # set the result to be "message" format.
    )
    if response.status_code == HTTPStatus.OK:
        print(response)
    else:
        print('Request id: %s, Status code: %s, error code: %s, error message: %s' % (
            response.request_id, response.status_code,
            response.code, response.message
        ))


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
                "content": '说一个程序员才懂的笑话'
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

def get_glm_4_free():
    client = OpenAI(
        # 控制台获取key和secret拼接，假使控制台获取的APIPassword是123456
        api_key="lENFVHvOGLIGcTBkZROk:sLkBPDgAFbjqlpDgNRll",
        base_url='https://spark-api-open.xf-yun.com/v1'  # 指向讯飞星火的请求地址
    )
    completion = client.chat.completions.create(
        model='generalv3.5',  # 指定请求的版本
        messages=[
            {"role": "system", "content": "你是一个聪明且富有创造力的小说作家"},
            {"role": "user", "content": "请你作为童话故事大王，写一篇短篇童话故事，故事的主题是要永远保持一颗善良的心。"}
        ],
        top_p=0.7,
        temperature=0.9
    )
    print(completion.choices[0].message)


def get_glm_4_2_response():
    client = ZhipuAI(api_key="0d62ab35210808d52040993cd53788a5.NrIcZR8TpXjbUwrz")  # 请填写您自己的APIKey
    response = client.chat.completions.create(
        model="glm-4-flash",  # 请填写您要调用的模型名称
        messages=[
            {"role": "user", "content": "说一个程序员才懂的笑话"}
        ],
    )
    print(response.choices[0].message)

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
    stream = False
    )
    print(completion.choices[0].message)

def get_deepseek1():
    # Please install OpenAI SDK first: `pip3 install openai`
    client = OpenAI(api_key="sk-d0072ee63cc14e82be849eb5f92d8c63", base_url="https://api.deepseek.com")
    response = client.chat.completions.create(
        model="deepseek-chat",
        # model="deepseek-reasoner",
        messages=[
            {"role": "system", "content": "你是一位历史学专家，用户将提供一系列问题，你的回答应当简明扼要，并以`Answer:`开头"},
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

if __name__ == '__main__':
    # call_with_messages()
    # get_response()
    get_glm_4_free()
