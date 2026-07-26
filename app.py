from __future__ import annotations

import base64
import hmac
import io
import json
import logging
import os
import random
import secrets
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
)
from dotenv import load_dotenv
from werkzeug.utils import secure_filename

load_dotenv()

from config import Config
from integrations import (
    AIClient,
    CoReadingClient,
    ImageClient,
    IntegrationError,
    OmbreBrainClient,
    weather_now,
)
from store import Store


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("yuk-ches-home")

cfg = Config()
app = Flask(__name__)
app.secret_key = cfg.app_secret
app.config.update(
    JSON_AS_ASCII=False,
    MAX_CONTENT_LENGTH=15 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("FLASK_ENV") != "development",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,
)

store = Store(cfg.supabase_url, cfg.supabase_key)
ai = AIClient(cfg.api_url, cfg.api_key, cfg.api_model)
memory = OmbreBrainClient(cfg.ombre_url, cfg.ombre_token, cfg.ombre_enabled)
reader = CoReadingClient(
    cfg.reading_url,
    cfg.reading_mcp_url,
    cfg.reading_token,
)
image_ai = ImageClient(
    cfg.image_provider,
    cfg.image_url,
    cfg.image_key,
    cfg.image_model,
    sampler=cfg.nai_sampler,
    steps=cfg.nai_steps,
    scale=cfg.nai_scale,
)
upload_root = Path(app.instance_path) / "uploads"
upload_root.mkdir(parents=True, exist_ok=True)

_attempts: dict[str, list[float]] = {}
_chat_requests: dict[str, list[float]] = {}

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
PUBLIC_API_PATHS = {
    "/api/health",
    "/api/auth/status",
    "/api/auth/login",
    "/api/auth/logout",
}
EDITABLE_PROFILE_FIELDS = {
    "character_prompt",
    "worldbook",
    "relationship",
    "proactive_enabled",
    "user_name",
    "ai_name",
}
ALLOWED_ITEM_KINDS = {
    "note",
    "task",
    "mood",
    "habit",
    "attachment",
    "link",
    "music",
    "transaction",
    "account",
    "saving_plan",
    "shopping",
    "reward",
    "reward_offer",
    "reward_spend",
    "shopping_fund",
    "sticker",
    "image",
    "scene",
    "scene_comment",
    "ai_favorite",
    "ai_memo",
    "ai_wallet",
    "daily_quote",
}


def now_local() -> datetime:
    return datetime.now(cfg.timezone)


def json_error(message: str, status: int = 400):
    return jsonify({"error": message}), status


def request_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    return (forwarded.split(",")[0].strip() or request.remote_addr or "unknown")[:80]


def rate_limited(bucket: dict[str, list[float]], limit: int, window: int) -> bool:
    key = request_ip()
    cutoff = time.time() - window
    recent = [stamp for stamp in bucket.get(key, []) if stamp > cutoff]
    if len(recent) >= limit:
        bucket[key] = recent
        return True
    recent.append(time.time())
    bucket[key] = recent
    return False


def is_authenticated() -> bool:
    if not cfg.app_password:
        return True
    return session.get("authenticated") is True


def same_origin_ok() -> bool:
    origin = request.headers.get("Origin")
    if not origin:
        return True
    expected = f"{request.scheme}://{request.host}"
    return hmac.compare_digest(origin.rstrip("/"), expected.rstrip("/"))


@app.before_request
def protect_api():
    if (
        request.path.startswith("/api/")
        and request.path not in PUBLIC_API_PATHS
        and not (request.path == "/api/cron/tick" and valid_cron_request())
        and not is_authenticated()
    ):
        return json_error("请先输入家庭访问密码", 401)
    if request.method in MUTATING_METHODS and not same_origin_ok():
        return json_error("拒绝跨站请求", 403)
    return None


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(self), microphone=(self), geolocation=()"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data: blob: https:; "
        "media-src 'self' blob: https:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; "
        "connect-src 'self'; "
        "font-src 'self'; "
        "object-src 'none'; base-uri 'self'; form-action 'self'"
    )
    return response


@app.errorhandler(413)
def file_too_large(_error):
    return json_error("文件不能超过 15 MB", 413)


@app.errorhandler(500)
def internal_error(error):
    logger.exception("Unhandled error: %s", error)
    return json_error("家里暂时出了点小故障，请稍后重试", 500)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/health")
def health():
    return jsonify(
        {
            "ok": True,
            "storage": store.backend,
            "ai": ai.ready,
            "memory": memory.enabled,
            "reading": reader.enabled,
            "image": image_ai.ready,
        }
    )


@app.get("/api/auth/status")
def auth_status():
    return jsonify(
        {
            "authenticated": is_authenticated(),
            "password_required": bool(cfg.app_password),
        }
    )


@app.post("/api/auth/login")
def login():
    if rate_limited(_attempts, 8, 600):
        return json_error("尝试次数过多，请十分钟后再试", 429)
    data = request.get_json(silent=True) or {}
    password = str(data.get("password", ""))
    if not cfg.app_password or hmac.compare_digest(password, cfg.app_password):
        session.clear()
        session["authenticated"] = True
        session.permanent = True
        return jsonify({"ok": True})
    return json_error("密码不对", 401)


