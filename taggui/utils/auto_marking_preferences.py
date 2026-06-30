import json

from utils.settings import settings


CLASS_ACTIONS_SETTINGS_KEY = "auto_marking_class_actions_json"
CLASS_LABELS_SETTINGS_KEY = "auto_marking_class_labels_json"


def load_saved_class_values(key: str) -> dict[str, dict[str, str]]:
    raw = settings.value(key, "{}", type=str)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def save_saved_class_values(
    key: str,
    payload: dict[str, dict[str, str]],
):
    settings.setValue(key, json.dumps(payload))


def saved_class_labels_for_model(model_key: str) -> dict[str, str]:
    requested = str(model_key or "").strip()
    if not requested:
        return {}
    payload = load_saved_class_values(CLASS_LABELS_SETTINGS_KEY)
    direct = payload.get(requested)
    if isinstance(direct, dict):
        return {
            str(class_id): str(label)
            for class_id, label in direct.items()
            if str(label).strip()
        }

    normalized = requested.replace("\\", "/").casefold()
    for saved_model, labels in payload.items():
        if str(saved_model).replace("\\", "/").casefold() != normalized:
            continue
        if not isinstance(labels, dict):
            return {}
        return {
            str(class_id): str(label)
            for class_id, label in labels.items()
            if str(label).strip()
        }
    return {}
