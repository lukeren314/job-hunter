import json
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
CONFIG_DIR = ROOT / "config"


def load_personal_info() -> dict:
    path = CONFIG_DIR / "personal_info.json"
    if not path.exists():
        path = CONFIG_DIR / "personal_info.example.json"
    with open(path) as f:
        return json.load(f)


def load_requirements() -> dict:
    with open(CONFIG_DIR / "requirements.json") as f:
        return json.load(f)


def load_resume_text() -> str:
    txt = CONFIG_DIR / "resume.txt"
    if txt.exists():
        return txt.read_text()
    pdf = CONFIG_DIR / "resume.pdf"
    if pdf.exists():
        try:
            from pdfminer.high_level import extract_text
            return extract_text(str(pdf))
        except ImportError:
            pass
    return ""
