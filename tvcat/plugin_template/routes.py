"""
TVCat 2 Plugin Template - Routes
Ejemplo de endpoints para un plugin
"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/api/plugin/hello")
async def hello():
    return {"message": "Hello from plugin!"}
