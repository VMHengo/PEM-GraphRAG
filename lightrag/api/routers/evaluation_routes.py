"""Evaluation and benchmark routes for the LightRAG API."""

from __future__ import annotations

import asyncio
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from lightrag.api.utils_api import get_combined_auth_dependency
from lightrag.evaluation.live_benchmark import (
    list_benchmarks,
    load_benchmark,
    run_live_benchmark,
)
from lightrag.evaluation.prompt_experiments import (
    create_prompt_experiment,
    estimate_prompt_experiment,
    execute_prompt_experiment,
    list_prompt_experiments,
    list_prompt_profiles,
    load_prompt_experiment,
    prompt_experiment_promotion_enabled,
    prompt_experiments_enabled,
    prompt_experiment_limits,
    promote_prompt_experiment_candidate,
    recover_interrupted_prompt_experiments,
)
from lightrag.evaluation.run_history import (
    complete_run,
    create_run,
    fail_run,
    get_run,
    list_runs,
    mark_run_running,
    recover_interrupted_runs,
    update_run_metadata,
)
from lightrag.utils import logger


class BenchmarkListItem(BaseModel):
    id: str
    name: str
    description: str
    case_count: int
    tier: str = "custom"


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


class BenchmarkRunStartRequest(BaseModel):
    mode: Literal["graph", "retrieval", "full"] = "retrieval"
    title: str | None = Field(default=None, max_length=160)
    note: str | None = Field(default=None, max_length=4000)


class BenchmarkRunUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=160)
    note: str | None = Field(default=None, max_length=4000)


class BenchmarkRunSummary(BaseModel):
    id: str
    title: str
    note: str
    status: Literal["queued", "running", "completed", "failed", "interrupted"]
    benchmark_id: str
    benchmark_name: str
    mode: Literal["graph", "retrieval", "full"]
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    updated_at: str
    error: str | None = None
    scores: dict[str, float | None] = Field(default_factory=dict)
    quality_gates_passed: bool | None = None
    failed_check_count: int = 0
    case_count: int = 0
    extraction_revision: dict | None = None


class BenchmarkRunListResponse(BaseModel):
    runs: list[BenchmarkRunSummary]
    total: int


class BenchmarkRunStartResponse(BaseModel):
    run: BenchmarkRunSummary


class BenchmarkRunDetailResponse(BaseModel):
    run: BenchmarkRunSummary
    result: dict | None = None


class PromptExperimentEstimateRequest(BaseModel):
    document_ids: list[str] = Field(min_length=1, max_length=20)
    profile_files: list[str] = Field(min_length=1, max_length=5)
    optimization_mode: Literal["screening", "validation", "final"] = "screening"
    benchmark_id: str | None = Field(default=None, min_length=1, max_length=160)


class PromptExperimentStartRequest(PromptExperimentEstimateRequest):
    title: str = Field(min_length=1, max_length=160)
    note: str = Field(default="", max_length=4000)
    benchmark_id: str = Field(min_length=1, max_length=160)
    benchmark_mode: Literal["graph", "retrieval", "full"] | None = None


class PromptExperimentPromotionRequest(BaseModel):
    profile_file: str = Field(min_length=1, max_length=255)


