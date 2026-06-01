from typing import TypedDict


class EvaluationResult(TypedDict):
    job_id: str
    fit_score: int      # 0-100
    reasoning: str
    evaluated_at: str


def evaluate_job(job: dict, personal_info: dict) -> EvaluationResult:
    raise NotImplementedError("Evaluator not yet implemented")
