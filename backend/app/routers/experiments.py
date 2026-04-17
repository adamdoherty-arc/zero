"""
Experiments Router.
REST API for designing, running, and viewing experiments.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.infrastructure.auth import require_auth
from app.models.agent_company import Experiment, ExperimentCreate
from app.services.experiment_service import get_experiment_service

router = APIRouter(prefix="/api/experiments", tags=["experiments"], dependencies=[Depends(require_auth)])


@router.post("", response_model=Experiment, status_code=201)
async def design_experiment(req: ExperimentCreate):
    """CEO designs experiment methodology from a hypothesis."""
    svc = get_experiment_service()
    return await svc.design_experiment(req)


@router.post("/{exp_id}/run", response_model=Experiment)
async def run_experiment(exp_id: str):
    """Execute an experiment."""
    svc = get_experiment_service()
    exp = await svc.get_experiment(exp_id)
    if not exp:
        raise HTTPException(404, f"Experiment {exp_id} not found")
    return await svc.run_experiment(exp_id)


@router.get("", response_model=list[Experiment])
async def list_experiments(status: Optional[str] = None, exp_type: Optional[str] = None, limit: int = 20):
    svc = get_experiment_service()
    return await svc.list_experiments(status=status, exp_type=exp_type, limit=limit)


@router.get("/{exp_id}", response_model=Experiment)
async def get_experiment(exp_id: str):
    svc = get_experiment_service()
    exp = await svc.get_experiment(exp_id)
    if not exp:
        raise HTTPException(404, f"Experiment {exp_id} not found")
    return exp