def create_evaluation_routes(rag, api_key: Optional[str] = None):
    router = APIRouter(prefix="/evaluation", tags=["evaluation"])
    combined_auth = get_combined_auth_dependency(api_key)
    working_dir = getattr(rag, "working_dir", "./rag_storage")
    active_runs: dict[str, asyncio.Task[None]] = {}
    run_lock = asyncio.Lock()
    active_prompt_experiments: dict[str, asyncio.Task[None]] = {}
    prompt_experiment_lock = asyncio.Lock()

    def get_active_extraction_revision() -> dict | None:
        """Return provenance when the supplied RAG implementation supports it."""

        get_revision = getattr(rag, "get_extraction_revision", None)
        return get_revision() if callable(get_revision) else None

    recovered = recover_interrupted_runs(working_dir)
    if recovered:
        logger.warning("Marked %s interrupted benchmark runs after server restart", recovered)
    recovered_experiments = recover_interrupted_prompt_experiments(working_dir)
    if recovered_experiments:
        logger.warning(
            "Marked %s interrupted prompt experiments after server restart",
            recovered_experiments,
        )

    async def execute_run(run_id: str, benchmark_id: str, mode: str) -> None:
        try:
            mark_run_running(working_dir, run_id)
            result = await run_live_benchmark(
                rag,
                benchmark_id,
                mode=mode,  # type: ignore[arg-type]
                save_result=False,
            )
            complete_run(working_dir, run_id, result)
            logger.info("Benchmark run %s completed", run_id)
        except Exception as exc:
            logger.error("Benchmark run %s failed: %s", run_id, exc, exc_info=True)
            try:
                fail_run(working_dir, run_id, str(exc))
            except Exception:
                logger.exception("Failed to persist benchmark run error for %s", run_id)
        finally:
            active_runs.pop(run_id, None)

    async def execute_experiment(experiment_id: str) -> None:
        try:
            await execute_prompt_experiment(rag, experiment_id)
        finally:
            active_prompt_experiments.pop(experiment_id, None)

    @router.get(
        "/benchmarks",
        response_model=BenchmarkListResponse,
        dependencies=[Depends(combined_auth)],
    )
    async def get_benchmarks():
        try:
            refs = list_benchmarks(working_dir)
            return BenchmarkListResponse(
                benchmarks=[
                    BenchmarkListItem(
                        id=ref.id,
                        name=ref.name,
                        description=ref.description,
                        case_count=ref.case_count,
                        tier=ref.tier,
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
            benchmark = load_benchmark(benchmark_id, working_dir)
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

    @router.post(
        "/benchmarks/{benchmark_id}/runs",
        response_model=BenchmarkRunStartResponse,
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[Depends(combined_auth)],
    )
    async def start_benchmark_run(benchmark_id: str, request: BenchmarkRunStartRequest):
        try:
            benchmark = load_benchmark(benchmark_id, working_dir)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.error("Failed to load benchmark %s: %s", benchmark_id, exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        async with run_lock:
            active_runs_copy = [
                run_id for run_id, task in active_runs.items() if not task.done()
            ]
            if active_runs_copy:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "message": "Another benchmark run is already active.",
                        "active_run_id": active_runs_copy[0],
                    },
                )

            try:
                run = create_run(
                    working_dir,
                    benchmark_id=str(benchmark["id"]),
                    benchmark_name=str(benchmark.get("name") or benchmark["id"]),
                    case_count=(
                        len(benchmark.get("cases") or [])
                        + len(benchmark.get("directed_cases") or [])
                    ),
                    mode=request.mode,
                    title=request.title,
                    note=request.note,
                    extraction_revision=get_active_extraction_revision(),
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

            active_runs[run["id"]] = asyncio.create_task(
                execute_run(run["id"], str(benchmark["id"]), request.mode),
                name=f"evaluation-benchmark-{run['id']}",
            )
            return BenchmarkRunStartResponse(run=BenchmarkRunSummary(**run))

    @router.get(
        "/runs",
        response_model=BenchmarkRunListResponse,
        dependencies=[Depends(combined_auth)],
    )
    async def get_benchmark_runs(
        benchmark_id: str | None = None,
        limit: int = Query(default=25, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        try:
            runs, total = list_runs(
                working_dir,
                benchmark_id=benchmark_id,
                limit=limit,
                offset=offset,
            )
            return BenchmarkRunListResponse(
                runs=[BenchmarkRunSummary(**run) for run in runs], total=total
            )
        except Exception as exc:
            logger.error("Failed to list benchmark runs: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get(
        "/runs/{run_id}",
        response_model=BenchmarkRunDetailResponse,
        dependencies=[Depends(combined_auth)],
    )
    async def get_benchmark_run(run_id: str):
        try:
            run = get_run(working_dir, run_id)
            return BenchmarkRunDetailResponse(
                run=BenchmarkRunSummary(**run["run"]), result=run["result"]
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.error("Failed to load benchmark run %s: %s", run_id, exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.patch(
        "/runs/{run_id}",
        response_model=BenchmarkRunStartResponse,
        dependencies=[Depends(combined_auth)],
    )
    async def edit_benchmark_run(run_id: str, request: BenchmarkRunUpdateRequest):
        if request.title is None and request.note is None:
            raise HTTPException(status_code=422, detail="Provide a title or note to update")
        try:
            run = update_run_metadata(
                working_dir, run_id, title=request.title, note=request.note
            )
            return BenchmarkRunStartResponse(run=BenchmarkRunSummary(**run))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            logger.error("Failed to update benchmark run %s: %s", run_id, exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get(
        "/prompt-experiments/config",
        dependencies=[Depends(combined_auth)],
    )
    async def get_prompt_experiment_config():
        return {
            "enabled": prompt_experiments_enabled(),
            "promotion_enabled": prompt_experiment_promotion_enabled(),
            "profiles": list_prompt_profiles(rag),
            "active_extraction_revision": get_active_extraction_revision(),
            "limits": prompt_experiment_limits(),
        }

    @router.post(
        "/prompt-experiments/estimate",
        dependencies=[Depends(combined_auth)],
    )
    async def estimate_prompt_experiment_route(request: PromptExperimentEstimateRequest):
        if not prompt_experiments_enabled():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Prompt experiments are disabled by the operator.",
            )
        try:
            return await estimate_prompt_experiment(
                rag,
                document_ids=request.document_ids,
                profile_files=request.profile_files,
                optimization_mode=request.optimization_mode,
                benchmark_id=request.benchmark_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        except Exception as exc:
            logger.error("Failed to estimate prompt experiment: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get(
        "/prompt-experiments",
        dependencies=[Depends(combined_auth)],
    )
    async def get_prompt_experiments(limit: int = Query(default=20, ge=1, le=100)):
        return {"experiments": list_prompt_experiments(working_dir, limit=limit)}

    @router.get(
        "/prompt-experiments/{experiment_id}",
        dependencies=[Depends(combined_auth)],
    )
    async def get_prompt_experiment(experiment_id: str):
        try:
            return load_prompt_experiment(working_dir, experiment_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Prompt experiment not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post(
        "/prompt-experiments",
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[Depends(combined_auth)],
    )
    async def start_prompt_experiment(request: PromptExperimentStartRequest):
        if not prompt_experiments_enabled():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Prompt experiments are disabled by the operator.",
            )
        async with prompt_experiment_lock:
            existing = [
                experiment_id
                for experiment_id, task in active_prompt_experiments.items()
                if not task.done()
            ]
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "message": "Another prompt experiment is already active.",
                        "active_experiment_id": existing[0],
                    },
                )
            if any(not task.done() for task in active_runs.values()):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A regular benchmark is active. Wait before starting a prompt experiment.",
                )
            try:
                experiment = await create_prompt_experiment(
                    rag,
                    title=request.title,
                    note=request.note,
                    document_ids=request.document_ids,
                    profile_files=request.profile_files,
                    benchmark_id=request.benchmark_id,
                    optimization_mode=request.optimization_mode,
                    benchmark_mode=request.benchmark_mode,
                )
            except PermissionError as exc:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
            task = asyncio.create_task(
                execute_experiment(str(experiment["id"])),
                name=f"prompt-experiment-{experiment['id']}",
            )
            active_prompt_experiments[str(experiment["id"])] = task
            return experiment

    @router.post(
        "/prompt-experiments/{experiment_id}/cancel",
        dependencies=[Depends(combined_auth)],
    )
    async def cancel_prompt_experiment(experiment_id: str):
        task = active_prompt_experiments.get(experiment_id)
        if task is None or task.done():
            raise HTTPException(status_code=409, detail="This prompt experiment is not running")
        task.cancel()
        return {"id": experiment_id, "status": "cancelling"}

    @router.post(
        "/prompt-experiments/{experiment_id}/promote",
        dependencies=[Depends(combined_auth)],
    )
    async def promote_prompt_experiment(
        experiment_id: str, request: PromptExperimentPromotionRequest
    ):
        if experiment_id in active_prompt_experiments:
            raise HTTPException(status_code=409, detail="Wait for the prompt experiment to complete before promotion")
        try:
            return await promote_prompt_experiment_candidate(
                rag,
                experiment_id=experiment_id,
                profile_file=request.profile_file,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except Exception as exc:
            logger.error("Prompt experiment promotion failed: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return router