@app.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


def public_config() -> dict[str, Any]:
    profile = store.get_setting("profile", {}) or {}
    return {
        "start_date": cfg.start_date,
        "user_name": profile.get("user_name") or cfg.user_name,
        "ai_name": profile.get("ai_name") or cfg.ai_name,
        "timezone": cfg.timezone_name,
        "weather_location": cfg.weather_location,
        "profile": profile,
        "features": {
            "ai": ai.ready,
            "supabase": cfg.supabase_ready,
            "memory": memory.enabled,
            "reading": reader.enabled,
            "image": image_ai.ready,
            "proactive": bool(
                profile.get("proactive_enabled", cfg.proactive_enabled)
            ),
        },
    }


@app.get("/api/bootstrap")
def bootstrap():
    messages = store.list_messages(limit=300)
    items = store.list_items(limit=1000)
    graves = store.list_messages(statuses=("deleted", "rerolled"), limit=200)
    return jsonify(
        {
            "config": public_config(),
            "messages": messages,
            "items": items,
            "graves": graves,
            "rewards": reward_summary(items),
        }
    )


@app.put("/api/settings")
def update_settings():
    data = request.get_json(silent=True) or {}
    current = store.get_setting("profile", {}) or {}
    for key in EDITABLE_PROFILE_FIELDS:
        if key in data:
            value = data[key]
            if isinstance(value, str):
                value = value.strip()[:20000]
            current[key] = value
    store.set_setting("profile", current)
    return jsonify({"profile": current, "config": public_config()})


def build_system_prompt(memory_text: str, inner_thought: str = "") -> str:
    profile = store.get_setting("profile", {}) or {}
    parts = [
        cfg.system_prompt,
        profile.get("character_prompt", ""),
        profile.get("worldbook", ""),
        profile.get("relationship", ""),
        (
            "这是一个私密的共同生活空间。自然聊天，不要把界面功能说明当成对话内容。"
            "如果看到“内心想法”，它是用户愿意提供的额外情绪语境，不是要求展示模型思维链。"
        ),
    ]
    if memory_text:
        parts.append(
            "下面是 Ombre Brain 召回的长期经历。只在确实相关时自然使用，"
            "不要逐条复述，也不要声称是数据库内容：\n" + memory_text
        )
    if inner_thought:
        parts.append("本轮用户额外告诉你的内心想法：" + inner_thought[:2000])
    return "\n\n".join(str(part).strip() for part in parts if str(part).strip())


def ai_history(limit: int = 80) -> list[dict[str, Any]]:
    result = []
    for message in store.list_messages(limit=limit):
        if message.get("role") not in {"user", "assistant"}:
            continue
        content: Any = message.get("content", "")
        metadata = message.get("metadata") or {}
        quote = metadata.get("quote")
        if quote and message.get("role") == "user":
            content = f"[引用：{quote}]\n{content}"
        result.append({"role": message["role"], "content": content})
    return result


def attachment_bytes(item: dict[str, Any]) -> bytes:
    metadata = item.get("metadata") or {}
    path = str(metadata.get("storage_path") or "")
    if not path:
        raise FileNotFoundError("附件地址缺失")
    if metadata.get("storage") == "supabase" and store.supabase:
        return store.supabase.storage.from_(cfg.storage_bucket).download(path)
    return (upload_root / path).read_bytes()


def attachment_text(item: dict[str, Any], raw: bytes) -> str:
    name = str((item.get("metadata") or {}).get("original_name") or item["title"])
    suffix = Path(name).suffix.lower()
    if suffix in {".txt", ".md", ".markdown", ".json", ".csv", ".log"}:
        for encoding in ("utf-8-sig", "utf-16", "gb18030"):
            try:
                return raw.decode(encoding)[:30000]
            except UnicodeDecodeError:
                continue
        return ""
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                xml = archive.read("word/document.xml")
            root = ElementTree.fromstring(xml)
            namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            paragraphs = []
            for paragraph in root.iter(f"{namespace}p"):
                text = "".join(
                    node.text or ""
                    for node in paragraph.iter(f"{namespace}t")
                )
                if text:
                    paragraphs.append(text)
            return "\n".join(paragraphs)[:30000]
        except (KeyError, zipfile.BadZipFile, ElementTree.ParseError):
            return ""
    return ""


