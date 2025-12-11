"""
Phone script loading helpers - shared across routers.
"""

import json
from pathlib import Path

from utils.html_processing import prepare_script_content

PHONE_SCRIPTS_DIR = Path("templates") / "phone"
PHONE_SCRIPT_SOURCES = [
    ("registered_agent", "Registered Agent", PHONE_SCRIPTS_DIR / "registered_agent.html"),
    ("decision_maker", "Decision Maker", PHONE_SCRIPTS_DIR / "decision_maker.html"),
    ("gatekeeper_contact", "Gatekeeper Contact Discovery", PHONE_SCRIPTS_DIR / "gatekeeper_contact_discovery_call.html"),
]


def load_phone_scripts():
    """
    Load phone scripts from template files.
    Returns a list of script dictionaries with 'key', 'label', 'text', and 'html' fields.
    """
    scripts = []
    for key, label, path in PHONE_SCRIPT_SOURCES:
        try:
            raw_text = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            raw_text = ""
        else:
            raw_text = raw_text.replace("\r\n", "\n")
        html_value, plain_value = prepare_script_content(raw_text)
        scripts.append(
            {
                "key": key,
                "label": label,
                "text": plain_value,
                "html": html_value,
            }
        )
    return scripts


def get_phone_scripts_json():
    """Get phone scripts as JSON string."""
    return json.dumps(load_phone_scripts())

