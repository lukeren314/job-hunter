import json
import anthropic

_FIELDS = [
    "company", "title", "location", "work_type", "salary_min", "salary_max",
    "employment_type", "seniority_level", "level",
    "responsibilities", "requirements", "preferred_qualifications", "description",
]


def fill_missing_fields(job: dict) -> dict:
    missing = [f for f in _FIELDS if not job.get(f)]
    if not missing:
        return job

    raw = (job.get("raw_content") or job.get("description") or "")[:6000]
    partial = {f: job.get(f) for f in _FIELDS if job.get(f)}

    prompt = (
        f"Extract the following missing fields from this job posting.\n"
        f"Missing fields: {', '.join(missing)}\n"
        f"Partial data already extracted: {json.dumps(partial)}\n\n"
        f"Raw job content:\n{raw}\n\n"
        f"Return ONLY a JSON object with the missing fields filled in. "
        f"Omit fields you cannot determine. No commentary."
    )

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]

    try:
        filled = json.loads(text)
    except json.JSONDecodeError:
        return job

    merged = {**job}
    for field, value in filled.items():
        if field in _FIELDS and value and not merged.get(field):
            merged[field] = value
    return merged
