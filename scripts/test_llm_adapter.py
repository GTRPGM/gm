import asyncio

import httpx
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from gm.core.config import settings
from gm.plugins.llm.adapter import NarrativeChatModel


class ActionSchema(BaseModel):
    action: str
    target: str


async def main():
    url = settings.LLM_GATEWAY_URL

    async with httpx.AsyncClient(base_url=url, timeout=60.0) as client:
        model = NarrativeChatModel(base_url=url, client=client)

        prompt = 'NPC의 다음 행동을 출력해줘.'
        messages = [HumanMessage(content=prompt)]

        # --- Test 1: basic invoke ---
        print("\n[Test1] basic invoke")
        res = await model.ainvoke(messages)
        print("OK" if isinstance(res.content, str) else "FAIL")

        # --- Test 2: response_format structured ---
        print("\n[Test2] response_format structured")
        res = await model.ainvoke(messages, response_format={"type": "json_object"})
        print("OK" if isinstance(res.content, (dict, list)) else "FAIL")

        # --- Test 3: with_structured_output ---
        print("\n[Test3] with_structured_output")
        structured = model.with_structured_output(ActionSchema)
        res = await structured.ainvoke(messages)
        print("OK" if isinstance(res, ActionSchema) else "FAIL")


if __name__ == "__main__":
    asyncio.run(main())
