from datetime import datetime
from pathlib import Path
from typing import List


def list_claim_files(dir_path: Path) -> List[dict]:
    files = []
    if not dir_path.exists() or not dir_path.is_dir():
        return files

    allowed_extensions = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp", ".svg"}

    for p in sorted(dir_path.iterdir()):
        if p.is_file() and p.suffix.lower() in allowed_extensions:
            files.append(
                {
                    "name": p.name,
                    "path": str(p),
                    "created_at": datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
                }
            )
    return files


def get_claim_files_dir(base_dir: Path, file_type: str) -> Path:
    return base_dir / ("generated" if file_type == "generated" else "package")


def resolve_claim_file(base_dir: Path, file_type: str, name: str) -> Path:
    target = get_claim_files_dir(base_dir, file_type)
    file_path = target / name
    if not target.exists():
        raise FileNotFoundError("target dir missing")
    try:
        file_path.resolve().relative_to(target.resolve())
    except Exception as exc:
        raise ValueError("invalid path") from exc
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError("file missing")
    return file_path
