"""Zero Company Operator API.

Read and command surface for the 24/7 ADA AI LLC company operator.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.infrastructure.auth import require_auth
from app.models.task import CompanyAgentQuestionAnswer, TaskCreate, TaskUpdate
from app.services.company_operator_service import get_company_operator_service


router = APIRouter(
    prefix="/api/company/operator",
    tags=["company-operator"],
    dependencies=[Depends(require_auth)],
)


class OperatorTickRequest(BaseModel):
    run_type: str = Field(default="manual", max_length=40)
    force: bool = False
    requested_by: str = Field(default="user", max_length=100)
    target_agent_id: Optional[str] = Field(default=None, max_length=64)


class OperatorReportRequest(BaseModel):
    report_type: str = Field(default="manual", max_length=40)
    requested_by: str = Field(default="user", max_length=100)


class ApprovalCreateRequest(BaseModel):
    summary: str = Field(..., min_length=1, max_length=1000)
    tool_name: str = Field(default="company_operator_manual_approval", max_length=200)
    tier: str = Field(default="write_external", pattern="^(read|write_local|write_external|financial)$")
    arguments: dict[str, Any] = Field(default_factory=dict)
    requested_by: str = Field(default="user", max_length=100)


class AssignTaskRequest(BaseModel):
    task_id: str = Field(..., min_length=1, max_length=64)
    role_id: str = Field(..., min_length=1, max_length=64)
    requested_by: str = Field(default="user", max_length=100)


class QuestionDismissRequest(BaseModel):
    answered_by: str = Field(default="dashboard", max_length=100)


class QuestionTriageRequest(BaseModel):
    requested_by: str = Field(default="dashboard", max_length=100)
    limit: int = Field(default=200, ge=1, le=500)
    max_open: int = Field(default=25, ge=5, le=100)


class PromptEvalRequest(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)


@router.get("/status")
async def status():
    return await get_company_operator_service().status()


@router.get("/report/latest")
async def latest_report(report_type: Optional[str] = Query(default=None)):
    return await get_company_operator_service().latest_report(report_type=report_type)


@router.get("/runs")
async def runs(
    run_type: Optional[str] = Query(default=None),
    limit: int = Query(default=30, ge=1, le=200),
):
    return await get_company_operator_service().runs(run_type=run_type, limit=limit)


@router.get("/questions")
async def questions(
    status: Optional[str] = Query(default="open"),
    task_id: Optional[str] = Query(default=None),
    agent_task_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    return await get_company_operator_service().questions(
        status=status,
        task_id=task_id,
        agent_task_id=agent_task_id,
        limit=limit,
    )


@router.get("/overnight")
async def overnight():
    return await get_company_operator_service().overnight()


@router.get("/today")
async def today():
    return await get_company_operator_service().today()


@router.post("/tick")
async def run_tick(req: OperatorTickRequest):
    return await get_company_operator_service().run_tick(
        run_type=req.run_type,
        requested_by=req.requested_by,
        force=req.force,
        target_agent_id=req.target_agent_id,
    )


@router.post("/questions/triage")
async def triage_questions(req: QuestionTriageRequest | None = None):
    return await get_company_operator_service().triage_questions(
        requested_by=req.requested_by if req else "dashboard",
        limit=req.limit if req else 200,
        max_open=req.max_open if req else 25,
    )


@router.post("/prompt-eval")
async def prompt_eval(req: PromptEvalRequest | None = None):
    return await get_company_operator_service().run_prompt_eval_bridge(
        limit=req.limit if req else 20,
    )


@router.post("/questions/{question_id}/answer")
async def answer_question(question_id: str, req: CompanyAgentQuestionAnswer):
    question = await get_company_operator_service().answer_question(
        question_id,
        answer=req.answer,
        answered_by=req.answered_by,
    )
    if not question:
        raise HTTPException(404, f"Question {question_id} not found")
    return question


@router.post("/questions/{question_id}/dismiss")
async def dismiss_question(question_id: str, req: QuestionDismissRequest | None = None):
    question = await get_company_operator_service().dismiss_question(
        question_id,
        answered_by=req.answered_by if req else "dashboard",
    )
    if not question:
        raise HTTPException(404, f"Question {question_id} not found")
    return question


@router.post("/report")
async def generate_report(req: OperatorReportRequest):
    return await get_company_operator_service().generate_report(
        report_type=req.report_type,
        requested_by=req.requested_by,
    )


@router.post("/pause")
async def pause():
    return await get_company_operator_service().pause()


@router.post("/resume")
async def resume():
    return await get_company_operator_service().resume()


@router.post("/tasks")
async def create_company_task(task: TaskCreate):
    return await get_company_operator_service().create_company_task(task)


@router.patch("/tasks/{task_id}")
async def update_company_task(task_id: str, updates: TaskUpdate):
    task = await get_company_operator_service().update_company_task(task_id, updates)
    if not task:
        raise HTTPException(404, f"Task {task_id} not found")
    return task


@router.post("/approvals")
async def queue_approval(req: ApprovalCreateRequest):
    return await get_company_operator_service().queue_approval(
        summary=req.summary,
        tool_name=req.tool_name,
        tier=req.tier,
        arguments=req.arguments,
        requested_by=req.requested_by,
    )


@router.post("/assign")
async def assign(req: AssignTaskRequest):
    try:
        return await get_company_operator_service().assign_task_to_subagent(
            task_id=req.task_id,
            role_id=req.role_id,
            requested_by=req.requested_by,
        )
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
