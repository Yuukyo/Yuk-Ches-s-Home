from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from supabase import create_client
import requests
import os
app = Flask(__name__)
CORS(app)
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
API_URL = os.environ.get("API_URL", "").rstrip("/")
API_KEY = os.environ.get("API_KEY", "")
API_MODEL = os.environ.get("API_MODEL", "")
SYSTEM_PROMPT = os.environ.get(
    "SYSTEM_PROMPT",
    "你是余天骋，正在与断云去进行自然的线上聊天。"
)
supabase = (
    create_client(SUPABASE_URL, SUPABASE_KEY)
    if SUPABASE_URL and SUPABASE_KEY
    else None
)
def get_api_endpoint():
    if API_URL.endswith("/chat/completions"):
        return API_URL
    return API_URL + "/v1/chat/completions"
def load_recent_messages(limit=30):
    if not supabase:
        return []
    try:
        result = (
            supabase.table("messages")
            .select("role,content,created_at")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        rows = result.data or []
        rows.reverse()
        return [
            {
                "role": row["role"],
                "content": row["content"]
            }
            for row in rows
            if row.get("role") in ("user", "assistant")
            and row.get("content")
        ]
    except Exception as error:
        print("读取聊天记录失败：", error)
        return []
def save_message(role, content):
    if not supabase:
        return
    try:
        supabase.table("messages").insert({
            "role": role,
            "content": content
        }).execute()
    except Exception as error:
        print("保存消息失败：", error)
@app.route("/")
def index():
    return render_template("index.html")
@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    user_msg = str(data.get("message", "")).strip()
    if not user_msg:
        return jsonify({"error": "消息不能为空"}), 400
    if not API_URL or not API_KEY or not API_MODEL:
        return jsonify({
            "error": "API尚未配置，请检查Render环境变量"
        }), 500
    history = load_recent_messages()
    save_message("user", user_msg)
    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ]
    messages.extend(history)
    messages.append({
        "role": "user",
        "content": user_msg
    })
    request_body = {
        "model": API_MODEL,
        "messages": messages,
        "temperature": 1.0,
        "stream": False
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }
    try:
        response = requests.post(
            get_api_endpoint(),
            headers=headers,
            json=request_body,
            timeout=120
        )
        if not response.ok:
            print("API错误：", response.status_code, response.text)
            return jsonify({
                "error": f"API请求失败：{response.status_code}"
            }), 502
        result = response.json()
        reply = (
            result.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        if not reply:
            return jsonify({"error": "AI没有返回内容"}), 502
        save_message("assistant", reply)
        return jsonify({"reply": reply})
    except requests.Timeout:
        return jsonify({"error": "AI响应超时，请稍后重试"}), 504
    except Exception as error:
        print("聊天接口异常：", error)
        return jsonify({"error": "后端请求出错"}), 500
if __name__ == "__main__":
    app.run(debug=True)
