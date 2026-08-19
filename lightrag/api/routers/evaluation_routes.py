"""Evaluation and benchmark routes for the LightRAG API."""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from lightrag.api.utils_api import get_combined_auth_dependency
from lightrag.evaluation.live_benchmark import (
    list_benchmarks,
    load_benchmark,
    run_live_benchmark,
)
from lightrag.utils import logger


class BenchmarkListItem(BaseModel):
    id: str
    name: str
    description: str
    case_count: int


class BenchmarkListResponse(BaseModel):
    benchmarks: list[BenchmarkListItem]


class BenchmarkRunRequest(BaseModel):
    mode: Literal["graph", "retrieval", "full"] = Field(
        default="retrieval",
        description=(
            "graph = no query calls, retrieval = context/reference checks, "
            "full = generated-answer checks"
        ),
    )
    save_result: bool = Field(
        default=True,
        description="Persist the benchmark result under rag_storage/evaluation_runs",
    )


def create_evaluation_routes(rag, api_key: Optional[str] = None):
    router = APIRouter(prefix="/evaluation", tags=["evaluation"])
    combined_auth = get_combined_auth_dependency(api_key)

    @router.get(
        "/benchmarks",
        response_model=BenchmarkListResponse,
        dependencies=[Depends(combined_auth)],
    )
    async def get_benchmarks():
        try:
            refs = list_benchmarks(getattr(rag, "working_dir", None))
            return BenchmarkListResponse(
                benchmarks=[
                    BenchmarkListItem(
                        id=ref.id,
                        name=ref.name,
                        description=ref.description,
                        case_count=ref.case_count,
                    )
                    for ref in refs
                ]
            )
        except Exception as exc:
            logger.error("Failed to list benchmarks: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get(
        "/benchmarks/{benchmark_id}",
        dependencies=[Depends(combined_auth)],
    )
    async def get_benchmark(benchmark_id: str):
        try:
            benchmark = load_benchmark(benchmark_id, getattr(rag, "working_dir", None))
            benchmark.pop("path", None)
            return benchmark
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.error("Failed to load benchmark %s: %s", benchmark_id, exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.post(
        "/benchmarks/{benchmark_id}/run",
        dependencies=[Depends(combined_auth)],
    )
    async def run_benchmark(benchmark_id: str, request: BenchmarkRunRequest):
        try:
            return await run_live_benchmark(
                rag,
                benchmark_id,
                mode=request.mode,
                save_result=request.save_result,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.error("Failed to run benchmark %s: %s", benchmark_id, exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return router
