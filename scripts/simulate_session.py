import asyncio
import json

import httpx

BASE_URL = "http://localhost:8020"
SESSION_ID = "debug_session_v2"


async def run_simulation():
    async with httpx.AsyncClient(timeout=60.0) as client:
        print(f"🔹 Starting Korean Simulation for Session: {SESSION_ID}")

        # 1. Player Action (Triggers NPC Turn automatically)
        print("\n▶ Player Turn 1: 장비 점검")
        resp = await client.post(
            f"{BASE_URL}/api/v1/game/turn",
            json={
                "session_id": SESSION_ID,
                "content": (
                    "나는 내 장비를 점검하고 어둠 속에서 움직임이 있는지 살핀다."
                ),
            },
        )
        print(f"   Response: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"   [Player Narrative]: {data.get('narrative')}")

            npc_data = data.get("npc_turn")
            if npc_data:
                print(
                    (
                        f"   [NPC Narrative ({npc_data.get('active_entity_id')} )]: "
                        f"{npc_data.get('narrative')}"
                    )
                )

        # 2. Player Action (Triggers NPC Turn automatically)
        print("\n▶ Player Turn 2: 소리 나는 곳으로 접근")
        resp = await client.post(
            f"{BASE_URL}/api/v1/game/turn",
            json={
                "session_id": SESSION_ID,
                "content": "나는 무기를 든 채 소리가 나는 곳으로 조심스럽게 다가간다.",
            },
        )
        print(f"   Response: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"   [Player Narrative]: {data.get('narrative')}")

            npc_data = data.get("npc_turn")
            if npc_data:
                print(
                    (
                        f"   [NPC Narrative ({npc_data.get('active_entity_id')} )]: "
                        f"{npc_data.get('narrative')}"
                    )
                )

        # 3. Fetch Full History
        print("\n📜 세션 전체 히스토리 조회...")
        resp = await client.get(f"{BASE_URL}/api/v1/game/history/{SESSION_ID}")
        if resp.status_code == 200:
            history = resp.json()
            print(json.dumps(history, indent=2, ensure_ascii=False))
        else:
            print(f"❌ Failed to fetch history: {resp.status_code}")


if __name__ == "__main__":
    asyncio.run(run_simulation())
