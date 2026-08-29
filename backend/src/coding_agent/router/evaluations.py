"""提供本地 benchmark 结果的只读查询接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from coding_agent.dependencies import get_evaluation_report_service
from coding_agent.schemas.evaluations import EvaluationRunListResponse, EvaluationRunResponse
from coding_agent.services import EvaluationReportService


router = APIRouter(prefix="/evaluations", tags=["evaluations"])


@router.get("", response_model=EvaluationRunListResponse)
def list_evaluations(
    service: EvaluationReportService = Depends(get_evaluation_report_service),
) -> dict[str, object]:
    """列出后端本地目录中可展示的评测运行。"""

    return {"runs": service.list_runs()}


@router.get("/{run_id}", response_model=EvaluationRunResponse)
def get_evaluation(
    run_id: str,
    service: EvaluationReportService = Depends(get_evaluation_report_service),
) -> dict[str, object]:
    """读取一份评测的任务、trial、验收和调用指标。"""

    return service.get_run(run_id)


__all__ = ["router"]
