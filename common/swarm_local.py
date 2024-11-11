from openai import OpenAI
from swarm import Swarm


class Swarm_local(Swarm):
    def __init__(self, client=None):
        self.local_model = 'general'  # 指定请求的版本
        self.local_api_key = "lENFVHvOGLIGcTBkZROk:sLkBPDgAFbjqlpDgNRll"
        self.local_base_url = 'https://spark-api-open.xf-yun.com/v1'
        if not client:
            client = OpenAI(
                # 控制台获取key和secret拼接，假使控制台获取的APIPassword是123456
                api_key=self.local_api_key,
                base_url=self.local_base_url,  # 指向讯飞星火的请求地址
            )
        super().__init__(client)

    def run(self, *args, **kwargs):
        model_override = kwargs.pop('model_override', None)
        if model_override:
            kwargs['agent'].model = model_override
        return super().run(*args, **kwargs)
