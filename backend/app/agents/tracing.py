from ..database import AsyncSessionLocal
from ..models import Trace


async def save_trace(owner_id: int, request_text: str, agent_used: str, steps: list[dict]) -> None:
    async with AsyncSessionLocal() as session:
        session.add(
            Trace(
                owner_id=owner_id,
                request_text=request_text,
                agent_used=agent_used,
                steps=steps,
            )
        )
        await session.commit()
