from sqlalchemy.ext.asyncio import AsyncSession
from zero.database.session import get_async_session
from fastapi import Depends
from typing import Annotated

async def create_audit_record(
    db: Annotated[AsyncSession, Depends(get_async_session)],
    data: dict
):
    # Example operation using a fresh session
    db.add(AuditModel(**data))
    await db.commit()
    return {"status": "success"}