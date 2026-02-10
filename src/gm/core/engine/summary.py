import logging
import os
from typing import Any, Dict, List, Optional
from langchain_core.prompts import ChatPromptTemplate
from gm.interfaces.llm import LLMPort
from gm.interfaces.external import StateManagerPort

logger = logging.getLogger("uvicorn.error")

class SummaryGenerator:
    def __init__(self, llm: LLMPort, state_client: StateManagerPort):
        self.llm, self.state_client = llm, state_client

    async def generate(self, sid: str, load_fn: Any, fetch_hist_fn: Any) -> str:
        try:
            snap = await self.state_client.get_state(sid)
            snap.update(await self.state_client.get_sequence_details(sid) or {})
            try: snap["act"] = await self.state_client.get_act_details(sid)
            except Exception: snap["act"] = {}

            entity_items = []
            for n in snap.get("npcs", []) or []: entity_items.append(f"{n.get('name') or 'NPC'}")
            for e in snap.get("enemies", []) or []: entity_items.append(f"{e.get('name') or 'Enemy'}")

            hist = await fetch_hist_fn(sid, limit=5)
            h_disp = "\n".join([f"- {h['player']} -> {h['narrative']}" for h in hist]) or "(기록 없음)"

            sys_p, usr_p = load_fn("generate_summary/system.txt"), load_fn("generate_summary/user.txt")
            res = await (ChatPromptTemplate.from_messages([("system", sys_p), ("user", usr_p)]) | self.llm).ainvoke({
                "act_name": snap.get("act", {}).get("act_name") or snap.get("current_act_id") or "Unknown",
                "sequence_name": snap.get("sequence_name", "Unknown"),
                "goal": snap.get("goal", "생존"),
                "entities": ", ".join(entity_items) or "없음",
                "entities_list": "- " + "\n- ".join(entity_items) if entity_items else "- 없음",
                "player_hp": (snap.get("player") or {}).get("hp", "?") if isinstance(snap.get("player"), dict) else "?",
                "history": h_disp,
            })
            return (res.content or "").strip() or "요약 생성 실패"
        except Exception as e:
            logger.error(f"Summary fail: {e}")
            return "상황 요약을 생성하는 도중 오류가 발생했습니다." if "LLM Error" in str(e) else "현재 상황을 파악할 수 없습니다."
