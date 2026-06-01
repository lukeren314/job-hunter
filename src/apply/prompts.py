TOOLS = [
    {
        "name": "navigate",
        "description": "Navigate the browser to a URL.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "URL to navigate to"}},
            "required": ["url"],
        },
    },
    {
        "name": "get_page_content",
        "description": "Get the current page's interactive elements and a text summary.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "fill_field",
        "description": "Fill a single form field by selector and value.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "[data-agent-ref=...] selector or label hint"},
                "value": {"type": "string", "description": "Value to enter"},
            },
            "required": ["selector", "value"],
        },
    },
    {
        "name": "fill_multiple_fields",
        "description": "Fill multiple form fields in a single call. Preferred over multiple fill_field calls.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fields": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "selector": {"type": "string"},
                            "value": {"type": "string"},
                        },
                        "required": ["selector", "value"],
                    },
                }
            },
            "required": ["fields"],
        },
    },
    {
        "name": "click_element",
        "description": "Click a button or link. Do NOT use on final submit buttons.",
        "input_schema": {
            "type": "object",
            "properties": {"selector": {"type": "string"}},
            "required": ["selector"],
        },
    },
    {
        "name": "upload_resume",
        "description": "Upload the user's resume PDF to a file input.",
        "input_schema": {
            "type": "object",
            "properties": {"selector": {"type": "string"}},
            "required": ["selector"],
        },
    },
    {
        "name": "request_user_input",
        "description": "Ask the user for information needed to fill a required field.",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "field_key": {"type": "string", "description": "Key to save in personal_info"},
            },
            "required": ["question", "field_key"],
        },
    },
    {
        "name": "signal_completion",
        "description": "Signal that all required fields are filled and the form is ready to submit.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "wait_for_timeout",
        "description": "Wait for a specified number of milliseconds.",
        "input_schema": {
            "type": "object",
            "properties": {"ms": {"type": "integer"}},
            "required": ["ms"],
        },
    },
]


def build_system_prompt(personal_info: dict, resume_text: str) -> str:
    import json

    return f"""You are a job application assistant. Fill out job application forms using the provided personal information and resume.

CRITICAL RULES:
1. Invoke exactly ONE tool per response turn.
2. After navigate or click_element, always call get_page_content next.
3. Prefer [data-agent-ref="el-N"] selectors. Fall back to label text as hint.
4. Fill required fields using personal_info and resume_text.
5. Work authorization / sponsorship: use exact values from personal_info.
6. Location yes/no: compare personal_info.location to the question's city.
7. Experience / skills: answer from resume_text.
8. Open-ended questions: honest answer grounded in resume.
9. If you see an "Apply for this job" button and no fields are visible, click it.
10. NEVER click the final submit button (Submit, Send Application, Complete Application, Apply).
11. When all required fields are filled: click Next/Continue if present, otherwise call signal_completion.
12. Call request_user_input ONLY for required fields you cannot answer from personal_info or resume.
13. If page content shows an iframeUrl, navigate to that URL directly.
14. Do NOT append /apply to URLs that already have query parameters.
15. Prefer fill_multiple_fields over multiple fill_field calls.

PERSONAL INFO:
{json.dumps(personal_info, indent=2)}

RESUME:
{resume_text[:5000]}
"""