@app.post("/api/chat")
def chat():
    if rate_limited(_chat_requests, 12, 60):
        return json_error("说慢一点，我还在听上一句", 429)
    if not ai.ready:
        return json_error("聊天 API 尚未在 Render 环境变量中配置", 503)
    data = request.get_json(silent=True) or {}
    incoming = data.get("messages")
    if not isinstance(incoming, list):
        incoming = [data.get("message", "")]
    texts = [str(item).strip()[:12000] for item in incoming if str(item).strip()]
    if not texts:
        return json_error("消息不能为空")
    if len(texts) > 10:
        return json_error("一次最多连续发送 10 条")
    inner_thought = str(data.get("inner_thought", "")).strip()[:2000]
    quote = str(data.get("quote", "")).strip()[:2000]
    attachment_ids = [
        str(item_id)
        for item_id in (data.get("attachment_ids") or [])
        if str(item_id).strip()
    ][:6]

    created = []
    for index, text in enumerate(texts):
        metadata: dict[str, Any] = {}
        if index == 0 and quote:
            metadata["quote"] = quote
        if index == len(texts) - 1 and inner_thought:
            metadata["inner_thought"] = inner_thought
        created.append(store.create_message("user", text, metadata=metadata))

    memory_text = ""
    memory_warning = ""
    if memory.enabled:
        try:
            memory_text = memory.recall("\n".join(texts))
        except IntegrationError as error:
            memory_warning = str(error)
            logger.warning("Memory recall skipped: %s", error)

    attachment_notes: list[str] = []
    vision_parts: list[dict[str, Any]] = []
    for item_id in attachment_ids:
        item = store.get_item(item_id)
        if not item or item.get("kind") != "attachment":
            continue
        metadata = item.get("metadata") or {}
        try:
            raw = attachment_bytes(item)
        except (FileNotFoundError, OSError, Exception) as error:
            logger.warning("Attachment read failed: %s", error)
            continue
        content_type = str(metadata.get("content_type") or "")
        if content_type.startswith("image/") and len(raw) <= 6 * 1024 * 1024:
            encoded = base64.b64encode(raw).decode("ascii")
            vision_parts.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{content_type};base64,{encoded}"
                    },
                }
            )
        else:
            extracted = attachment_text(item, raw)
            if extracted:
                attachment_notes.append(
                    f"附件《{item.get('title') or '未命名'}》：\n{extracted}"
                )
            else:
                attachment_notes.append(
                    f"用户附加了文件《{item.get('title') or '未命名'}》，"
                    "当前无法提取正文。"
                )

    system_prompt = build_system_prompt(memory_text, inner_thought)
    if attachment_notes:
        system_prompt += "\n\n" + "\n\n".join(attachment_notes)
    reading_context = str(data.get("reading_context", "")).strip()[:20000]
    if reading_context:
        system_prompt += (
            "\n\n下面是你们正在共读的当前段落。可以围绕它自然交流：\n"
            + reading_context
        )
    messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
        *ai_history(),
    ]
    if vision_parts:
        for candidate in reversed(messages):
            if candidate.get("role") == "user":
                candidate["content"] = [
                    {"type": "text", "text": str(candidate["content"])},
                    *vision_parts,
                ]
                break
    try:
        reply = ai.chat(messages)
    except IntegrationError as error:
        return json_error(str(error), 502)

    assistant_message = store.create_message(
        "assistant",
        reply,
        metadata={"memory_recalled": bool(memory_text)},
        parent_id=created[-1]["id"],
    )

    memory_saved = False
    if memory.enabled:
        profile = store.get_setting("profile", {}) or {}
        user_name = profile.get("user_name") or cfg.user_name
        ai_name = profile.get("ai_name") or cfg.ai_name
        transcript = (
            f"我（{ai_name}）和{user_name}刚刚聊到：\n"
            + "\n".join(f"{user_name}：{text}" for text in texts)
            + f"\n我回应：{reply}"
        )
        try:
            memory.remember(transcript)
            memory_saved = True
        except IntegrationError as error:
            memory_warning = str(error)
            logger.warning("Memory write skipped: %s", error)

    return jsonify(
        {
            "user_messages": created,
            "message": assistant_message,
            "memory_saved": memory_saved,
            "memory_warning": memory_warning or None,
        }
    )


