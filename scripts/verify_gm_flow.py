import argparse
import asyncio

import httpx


async def verify_gm_flow(base_url: str, session_id: str):
    print(f"--- Verifying GM Flow at {base_url} ---")
    print(f"Session ID: {session_id}\n")

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Health Check
        try:
            health_resp = await client.get(f"{base_url}/health")
            print(f"Health Check: {health_resp.status_code} {health_resp.json()}")
        except Exception as e:
            print(f"Health Check Failed: {e}")
            return

        # 2. Start Game Turn (Player)
        print("\n[Step 1] Sending Player Action...")
        payload = {
            "session_id": session_id,
            "content": "어두운 동굴 안으로 조심스럽게 들어간다.",
        }

        try:
            resp = await client.post(f"{base_url}/api/v1/game/turn", json=payload)
            if resp.status_code != 200:
                print(f"Error: {resp.status_code}\n{resp.text}")
                return

            data = resp.json()
            print(f"✔ Turn Processed (ID: {data.get('turn_id')})")
            print(f"   Narrative: {data.get('narrative')}")
            print(f"   Commit ID: {data.get('commit_id')}")

            # 3. Verify NPC Turn auto-execution
            npc_turn = data.get("npc_turn")
            if npc_turn:
                t_id = npc_turn.get("turn_id")
                print(f"\n✔ NPC Turn Automatically Triggered (ID: {t_id})")
                print(f"   Actor: {npc_turn.get('active_entity_id')}")
                print(f"   Narrative: {npc_turn.get('narrative')}")
            else:
                print("\n⚠ NPC Turn was not found in response.")

        except Exception as e:
            print(f"Failed to process turn: {e}")
            return

        # 4. Check Session History
        print("\n[Step 2] Fetching Session History...")
        try:
            hist_resp = await client.get(f"{base_url}/api/v1/game/history/{session_id}")
            if hist_resp.status_code == 200:
                history = hist_resp.json()
                print(f"✔ History Count: {len(history)}")
                for entry in history[-2:]:
                    active_entity = entry.get("active_entity_id", "player")
                    u_in = entry.get("user_input", "")[:30]
                    f_out = entry.get("final_output", "")[:30]
                    role = "NPC" if active_entity.lower() != "player" else "Player"
                    print(f"   [{role} ({active_entity})] {u_in}... -> {f_out}...")
            else:
                print(f"Failed to fetch history: {hist_resp.status_code}")
        except Exception as e:
            print(f"History Fetch Failed: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GM Flow Verification Script")
    parser.add_argument(
        "--url", default="http://localhost:8020", help="Base URL of the GM service"
    )
    parser.add_argument(
        "--session", default="verify-session-001", help="Session ID to use"
    )

    args = parser.parse_args()

    asyncio.run(verify_gm_flow(args.url, args.session))
