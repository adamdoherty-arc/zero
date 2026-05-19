from fastapi import FastAPI
from zero.services.audit_service import create_audit_record
from zero.database.session import get_async_session

app = FastAPI()

app.dependency_overrides[get_async_session] = get_async_session

@app.post("/audit")
async def audit_endpoint(data: dict):
    return await create_audit_record(data=data)