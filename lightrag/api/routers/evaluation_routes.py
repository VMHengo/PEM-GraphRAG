"""Evaluation and benchmark routes for the LightRAG API."""

from __future__ import annotations

import asyncio
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, field_validator

from lightrag.base import QueryParam
from lightrag.evaluation.exploration_discovery import discover_from_start
from lightrag.evaluation.human_review import (
    add_review,
    create_session,
    list_sessions,
    load_session,
    recover_interrupted_sessions,
    render_review_sheet,
    select_review_candidates,
    update_session,
)
from lightrag_mcp.exploration import format_exploration
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
    archived: bool = False


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


class ExplorationSessionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    starts: list[str] = Field(min_length=1, max_length=5)
    hop_depth: int = Field(default=3, ge=2, le=4)
    limit: int = Field(default=20, ge=1, le=20)

    @field_validator("starts")
    @classmethod
    def validate_starts(cls, starts: list[str]) -> list[str]:
        cleaned = [start.strip() for start in starts]
        if any(not 3 <= len(start) <= 200 for start in cleaned):
            raise ValueError("Each start node must contain 3 to 200 characters")
        if len({start.casefold() for start in cleaned}) != len(cleaned):
            raise ValueError("Start nodes must be distinct")
        return cleaned


class ExplorationReviewRequest(BaseModel):
    candidate_id: str = Field(min_length=1, max_length=80)
    reviewer: str = Field(min_length=1, max_length=80)
    interest: Literal["interesting", "neutral", "not_interesting", "unclear"]
    correctness: Literal["supported", "partial", "contradicted", "unclear"]
    hop_verdicts: list[Literal["supported", "partial", "contradicted", "unclear"]] = Field(
        min_length=2, max_length=4
    )
    conditions: Literal["compatible", "incompatible", "unclear"]
    inference_verdict: Literal[
        "plausible", "conditional", "contradicted", "not_derivable"
    ] | None = None
    follow_up: bool = False
    note: str = Field(default="", max_length=4000)


def create_evaluation_routes(rag, api_key: Optional[str] = None):
    router = APIRouter(prefix="/evaluation", tags=["evaluation"])
    combined_auth = get_combined_auth_dependency(api_key)
    working_dir = getattr(rag, "working_dir", "./rag_storage")
    active_runs: dict[str, asyncio.Task[None]] = {}
    run_lock = asyncio.Lock()
    active_prompt_experiments: dict[str, asyncio.Task[None]] = {}
    prompt_experiment_lock = asyncio.Lock()
    active_exploration: dict[str, asyncio.Task[None]] = {}
    exploration_lock = asyncio.Lock()

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
    recovered_reviews = recover_interrupted_sessions(working_dir)
    if recovered_reviews:
        logger.warning("Marked %s interrupted exploration reviews after restart", recovered_reviews)

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

    async def execute_exploration(session_id: str, starts: list[str], hop_depth: int, limit: int) -> None:
        discoveries: list[dict] = []
        seed_errors: list[dict[str, str]] = []
        seed_diagnostics: list[dict] = []
        try:
            update_session(working_dir, session_id, status="running")
            for index, start in enumerate(starts, start=1):
                try:
                    param = QueryParam(
                        mode="mix",
                        retrieval_strategy="directed",
                        edge_direction="out",
                        hop_depth=hop_depth,
                        chain_top_k=100,
                        ll_keywords=[start],
                        hl_keywords=[start],
                        include_references=True,
                        stream=False,
                    )
                    payload = await discover_from_start(rag, start, param)
                    if payload is None:
                        payload = await rag.aquery_data(
                            f"What can {start} cause or influence downstream?", param=param
                        )
                    discovery = format_exploration(
                        payload, start=start, limit=min(limit * 2, 40),
                        include_full_chunks=True, max_paths_per_target=2,
                    )
                    discoveries.append(discovery)
                    seed_diagnostics.append({
                        "start": start,
                        "retrieval_status": discovery["retrieval_status"],
                        "retrieval_reason": discovery["retrieval_reason"],
                        "paths_examined": discovery["paths_examined"],
                        "eligible_paths": discovery["candidate_count"],
                        "excluded_paths": discovery["excluded_paths"],
                        "empty_reason": discovery["empty_reason"],
                        "suggested_start_nodes": discovery["suggested_start_nodes"],
                    })
                except Exception as exc:
                    logger.warning("Exploration seed %s failed: %s", start, exc)
                    seed_errors.append({"start": start, "error": "Seed query failed; check server logs"})
                update_session(
                    working_dir, session_id,
                    completed_starts=index, seed_errors=seed_errors,
                    seed_diagnostics=seed_diagnostics,
                )
            candidates = select_review_candidates(discoveries, limit=limit)
            update_session(
                working_dir, session_id,
                status="completed" if discoveries else "failed",
                candidates=candidates,
                seed_errors=seed_errors,
                seed_diagnostics=seed_diagnostics,
                error=None if discoveries else "All start-node queries failed",
            )
        except Exception as exc:
            logger.error("Exploration session %s failed: %s", session_id, exc, exc_info=True)
            update_session(working_dir, session_id, status="failed", error="Discovery failed; check server logs")
        finally:
            active_exploration.pop(session_id, None)

    @router.get("/exploration/sessions", dependencies=[Depends(combined_auth)])
    async def get_exploration_sessions():
        return {"sessions": list_sessions(working_dir)}

    @router.post(
        "/exploration/sessions", status_code=status.HTTP_202_ACCEPTED,
        dependencies=[Depends(combined_auth)],
    )
    async def start_exploration_session(request: ExplorationSessionRequest):
        if not request.title.strip():
            raise HTTPException(status_code=422, detail="A title is required")
        if not callable(getattr(rag, "aquery_data", None)):
            raise HTTPException(status_code=503, detail="Structured retrieval is unavailable")
        async with exploration_lock:
            if any(not task.done() for task in active_exploration.values()):
                raise HTTPException(status_code=409, detail="Another exploration is running")
            session = create_session(
                working_dir,
                title=request.title.strip(),
                starts=request.starts,
                hop_depth=request.hop_depth,
                limit=request.limit,
                extraction_revision=get_active_extraction_revision(),
            )
            active_exploration[session["id"]] = asyncio.create_task(
                execute_exploration(session["id"], request.starts, request.hop_depth, request.limit),
                name=f"evaluation-exploration-{session['id']}",
            )
        return {"session": session}

    @router.get("/exploration/sessions/{session_id}", dependencies=[Depends(combined_auth)])
    async def get_exploration_session(session_id: str):
        try:
            return {"session": load_session(working_dir, session_id)}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get(
        "/exploration/sessions/{session_id}/review-sheet",
        dependencies=[Depends(combined_auth)],
    )
    async def get_exploration_review_sheet(session_id: str):
        try:
            session = load_session(working_dir, session_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(
            content=render_review_sheet(session),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{session_id}-review.md"'},
        )

    @router.post(
        "/exploration/sessions/{session_id}/reviews",
        dependencies=[Depends(combined_auth)],
    )
    async def submit_exploration_review(session_id: str, request: ExplorationReviewRequest):
        try:
            review = add_review(
                working_dir, session_id,
                candidate_id=request.candidate_id,
                reviewer=request.reviewer.strip(),
                interest=request.interest,
                correctness=request.correctness,
                hop_verdicts=list(request.hop_verdicts),
                conditions=request.conditions,
                inference_verdict=request.inference_verdict,
                follow_up=request.follow_up,
                note=request.note.strip(),
            )
            return {"review": review}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

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
                        archived=ref.archived,
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
