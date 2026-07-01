from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from supabase import create_client
import requests
import os
app = Flask(__name__)
CORS(app)
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL else None
@app.route("/")
def index():
    return render_template("index.html")
@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    user_msg = data.get("message", "")
    if supabase:
        supabase.table("messages").insert({"role": "user", "content": user_msg}).execute()
    return jsonify({"reply": "我在。家还在装修，先将就一下。"})
if __name__ == "__main__":
    app.run(debug=True)
