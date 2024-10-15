# coding: utf-8
import json

import requests
# 导入SDK，发起请求
from openai import OpenAI


def get_response():
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



def get_http_stream_response():
    url = "https://spark-api-open.xf-yun.com/v1/chat/completions"
    data = {
        "model": "general",  # 指定请求的模型
        "messages": [
            {
                "role": "user",
                "content": "你是谁"
            }
        ],
        "stream": True
    }
    header = {
        "Authorization": "Bearer 3e1295178045e81ac519b8e3477e95d5:OTU3MjNkMmIxZTYzOTY5NWVmZDRjMzA3"
        # 注意此处替换自己的key和secret
    }
    response = requests.post(url, headers=header, json=data, stream=True)
    # 流式响应解析示例
    response.encoding = "utf-8"
    print(response)
    for line in response.iter_lines(decode_unicode="utf-8"):
        print(line)


if __name__ == "__main__":
    # main(
    #     appid="bcc8f86a",
    #     api_secret="OTU3MjNkMmIxZTYzOTY5NWVmZDRjMzA3",
    #     api_key="3e1295178045e81ac519b8e3477e95d5",
    #     # appid、api_secret、api_key三个服务认证信息请前往开放平台控制台查看（https://console.xfyun.cn/services/bm35）
    #     gpt_url="wss://spark-api.xf-yun.com/v1.1/chat",  # Max环境的地址
    #     # Spark_url = "ws://spark-api.xf-yun.com/v3.1/chat"  # Pro环境的地址
    #     # Spark_url = "ws://spark-api.xf-yun.com/v1.1/chat"  # Lite环境的地址
    #     # domain="generalv3.5",     # Max版本
    #     # domain = "generalv3"    # Pro版本
    #     domain="general",  # Lite版本址
    #     query="给我写一篇100字的作文"
    # )
    get_http_response()
