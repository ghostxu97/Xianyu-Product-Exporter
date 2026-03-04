#!/usr/bin/env python3
from __future__ import annotations

import sys
import threading
import uuid
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_from_directory

# 允许在子目录启动时，自动从上级目录加载核心导出脚本
BASE_DIR = Path(__file__).resolve().parent
PARENT_DIR = BASE_DIR.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if str(PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_DIR))

from export_goofish_products import build_default_output_dir, export_from_online, split_keywords

WEB_DIR = BASE_DIR / "webui"

app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="/static")

tasks: dict[str, dict[str, Any]] = {}
tasks_lock = threading.Lock()


def _update_task(task_id: str, **kwargs: Any) -> None:
    with tasks_lock:
        task = tasks.get(task_id, {})
        task.update(kwargs)
        tasks[task_id] = task


def _append_log(task_id: str, message: str) -> None:
    with tasks_lock:
        task = tasks.get(task_id)
        if not task:
            return
        task["logs"].append(message)


@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.post("/api/start")
def api_start():
    payload = request.get_json(force=True, silent=True) or {}
    personal_url = str(payload.get("personal_url", "")).strip()
    cookies = str(payload.get("cookies", "")).strip()
    out_dir = str(payload.get("out_dir", "")).strip()
    include_raw = str(payload.get("include_keywords", "")).strip()
    exclude_raw = str(payload.get("exclude_keywords", "")).strip()
    max_items_raw = str(payload.get("max_items", "0")).strip()
    include_offline_raw = payload.get("include_offline_items", True)

    if not personal_url:
        return jsonify({"ok": False, "error": "personal_url 不能为空"}), 400
    if not cookies:
        return jsonify({"ok": False, "error": "cookies 不能为空"}), 400
    try:
        max_items = int(max_items_raw or "0")
    except ValueError:
        return jsonify({"ok": False, "error": "max_items 必须是整数"}), 400

    include_keywords = split_keywords(include_raw)
    exclude_keywords = split_keywords(exclude_raw)
    include_offline_items = str(include_offline_raw).strip().lower() not in {"false", "0", "no", "off"}
    if not out_dir:
        out_dir = str(
            build_default_output_dir(
                personal_url=personal_url,
                cookie=cookies,
                include_keywords=include_keywords,
                exclude_keywords=exclude_keywords,
                base_dir=BASE_DIR,
            )
        )

    task_id = uuid.uuid4().hex[:12]
    _update_task(
        task_id,
        status="running",
        logs=[],
        summary=None,
        error=None,
    )

    def worker() -> None:
        try:
            summary = export_from_online(
                personal_url=personal_url,
                output_dir=Path(out_dir).resolve(),
                cookie=cookies,
                max_items=max_items,
                include_keywords=include_keywords,
                exclude_keywords=exclude_keywords,
                include_offline_items=include_offline_items,
                log=lambda msg: _append_log(task_id, msg),
            )
            _update_task(task_id, status="done", summary=summary, out_dir=out_dir)
        except Exception as e:
            _append_log(task_id, f"失败: {type(e).__name__}: {e}")
            _update_task(task_id, status="error", error=f"{type(e).__name__}: {e}")

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"ok": True, "task_id": task_id, "out_dir": out_dir})


@app.get("/api/status/<task_id>")
def api_status(task_id: str):
    offset_raw = request.args.get("offset", "0")
    try:
        offset = int(offset_raw)
    except ValueError:
        offset = 0
    with tasks_lock:
        task = tasks.get(task_id)
        if not task:
            return jsonify({"ok": False, "error": "task 不存在"}), 404
        logs = task["logs"][offset:]
        return jsonify(
            {
                "ok": True,
                "status": task["status"],
                "logs": logs,
                "next_offset": offset + len(logs),
                "summary": task.get("summary"),
                "error": task.get("error"),
                "out_dir": task.get("out_dir"),
            }
        )


def main() -> None:
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    app.run(host="127.0.0.1", port=8765, debug=False)


if __name__ == "__main__":
    main()
