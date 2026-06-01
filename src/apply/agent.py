"""
Apply agent — 40-step Anthropic tool-use loop.
Port of apply_agent.js runAgent().
"""
import asyncio
import json
import re
from collections import deque
from pathlib import Path

import anthropic
from playwright.async_api import async_playwright

from apply.heuristics import annotate_snapshot, compact_snapshot, get_known_answer, best_select_option
from apply.prompts import TOOLS, build_system_prompt
from apply import tools as browser_tools
from common.config import load_personal_info, load_resume_text

ROOT = Path(__file__).parent.parent
PERSONAL_INFO_PATH = ROOT / "config" / "personal_info.json"

_NEXT_BUTTON_RE = re.compile(
    r"^(next|continue|next step|proceed|save and continue|save & continue|go to next|"
    r"save and next|next page|next section|save progress|confirm and continue|"
    r"review and submit|continue to next step)$",
    re.I,
)

_TERMINAL_SUBMIT_RE = re.compile(
    r"^(submit|send application|submit application|complete application|final submit|apply)$",
    re.I,
)


async def run_agent(
    target_url: str,
    headless: bool = True,
    collect_questions: bool = False,
    no_wait: bool = False,
) -> dict:
    target_url = browser_tools.resolve_apply_url(target_url)
    personal_info = load_personal_info()
    resume_text = load_resume_text()
    system_prompt = build_system_prompt(personal_info, resume_text)

    client = anthropic.Anthropic()
    messages: list[dict] = []

    pending_questions: list[dict] = []
    unfilled_fields: list[str] = []
    filled_selectors: set[str] = set()
    finished = False
    completion_url = None
    step = 0

    recent_actions: deque[str] = deque(maxlen=8)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(viewport={"width": 1365, "height": 900})
        # Inject LinkedIn session cookies if navigating to a LinkedIn URL
        if "linkedin.com" in target_url:
            li_cookies = browser_tools.load_linkedin_cookies()
            if li_cookies:
                await ctx.add_cookies(li_cookies)
        page = await ctx.new_page()

        try:
            await browser_tools.navigate(page, target_url)
            snapshot = await browser_tools.get_page_content(page)
            snapshot = annotate_snapshot(snapshot, personal_info)

            # Heuristic pre-fill
            prefill_result = await _prefill_known_fields(page, personal_info, filled_selectors)
            if prefill_result["filled"]:
                snapshot = await browser_tools.get_page_content(page)
                snapshot = annotate_snapshot(snapshot, personal_info)

            # Initial user message
            messages.append({
                "role": "user",
                "content": f"Start filling out the application at {target_url}.\n\nCurrent page:\n{json.dumps(compact_snapshot(snapshot))}",
            })

            while not finished and step < 40:
                step += 1
                print(f"\n[Step {step}]")

                # Loop detection
                if len(recent_actions) >= 3:
                    last_3 = list(recent_actions)[-3:]
                    if len(set(last_3)) == 1:
                        messages.append({
                            "role": "user",
                            "content": (
                                "You've repeated the same action 3 times. Try a different approach: "
                                "use a different selector, scroll the page, or call signal_completion "
                                "if all required fields appear filled."
                            ),
                        })

                response = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=4096,
                    system=system_prompt,
                    tools=TOOLS,
                    messages=messages,
                )
                messages.append({"role": "assistant", "content": response.content})

                tool_calls = [b for b in response.content if b.type == "tool_use"]
                if not tool_calls:
                    print("  No tool call in response — stopping.")
                    break

                tool_results = []
                for tc in tool_calls:
                    tool_name = tc.name
                    tool_input = tc.input
                    action_key = f"{tool_name}:{json.dumps(tool_input, sort_keys=True)}"
                    recent_actions.append(action_key)
                    print(f"  Tool: {tool_name} {tool_input}")

                    result_content = await _dispatch_tool(
                        tool_name, tool_input, page, personal_info, filled_selectors,
                        pending_questions, collect_questions,
                    )

                    if tool_name == "signal_completion":
                        finished = True
                        completion_url = page.url

                    # After navigate/click, re-run prefill on new page
                    if tool_name in ("navigate", "click_element") and not finished:
                        filled_selectors.clear()
                        await asyncio.sleep(0.5)
                        new_snapshot = await browser_tools.get_page_content(page)
                        new_snapshot = annotate_snapshot(new_snapshot, personal_info)
                        await _prefill_known_fields(page, personal_info, filled_selectors)
                        new_snapshot = await browser_tools.get_page_content(page)
                        new_snapshot = annotate_snapshot(new_snapshot, personal_info)
                        result_content = json.dumps(compact_snapshot(new_snapshot))

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": str(result_content),
                    })

                if finished:
                    break

                messages.append({"role": "user", "content": tool_results})

                # Auto-advance check
                if not finished:
                    auto_advanced = await _try_auto_advance(page, personal_info, filled_selectors)
                    if auto_advanced:
                        snapshot = await browser_tools.get_page_content(page)
                        snapshot = annotate_snapshot(snapshot, personal_info)
                        messages.append({
                            "role": "user",
                            "content": f"Auto-advanced to next step. Current page:\n{json.dumps(compact_snapshot(snapshot))}",
                        })

        finally:
            if not no_wait and not headless:
                print("Keeping browser open 30s for review...")
                await asyncio.sleep(30)
            await browser.close()

    # Collect unfilled required fields from last snapshot (best effort)
    return {
        "finished": finished,
        "steps": step,
        "completion_url": completion_url,
        "pending_questions": pending_questions,
        "unfilled_fields": unfilled_fields,
    }


