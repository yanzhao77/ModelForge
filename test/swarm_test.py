from swarm import Agent

from test.swarm_local import Swarm_local


class local_Agent_test1():
    def __init__(self, client: Swarm_local):
        self.client = client

    def transfer_to_agent_b(self):
        return self.agent_b

    agent_a = Agent(
        name="Agent A",
        instructions="You are a helpful agent.",
        functions=[transfer_to_agent_b]
    )
    agent_b = Agent(
        name="Agent B",
        instructions="Only speak in Haikus.",
    )

    def response(self):
        return self.client.run(
            model_override=self.client.local_model,
            agent=self.agent_a,
            messages=[{"role": "user", "content": "I want to talk to agent B."}],
        )


class local_Agent_test2():
    def __init__(self, client: Swarm_local):
        self.client = client

    def transfer_to_agent_b(self):
        return self.agent_b

    agent_a = Agent(name="Agent A", instructions="你是一个有用的助手")
    agent_b = Agent(name="Agent B", instructions="仅仅使用繁体字说话")

    def response(self):
        return self.client.run(agent=self.agent_a, messages=[{"role": "user", "content": "我想和Agent B说话"}], )

    def print(self):
        print("User和AgentA说: 我想和Agent B说话。")

        print("Agent：", self.response().messages[-1]["content"])


if __name__ == '__main__':
    client = Swarm_local()
    local_Agent_test = local_Agent_test2(client)

    local_Agent_test.print()
    # print(local_Agent_test.response().messages[-1]["content"])