@app.patch("/api/messages/<message_id>")
def edit_message(message_id: str):
    message = store.get_message(message_id)
    if not message or message.get("status") != "active":
        return json_error("消息不存在", 404)
    data = request.get_json(silent=True) or {}
    changes: dict[str, Any] = {}
    if "content" in data:
        content = str(data["content"]).strip()[:12000]
        if not content:
            return json_error("消息不能为空")
        metadata = dict(message.get("metadata") or {})
        metadata.setdefault("edit_history", []).append(
            {
                "content": message["content"],
                "edited_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        changes.update(content=content, metadata=metadata)
    if "favorite_by" in data:
        owner = str(data["favorite_by"])
        if owner not in {"user", "ai"}:
            return json_error("收藏者无效")
        metadata = dict(changes.get("metadata") or message.get("metadata") or {})
        favorites = set(metadata.get("favorite_by") or [])
        if owner in favorites:
            favorites.remove(owner)
        else:
            favorites.add(owner)
        metadata["favorite_by"] = sorted(favorites)
        changes["metadata"] = metadata
    if not changes:
        return json_error("没有可更新的内容")
    return jsonify(store.update_message(message_id, changes))


@app.delete("/api/messages/<message_id>")
def delete_message(message_id: str):
    message = store.get_message(message_id)
    if not message or message.get("status") != "active":
        return json_error("消息不存在", 404)
    data = request.get_json(silent=True) or {}
    reason = str(data.get("reason", "")).strip()[:1000]
    updated = store.update_message(
        message_id, {"status": "deleted", "deletion_reason": reason or None}
    )
    return jsonify(updated)


@app.post("/api/messages/<message_id>/reroll")
def reroll_message(message_id: str):
    message = store.get_message(message_id)
    if not message or message.get("role") != "assistant":
        return json_error("只能重回 AI 消息", 404)
    store.update_message(message_id, {"status": "rerolled"})
    if not ai.ready:
        return json_error("聊天 API 尚未配置", 503)
    memory_text = ""
    if memory.enabled:
        try:
            history = ai_history()
            query = history[-1]["content"] if history else ""
            memory_text = memory.recall(str(query))
        except IntegrationError:
            pass
    try:
        reply = ai.chat(
            [
                {"role": "system", "content": build_system_prompt(memory_text)},
                *ai_history(),
            ],
            temperature=1.05,
        )
    except IntegrationError as error:
        return json_error(str(error), 502)
    created = store.create_message(
        "assistant",
        reply,
        metadata={"rerolled_from": message_id},
        parent_id=message.get("parent_id"),
    )
    return jsonify({"message": created, "grave": store.get_message(message_id)})


def ovo_message_content(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    texts: list[str] = []
    for part in message.get("parts") or []:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text" and part.get("text"):
            texts.append(str(part["text"]))
        elif part.get("type") == "image":
            description = part.get("description") or part.get("name") or "图片"
            texts.append(f"[图片：{description}]")
        elif part.get("type"):
            texts.append(f"[{part.get('type')}消息]")
    return "\n".join(texts).strip()


def ovo_histories(payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Return (character name, message) pairs from OVO chat or full backups."""
    history = payload.get("history")
    if isinstance(history, list):
        name = str(payload.get("charName") or payload.get("characterName") or "")
        return [(name, item) for item in history if isinstance(item, dict)]
    result: list[tuple[str, dict[str, Any]]] = []
    for character in payload.get("characters") or []:
        if not isinstance(character, dict):
            continue
        name = str(
            character.get("remarkName")
            or character.get("realName")
            or character.get("name")
            or ""
        )
        for item in character.get("history") or []:
            if isinstance(item, dict):
                result.append((name, item))
    return result


def ovo_timestamp_key(pair: tuple[str, dict[str, Any]]) -> float:
    value = pair[1].get("timestamp")
    try:
        numeric = float(value or 0)
        return numeric / 1000 if numeric > 10_000_000_000 else numeric
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            return 0


@app.post("/api/import/ovo")
def import_ovo_history():
    uploaded = request.files.get("file")
    mode = request.form.get("mode", "append")
    if not uploaded:
        return json_error("请选择 OVO 导出的 JSON 文件")
    try:
        payload = json.loads(uploaded.read().decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return json_error("文件不是有效的 UTF-8 JSON")
    if not isinstance(payload, dict):
        return json_error("OVO 文件结构无效")
    pairs = ovo_histories(payload)
    if not pairs:
        return json_error("没有找到 history 聊天记录")

    if mode == "replace":
        for existing in store.list_messages(limit=1000):
            store.update_message(
                existing["id"],
                {
                    "status": "deleted",
                    "deletion_reason": "导入 OVO 记录时替换",
                },
            )
    elif mode != "append":
        return json_error("导入模式无效")

    existing_source_ids = {
        (message.get("metadata") or {}).get("ovo_source_id")
        for message in store.list_messages(
            statuses=("active", "deleted", "rerolled"), limit=1000
        )
    }
    imported = 0
    skipped = 0
    for character_name, source in sorted(pairs, key=ovo_timestamp_key):
        source_id = str(source.get("id") or "")
        if source_id and source_id in existing_source_ids:
            skipped += 1
            continue
        content = ovo_message_content(source)
        if not content:
            skipped += 1
            continue
        source_role = str(source.get("role") or "user")
        role = "assistant" if source_role in {"assistant", "char", "ai"} else source_role
        if role not in {"user", "assistant", "system"}:
            role = "system"
        timestamp = source.get("timestamp")
        created_at = None
        try:
            numeric = float(timestamp)
            if numeric > 10_000_000_000:
                numeric /= 1000
            created_at = datetime.fromtimestamp(numeric, timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            try:
                parsed = datetime.fromisoformat(
                    str(timestamp).replace("Z", "+00:00")
                )
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                created_at = parsed.astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError):
                pass
        metadata = {
            "imported_from": "wq70/OVO",
            "ovo_source_id": source_id or None,
            "ovo_character": character_name or None,
            "ovo_parts": [
                {
                    key: value
                    for key, value in part.items()
                    if key not in {"data", "base64", "dataBase64"}
                }
                for part in (source.get("parts") or [])
                if isinstance(part, dict)
            ],
            "ovo_original_role": source_role,
        }
        store.create_message(
            role,
            content[:12000],
            metadata=metadata,
            created_at=created_at,
        )
        imported += 1
    return jsonify(
        {
            "ok": True,
            "imported": imported,
            "skipped": skipped,
            "mode": mode,
        }
    )


@app.get("/api/export/chat")
def export_chat_history():
    profile = store.get_setting("profile", {}) or {}
    history = []
    for message in store.list_messages(limit=1000):
        history.append(
            {
                "id": message["id"],
                "role": message["role"],
                "content": message["content"],
                "parts": [
                    {"type": "text", "text": message["content"]}
                ],
                "timestamp": int(
                    datetime.fromisoformat(message["created_at"]).timestamp() * 1000
                ),
                "metadata": message.get("metadata") or {},
            }
        )
    return jsonify(
        {
            "type": "uwu-chat-history",
            "version": 1,
            "charName": profile.get("ai_name") or cfg.ai_name,
            "exportTime": int(time.time() * 1000),
            "history": history,
        }
    )


@app.get("/api/items")
def list_items():
    kind = request.args.get("kind") or None
    return jsonify(store.list_items(kind=kind, limit=1000))


@app.post("/api/items")
def create_item():
    data = request.get_json(silent=True) or {}
    kind = str(data.get("kind", "note"))
    if kind not in ALLOWED_ITEM_KINDS:
        return json_error("不支持的记录类型")
    if kind in {"task", "habit"} and not data.get("value"):
        title = str(data.get("title") or data.get("content") or "未命名事项")
        data["value"] = ai.suggest_points(title) if ai.ready else 5
    data["kind"] = kind
    return jsonify(store.create_item(data)), 201


@app.patch("/api/items/<item_id>")
def update_item(item_id: str):
    item = store.get_item(item_id)
    if not item:
        return json_error("记录不存在", 404)
    data = request.get_json(silent=True) or {}
    if "kind" in data and data["kind"] not in ALLOWED_ITEM_KINDS:
        return json_error("不支持的记录类型")
    return jsonify(store.update_item(item_id, data))


@app.delete("/api/items/<item_id>")
def delete_item(item_id: str):
    if not store.get_item(item_id):
        return json_error("记录不存在", 404)
    return jsonify(store.archive_item(item_id))


def reward_summary(items: list[dict[str, Any]] | None = None) -> dict[str, float]:
    items = items if items is not None else store.list_items(limit=2000)
    earned = sum(float(item.get("value") or 0) for item in items if item["kind"] == "reward")
    spent = sum(
        float(item.get("value") or 0)
        for item in items
        if item["kind"] == "reward_spend"
    )
    fund = sum(
        float(item.get("value") or 0)
        for item in items
        if item["kind"] == "shopping_fund"
    )
    return {
        "earned": round(earned, 2),
        "spent": round(spent, 2),
        "balance": round(earned - spent, 2),
        "shopping_fund": round(fund, 2),
    }


def evaluate_rewards() -> list[dict[str, Any]]:
    awarded: list[dict[str, Any]] = []
    for item in store.list_items(limit=1000):
        if item["kind"] not in {"task", "habit"} or item["status"] != "done":
            continue
        metadata = dict(item.get("metadata") or {})
        if metadata.get("points_awarded"):
            continue
        points = max(float(item.get("value") or 0), 1)
        reward = store.create_item(
            {
                "kind": "reward",
                "title": item.get("title") or "完成事项",
                "content": f"完成 {item['kind']} 获得积分",
                "value": points,
                "metadata": {"source_item_id": item["id"]},
            }
        )
        metadata["points_awarded"] = True
        metadata["reward_id"] = reward["id"]
        store.update_item(item["id"], {"metadata": metadata})
        awarded.append(reward)
    return awarded


@app.post("/api/rewards/evaluate")
def reward_evaluate():
    awarded = evaluate_rewards()
    return jsonify({"awarded": awarded, "summary": reward_summary()})


@app.post("/api/rewards/redeem")
def reward_redeem():
    data = request.get_json(silent=True) or {}
    try:
        points = float(data.get("points") or 0)
    except (TypeError, ValueError):
        return json_error("积分格式不正确")
    summary = reward_summary()
    if points <= 0 or points > summary["balance"]:
        return json_error("积分不足或兑换数量无效")
    item = store.create_item(
        {
            "kind": "reward_spend",
            "title": str(data.get("title") or "娱乐兑换")[:200],
            "content": str(data.get("content") or "")[:2000],
            "value": points,
        }
    )
    return jsonify({"item": item, "summary": reward_summary()})


@app.post("/api/rewards/settle")
def reward_settle():
    balance = reward_summary()["balance"]
    if balance <= 0:
        return json_error("当前没有可转入购物基金的积分")
    date_key = now_local().date().isoformat()
    if store.get_setting(f"reward_settled:{date_key}", False):
        return json_error("今天已经结算过")
    spend = store.create_item(
        {
            "kind": "reward_spend",
            "title": "转入购物基金",
            "value": balance,
            "metadata": {"date": date_key},
        }
    )
    fund = store.create_item(
        {
            "kind": "shopping_fund",
            "title": "积分结转",
            "value": balance,
            "metadata": {"date": date_key},
        }
    )
    store.set_setting(f"reward_settled:{date_key}", True)
    return jsonify(
        {"spend": spend, "fund": fund, "summary": reward_summary()}
    )


@app.get("/api/weather")
def weather():
    return jsonify(
        weather_now(
            cfg.weather_latitude,
            cfg.weather_longitude,
            cfg.weather_location,
        )
    )


def daily_quote_value() -> dict[str, Any]:
    local = now_local()
    today = local.date().isoformat()
    existing = [
        item
        for item in store.list_items(kind="daily_quote", limit=30)
        if (item.get("metadata") or {}).get("date") == today
    ]
    if existing:
        return existing[0]
    fallbacks = [
        "书页间藏着时光，而我在这里等你。",
        "今天也给彼此留一盏柔和的灯。",
        "我们把寻常日子，慢慢过成家的样子。",
        "窗外的风路过书架，也路过我们。",
    ]
    target_key = f"quote_target_hour:{today}"
    target_hour = store.get_setting(target_key)
    if target_hour is None:
        target_hour = random.randint(0, 6)
        store.set_setting(target_key, target_hour)

    # 定时任务会在 00:00–06:00 每小时唤醒一次；目标小时让每天的短句
    # 不总是在同一时刻出现。目标时间前访问首页时只返回临时占位句，不落库。
    should_generate = (
        ai.ready
        and 0 <= local.hour < 7
        and local.hour >= int(target_hour)
    )
    if ai.ready and 0 <= local.hour < int(target_hour):
        return {
            "content": random.choice(fallbacks),
            "metadata": {
                "date": today,
                "generated_by_ai": False,
                "pending_ai_quote": True,
                "target_hour": int(target_hour),
            },
        }
    if should_generate:
        text = ai.short_text(
            f"你是{cfg.ai_name}。只写一句自然、私密、不油腻的晨间或夜间短句，30字以内。",
            f"今天是 {today}，写给{cfg.user_name}。",
            random.choice(fallbacks),
        )
    else:
        text = random.choice(fallbacks)
    return store.create_item(
        {
            "kind": "daily_quote",
            "title": today,
            "content": text,
            "metadata": {
                "date": today,
                "generated_by_ai": should_generate,
                "target_hour": int(target_hour),
            },
        }
    )


@app.get("/api/daily-quote")
def daily_quote():
    return jsonify(daily_quote_value())


@app.get("/api/integrations/status")
def integration_status():
    return jsonify(
        {
            "ai": {"enabled": ai.ready, "model": cfg.api_model or None},
            "supabase": {
                "enabled": cfg.supabase_ready,
                "backend": store.backend,
            },
            "memory": memory.status(),
            "reading": reader.status(),
            "image": {
                "enabled": image_ai.ready,
                "provider": cfg.image_provider or None,
                "model": cfg.image_model or None,
            },
        }
    )


@app.post("/api/memory/search")
def memory_search():
    if not memory.enabled:
        return json_error("Ombre Brain 尚未启用", 503)
    data = request.get_json(silent=True) or {}
    query = str(data.get("query", "")).strip()[:1000]
    if not query:
        return json_error("请输入要回忆的内容")
    try:
        text = memory.call_tool(
            "breath_search",
            {"query": query, "max_results": min(int(data.get("limit") or 5), 20)},
        )
        return jsonify({"text": text})
    except (IntegrationError, ValueError) as error:
        return json_error(str(error), 503)


@app.post("/api/memory/remember")
def memory_remember():
    if not memory.enabled:
        return json_error("Ombre Brain 尚未启用", 503)
    data = request.get_json(silent=True) or {}
    content = str(data.get("content", "")).strip()[:12000]
    if not content:
        return json_error("记忆内容不能为空")
    try:
        text = memory.remember(content)
        return jsonify({"text": text})
    except IntegrationError as error:
        return json_error(str(error), 503)


@app.get("/api/reading/books")
def reading_books():
    try:
        if cfg.reading_url:
            return jsonify(reader.request("GET", "/api/books"))
        return jsonify({"text": reader.call_tool("reading_list_books", {})})
    except IntegrationError as error:
        return json_error(str(error), 503)


@app.get("/api/reading/search")
def reading_search():
    query = str(request.args.get("q", "")).strip()[:500]
    book_id = str(request.args.get("bookId", "")).strip()[:200]
    if not query:
        return json_error("请输入搜索词")
    try:
        if cfg.reading_url:
            return jsonify(
                reader.request(
                    "GET",
                    "/api/search",
                    params={"q": query, "bookId": book_id or None},
                )
            )
        arguments: dict[str, Any] = {"query": query}
        if book_id:
            arguments["bookId"] = book_id
        return jsonify(
            {"text": reader.call_tool("reading_search_chunks", arguments)}
        )
    except IntegrationError as error:
        return json_error(str(error), 503)


@app.get("/api/reading/books/<book_id>/chunks")
def reading_chunks(book_id: str):
    try:
        if cfg.reading_url:
            return jsonify(
                reader.request("GET", f"/api/books/{book_id}/chunks")
            )
        return jsonify(
            {
                "text": reader.call_tool(
                    "reading_list_chunks", {"bookId": book_id}
                )
            }
        )
    except IntegrationError as error:
        return json_error(str(error), 503)


@app.get("/api/reading/books/<book_id>/chunks/<chunk_id>")
def reading_chunk(book_id: str, chunk_id: str):
    try:
        if cfg.reading_url:
            return jsonify(
                reader.request(
                    "GET",
                    f"/api/books/{book_id}/chunks/{chunk_id}",
                )
            )
        text = reader.call_tool(
            "reading_read_chunk",
            {"bookId": book_id, "chunkId": chunk_id},
        )
        return jsonify({"text": text})
    except IntegrationError as error:
        return json_error(str(error), 503)


@app.post("/api/reading/mark-read")
def reading_mark_read():
    data = request.get_json(silent=True) or {}
    book_id = str(data.get("bookId", "")).strip()
    chunk_id = str(data.get("chunkId", "")).strip()
    if not book_id or not chunk_id:
        return json_error("缺少书籍或章节")
    try:
        if cfg.reading_url:
            return jsonify(
                reader.request(
                    "POST",
                    "/api/mark-read",
                    json_body={"bookId": book_id, "chunkId": chunk_id},
                )
            )
        text = reader.call_tool(
            "reading_mark_read",
            {"bookId": book_id, "chunkId": chunk_id},
        )
        return jsonify({"text": text})
    except IntegrationError as error:
        return json_error(str(error), 503)


@app.post("/api/reading/annotations")
def reading_annotation():
    data = request.get_json(silent=True) or {}
    required = ("bookId", "chunkId", "quote", "note")
    if any(not str(data.get(key, "")).strip() for key in required):
        return json_error("书籍、章节、原文和批注都不能为空")
    arguments = {
        "bookId": str(data["bookId"]),
        "chunkId": str(data["chunkId"]),
        "quote": str(data["quote"])[:4000],
        "note": str(data["note"])[:4000],
        "kind": str(data.get("kind") or "margin"),
        "mood": str(data.get("mood") or ""),
        "author": "user",
        "status": "open",
    }
    try:
        if cfg.reading_url:
            return jsonify(
                reader.request(
                    "POST",
                    "/api/annotations",
                    json_body=arguments,
                )
            )
        text = reader.call_tool("reading_annotate_passage", arguments)
        return jsonify({"text": text})
    except IntegrationError as error:
        return json_error(str(error), 503)


@app.post("/api/reading/import")
def reading_import():
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return json_error("请选择 EPUB、TXT 或 Markdown 文件")
    suffix = Path(uploaded.filename).suffix.lower()
    if suffix not in {".epub", ".txt", ".md", ".markdown"}:
        return json_error("共读目前支持 EPUB、TXT 和 Markdown")
    raw = uploaded.read()
    if not raw:
        return json_error("文件为空")
    if len(raw) > 12 * 1024 * 1024:
        return json_error("共读导入文件不能超过 12 MB")
    arguments: dict[str, Any] = {
        "filename": secure_filename(uploaded.filename) or f"book{suffix}",
        "dataBase64": base64.b64encode(raw).decode("ascii"),
    }
    title = request.form.get("title", "").strip()
    author = request.form.get("author", "").strip()
    if title:
        arguments["title"] = title[:300]
    if author:
        arguments["author"] = author[:300]
    try:
        text = reader.call_tool("reading_import_book", arguments)
        return jsonify({"text": text})
    except IntegrationError as error:
        return json_error(str(error), 503)


def persist_blob(
    content: bytes,
    *,
    original_name: str,
    content_type: str,
) -> dict[str, Any]:
    safe_name = secure_filename(original_name) or "attachment"
    suffix = Path(safe_name).suffix.lower()[:12]
    object_name = f"{now_local():%Y/%m}/{uuid.uuid4().hex}{suffix}"
    metadata: dict[str, Any] = {
        "original_name": safe_name,
        "content_type": content_type or "application/octet-stream",
        "size": len(content),
        "storage_path": object_name,
    }
    if store.supabase:
        store.supabase.storage.from_(cfg.storage_bucket).upload(
            object_name,
            content,
            {
                "content-type": metadata["content_type"],
                "upsert": "false",
            },
        )
        metadata["storage"] = "supabase"
    else:
        target = upload_root / object_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        metadata["storage"] = "local"
    return metadata


@app.post("/api/upload")
def upload_file():
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return json_error("没有选择文件")
    original = secure_filename(uploaded.filename) or "attachment"
    content = uploaded.read()
    if not content:
        return json_error("文件为空")
    try:
        metadata = persist_blob(
            content,
            original_name=original,
            content_type=uploaded.mimetype or "application/octet-stream",
        )
    except Exception as error:
        logger.warning("Attachment upload failed: %s", error)
        return json_error(
            "上传失败，请确认 Supabase Storage bucket 已创建", 502
        )
    item = store.create_item(
        {
            "kind": "attachment",
            "title": original,
            "content": "",
            "metadata": metadata,
        }
    )
    return jsonify(item), 201


@app.post("/api/images/generate")
def generate_image():
    if not image_ai.ready:
        return json_error("NAI/生图 API 尚未配置", 503)
    data = request.get_json(silent=True) or {}
    prompt = str(data.get("prompt", "")).strip()[:8000]
    if not prompt:
        return json_error("生图提示词不能为空")
    try:
        result = image_ai.generate(
            prompt,
            negative_prompt=str(data.get("negative_prompt", ""))[:4000],
            width=int(data.get("width") or 832),
            height=int(data.get("height") or 1216),
            seed=(
                int(data["seed"])
                if str(data.get("seed", "")).strip()
                else None
            ),
        )
    except (IntegrationError, TypeError, ValueError) as error:
        return json_error(str(error), 502)
    metadata: dict[str, Any] = {
        "provider": result["provider"],
        "prompt": prompt,
        "negative_prompt": str(data.get("negative_prompt", ""))[:4000],
        "marked": False,
        "note": "",
    }
    if result.get("base64"):
        try:
            raw = base64.b64decode(result["base64"], validate=True)
            metadata.update(
                persist_blob(
                    raw,
                    original_name=f"generated-{int(time.time())}.png",
                    content_type="image/png",
                )
            )
        except (ValueError, Exception) as error:
            logger.warning("Generated image save failed: %s", error)
            return json_error("图片已生成，但保存失败", 502)
    else:
        metadata["remote_url"] = result.get("url")
        metadata["storage"] = "remote"
    item = store.create_item(
        {
            "kind": "image",
            "title": str(data.get("title") or "我们的生成图")[:200],
            "content": prompt,
            "metadata": metadata,
        }
    )
    return jsonify(item), 201


@app.get("/api/files/<item_id>")
def download_file(item_id: str):
    item = store.get_item(item_id)
    if not item or item.get("kind") not in {"attachment", "image"}:
        return json_error("文件不存在", 404)
    metadata = item.get("metadata") or {}
    if metadata.get("storage") == "remote" and metadata.get("remote_url"):
        return redirect(str(metadata["remote_url"]))
    path = metadata.get("storage_path")
    if not path:
        return json_error("文件地址缺失", 404)
    if metadata.get("storage") == "supabase" and store.supabase:
        try:
            signed = (
                store.supabase.storage.from_(cfg.storage_bucket)
                .create_signed_url(path, 3600)
            )
            url = signed.get("signedURL") or signed.get("signedUrl")
            if url:
                return redirect(url)
        except Exception as error:
            logger.warning("Signed URL failed: %s", error)
        return json_error("暂时无法生成下载地址", 502)
    directory = upload_root / Path(path).parent
    return send_from_directory(
        directory,
        Path(path).name,
        as_attachment=True,
        download_name=metadata.get("original_name") or Path(path).name,
    )


def maybe_proactive(force: bool = False) -> dict[str, Any] | None:
    profile = store.get_setting("profile", {}) or {}
    enabled = bool(profile.get("proactive_enabled", cfg.proactive_enabled))
    if not enabled or not ai.ready:
        return None
    today = now_local().date().isoformat()
    if store.get_setting(f"proactive:{today}", 0) >= 2:
        return None
    history = store.list_messages(limit=30)
    if history:
        try:
            last = datetime.fromisoformat(history[-1]["created_at"])
            idle_minutes = (
                datetime.now(timezone.utc) - last.astimezone(timezone.utc)
            ).total_seconds() / 60
            if idle_minutes < cfg.proactive_idle_minutes and not force:
                return None
        except (ValueError, TypeError):
            pass
    if not force and random.random() > 0.08:
        return None
    try:
        reply = ai.chat(
            [
                {
                    "role": "system",
                    "content": build_system_prompt("")
                    + "\n现在可以主动发一条自然的短消息，不要说明这是定时任务。",
                },
                *ai_history(limit=30),
            ],
            temperature=1.05,
            max_tokens=180,
        )
    except IntegrationError:
        return None
    message = store.create_message(
        "assistant", reply, metadata={"proactive": True}
    )
    count = int(store.get_setting(f"proactive:{today}", 0) or 0)
    store.set_setting(f"proactive:{today}", count + 1)
    return message


@app.get("/api/events")
def events():
    return jsonify({"message": maybe_proactive(force=False)})


def valid_cron_request() -> bool:
    if not cfg.cron_secret:
        return False
    provided = request.headers.get("Authorization", "").removeprefix("Bearer ")
    return hmac.compare_digest(provided, cfg.cron_secret)


@app.post("/api/cron/tick")
def cron_tick():
    if not valid_cron_request():
        return json_error("无权执行定时任务", 401)
    awarded = evaluate_rewards()
    quote = daily_quote_value()
    proactive = maybe_proactive(force=False)
    local = now_local()
    settled = None
    if local.hour >= 22 and not store.get_setting(
        f"reward_settled:{local.date().isoformat()}", False
    ):
        balance = reward_summary()["balance"]
        if balance > 0:
            store.create_item(
                {
                    "kind": "reward_spend",
                    "title": "自动转入购物基金",
                    "value": balance,
                }
            )
            settled = store.create_item(
                {
                    "kind": "shopping_fund",
                    "title": "每日积分结转",
                    "value": balance,
                }
            )
            store.set_setting(
                f"reward_settled:{local.date().isoformat()}", True
            )
    return jsonify(
        {
            "ok": True,
            "awarded": len(awarded),
            "quote": quote["content"],
            "proactive": bool(proactive),
            "settled": settled,
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