async def _dispatch_tool(
    tool_name: str,
    tool_input: dict,
    page,
    personal_info: dict,
    filled_selectors: set,
    pending_questions: list,
    collect_questions: bool,
) -> str:
    try:
        if tool_name == "navigate":
            await browser_tools.navigate(page, tool_input["url"])
            return "Navigated successfully."

        if tool_name == "get_page_content":
            snapshot = await browser_tools.get_page_content(page)
            snapshot = annotate_snapshot(snapshot, personal_info)
            return json.dumps(compact_snapshot(snapshot))

        if tool_name == "fill_field":
            await browser_tools.fill_field(page, tool_input["selector"], tool_input["value"])
            filled_selectors.add(tool_input["selector"])
            return f"Filled {tool_input['selector']} with {tool_input['value']!r}"

        if tool_name == "fill_multiple_fields":
            results = []
            for f in tool_input.get("fields") or []:
                try:
                    await browser_tools.fill_field(page, f["selector"], f["value"])
                    filled_selectors.add(f["selector"])
                    results.append(f"✓ {f['selector']}")
                except Exception as e:
                    results.append(f"✗ {f['selector']}: {e}")
            return "\n".join(results)

        if tool_name == "click_element":
            await browser_tools.click_element(page, tool_input["selector"])
            return f"Clicked {tool_input['selector']}"

        if tool_name == "upload_resume":
            await browser_tools.upload_resume(page, tool_input["selector"])
            filled_selectors.add(tool_input["selector"])
            return "Resume uploaded."

        if tool_name == "request_user_input":
            q = {"question": tool_input["question"], "field_key": tool_input["field_key"]}
            if collect_questions:
                pending_questions.append(q)
                return f"Question collected: {tool_input['question']}"
            print(f"\n[Question] {tool_input['question']}")
            answer = input("Your answer: ").strip()
            if answer and tool_input.get("field_key"):
                _save_to_personal_info(tool_input["field_key"], answer)
                personal_info[tool_input["field_key"]] = answer
            return f"User answered: {answer!r}"

        if tool_name == "signal_completion":
            return "Completion signaled."

        if tool_name == "wait_for_timeout":
            ms = min(tool_input.get("ms", 1000), 5000)
            await asyncio.sleep(ms / 1000)
            return f"Waited {ms}ms"

        return f"Unknown tool: {tool_name}"

    except Exception as e:
        return f"Error executing {tool_name}: {e}"


async def _prefill_known_fields(page, personal_info: dict, filled_selectors: set) -> dict:
    snapshot = await browser_tools.get_page_content(page)
    filled = []

    for item in snapshot.get("interactables") or []:
        selector = item.get("selector")
        if not selector or selector in filled_selectors:
            continue

        suggested = get_known_answer(item, personal_info)
        if not suggested:
            continue

        # High-confidence fields — fill even if optional
        label = (item.get("label") or "").lower()
        is_high_confidence = any(kw in label for kw in [
            "first name", "last name", "full name", "email", "linkedin", "github",
            "phone", "degree", "school", "university",
        ])
        if not item.get("required") and not is_high_confidence:
            continue

        if suggested == "__UPLOAD_RESUME__":
            try:
                await browser_tools.upload_resume(page, selector)
                filled_selectors.add(selector)
                filled.append(selector)
            except Exception:
                pass
            continue

        # For select fields, fuzzy-match the option
        if item.get("type") == "select" and item.get("options"):
            best = best_select_option(item["options"], suggested)
            if best:
                suggested = best

        try:
            await browser_tools.fill_field(page, selector, suggested)
            filled_selectors.add(selector)
            filled.append(selector)
        except Exception:
            pass

    # Second pass: EEOC fields (try decline options)
    for item in snapshot.get("interactables") or []:
        selector = item.get("selector")
        if not selector or selector in filled_selectors:
            continue
        label = (item.get("label") or "").lower()
        if not any(kw in label for kw in ["race", "ethnicity", "gender", "veteran", "disability", "hispanic"]):
            continue
        suggested = get_known_answer(item, personal_info)
        if suggested:
            try:
                await browser_tools.fill_field(page, selector, suggested)
                filled_selectors.add(selector)
                filled.append(selector)
            except Exception:
                pass

    return {"snapshot": snapshot, "filled": filled}


async def _try_auto_advance(page, personal_info: dict, filled_selectors: set) -> bool:
    snapshot = await browser_tools.get_page_content(page)
    required_items = [
        item for item in (snapshot.get("interactables") or [])
        if item.get("required") and item.get("selector") not in filled_selectors
        and item.get("type") not in ("button", "link")
    ]
    if required_items:
        return False

    # Look for Next/Continue button
    for item in snapshot.get("interactables") or []:
        if item.get("type") not in ("button", "link"):
            continue
        text = item.get("text") or ""
        if _NEXT_BUTTON_RE.match(text):
            if _TERMINAL_SUBMIT_RE.match(text):
                continue
            try:
                print(f"  Auto-advance: clicking '{text}'")
                await browser_tools.click_element(page, item["selector"])
                filled_selectors.clear()
                return True
            except Exception:
                pass
    return False


def _save_to_personal_info(key: str, value: str) -> None:
    try:
        data = json.loads(PERSONAL_INFO_PATH.read_text())
        data[key] = value
        PERSONAL_INFO_PATH.write_text(json.dumps(data, indent=2))
    except Exception:
        pass
