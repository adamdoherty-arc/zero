"""
Zero Personal Assistant API Routes.

This module defines the RESTful API endpoints for the Zero Personal Assistant.
It handles user interactions, task management, and system status.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from zero.services import TaskService, UserService
from zero.models import Task, User

router = APIRouter()

class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    priority: int = 1

class TaskResponse(BaseModel):
    id: int
    title: str
    description: Optional[str]
    priority: int
    is_completed: bool

    class Config:
        from_attributes = True

class UserResponse(BaseModel):
    id: int
    name: str
    email: str

    class Config:
        from_attributes = True

@router.post("/tasks", response_model=TaskResponse, summary="Create a new task")
async def create_task(task: TaskCreate) -> TaskResponse:
    """
    Create a new task in the system.

    Args:
        task: A TaskCreate model containing the task details.

    Returns:
        TaskResponse: The created task with its assigned ID and default values.
    """
    try:
        service = TaskService()
        created_task = service.create_task(task.title, task.description, task.priority)
        return TaskResponse(
            id=created_task.id,
            title=created_task.title,
            description=created_task.description,
            priority=created_task.priority,
            is_completed=created_task.is_completed,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/tasks", response_model=List[TaskResponse], summary="Get all tasks")
async def get_tasks() -> List[TaskResponse]:
    """
    Retrieve all tasks from the system.

    Returns:
        List[TaskResponse]: A list of all tasks, sorted by creation date.
    """
    try:
        service = TaskService()
        tasks = service.get_all_tasks()
        return [
            TaskResponse(
                id=task.id,
                title=task.title,
                description=task.description,
                priority=task.priority,
                is_completed=task.is_completed,
            )
            for task in tasks
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/tasks/{task_id}", response_model=TaskResponse, summary="Get a task by ID")
async def get_task(task_id: int) -> TaskResponse:
    """
    Retrieve a specific task by its ID.

    Args:
        task_id: The unique identifier of the task.

    Returns:
        TaskResponse: The task details if found.

    Raises:
        HTTPException: 404 if the task is not found.
    """
    try:
        service = TaskService()
        task = service.get_task_by_id(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return TaskResponse(
            id=task.id,
            title=task.title,
            description=task.description,
            priority=task.priority,
            is_completed=task.is_completed,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/tasks/{task_id}", response_model=dict, summary="Delete a task")
async def delete_task(task_id: int) -> dict:
    """
    Delete a task by its ID.

    Args:
        task_id: The unique identifier of the task to delete.

    Returns:
        dict: A message confirming the deletion.

    Raises:
        HTTPException: 404 if the task is not found.
    """
    try:
        service = TaskService()
        deleted = service.delete_task(task_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"message": "Task deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/users", response_model=UserResponse, summary="Register a new user")
async def register_user(user_data: dict) -> UserResponse:
    """
    Register a new user in the system.

    Args:
        user_data: A dictionary containing 'name' and 'email' keys.

    Returns:
        UserResponse: The registered user with their assigned ID.
    """
    try:
        service = UserService()
        user = service.register_user(user_data["name"], user_data["email"])
        return UserResponse(
            id=user.id,
            name=user.name,
            email=user.email,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/users", response_model=List[UserResponse], summary="Get all users")
async def get_users() -> List[UserResponse]:
    """
    Retrieve all registered users.

    Returns:
        List[UserResponse]: A list of all users.
    """
    try:
        service = UserService()
        users = service.get_all_users()
        return [
            UserResponse(id=user.id, name=user.name, email=user.email)
            for user in users
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/health", response_model=dict, summary="Health check endpoint")
async def health_check() -> dict:
    """
    Check the health status of the API.

    Returns:
        dict: A dictionary with 'status' and 'uptime' keys.
    """
    return {"status": "healthy", "uptime": "0.0s"}
