"""用户自定义预设（裁剪比例 / 像素尺寸）持久化，存于用户主目录。"""
from __future__ import annotations

import json
from math import gcd
from pathlib import Path

PRESETS_DIR = Path.home() / ".imgtoolbox"
PRESETS_FILE = PRESETS_DIR / "presets.json"

DEFAULT_RATIOS = [("1:1", 1, 1), ("4:3", 4, 3), ("3:4", 3, 4), ("16:9", 16, 9),
                  ("9:16", 9, 16), ("3:2", 3, 2), ("2:3", 2, 3)]
DEFAULT_SIZES = [(1920, 1080), (1280, 720), (1080, 1080), (1080, 1920), (800, 600)]


def load_presets() -> dict:
    """返回 {"custom_ratios": [(label, w, h)...], "custom_sizes": [(w, h)...]}。"""
    data = {"custom_ratios": [], "custom_sizes": []}
    if PRESETS_FILE.exists():
        try:
            raw = json.loads(PRESETS_FILE.read_text("utf-8"))
            for r in raw.get("custom_ratios", []):
                if isinstance(r, list) and len(r) == 3:
                    data["custom_ratios"].append((str(r[0]), int(r[1]), int(r[2])))
            for s in raw.get("custom_sizes", []):
                if isinstance(s, list) and len(s) == 2:
                    data["custom_sizes"].append((int(s[0]), int(s[1])))
        except (OSError, ValueError, json.JSONDecodeError):
            pass  # 预设损坏时回退到默认
    return data


def save_custom(custom_ratios: list, custom_sizes: list) -> None:
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "custom_ratios": [[label, w, h] for label, w, h in custom_ratios],
        "custom_sizes": [[w, h] for w, h in custom_sizes],
    }
    PRESETS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                            encoding="utf-8")


def ratio_label(w: int, h: int) -> str:
    """按最大公约数化简的比例标签，如 1920:1080 -> 16:9。"""
    if w <= 0 or h <= 0:
        return f"{w}:{h}"
    g = gcd(w, h)
    return f"{w // g}:{h // g}"


def all_ratios() -> list[tuple[str, int, int]]:
    data = load_presets()
    seen = {label for label, _, _ in DEFAULT_RATIOS}
    out = list(DEFAULT_RATIOS)
    for label, w, h in data["custom_ratios"]:
        if label not in seen:
            seen.add(label)
            out.append((label, w, h))
    return out


def all_sizes() -> list[tuple[int, int]]:
    data = load_presets()
    seen = set(DEFAULT_SIZES)
    out = list(DEFAULT_SIZES)
    for w, h in data["custom_sizes"]:
        if (w, h) not in seen:
            seen.add((w, h))
            out.append((w, h))
    return out
