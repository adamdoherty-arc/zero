"""Vision processing API."""
from fastapi import APIRouter, UploadFile, File
from typing import Optional

router = APIRouter()


@router.get("/describe")
async def describe_scene(prompt: str = "Describe what you see."):
    from app.services.vision_service import get_vision_service
    return await get_vision_service().capture_and_describe(prompt)


@router.post("/describe")
async def describe_uploaded(file: UploadFile = File(...), prompt: str = "Describe what you see."):
    from app.services.vision_service import get_vision_service
    image_bytes = await file.read()
    return await get_vision_service().describe_image(image_bytes, prompt)


@router.get("/presence")
async def detect_presence():
    from app.services.vision_service import get_vision_service
    return await get_vision_service().detect_presence()
