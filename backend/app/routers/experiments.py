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
    result = await svc.run_experiment(exp_id)
    if result is None:
        # RSN-NEW1: the row can be deleted while the run is in flight; every
        # terminal path of run_experiment re-reads it and returns None in that
        # case. Serializing None under response_model=Experiment is a 500
        # ResponseValidationError — surface the vanished row as a 404 instead,
        # mirroring the RSN-5 council guard and the GET route below.
        raise HTTPException(404, f"Experiment {exp_id} deleted while running")
    return result


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
