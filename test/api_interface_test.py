import uvicorn

from interface.api_interface_falcon import FalconOpenAIChatCompletionResource
from interface.api_interface_fastapi import FastAPIChatCompletionResource

if __name__ == '__main__':
    # 实例化，构建应用并配置所有路由
    # resource = FastAPIChatCompletionResource()
    # # 假设在此模块中将 app 暴露为全局变量
    # app = resource.app
    # # 使用 uvicorn 的导入字符串，确保 reload 或 workers 生效
    # uvicorn.run("main:app", host="0.0.0.0", port=7783, reload=True)
    resource = FastAPIChatCompletionResource()
    resource.run()
    # app = resource.app
    # 注意这里使用导入字符串 "main:app"（假设文件名为 main.py）
    # uvicorn.run("interface.api_interface_fastapi:app", host="0.0.0.0", port=7783, reload=True)
    # interface = FalconOpenAIChatCompletionResource()
    # uvicorn.run("main:app", host="0.0.0.0", port=7783, reload=True)