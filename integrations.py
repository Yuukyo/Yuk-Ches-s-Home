from __future__ import annotations

import base64
import io
import json
import random
import re
import zipfile
from dataclasses import dataclass
from typing import Any

import requests


class IntegrationError(RuntimeError):
    pass


def _text_from_mcp(payload: dict[str, Any]) -> str:
    result = payload.get("result") or {}
    if result.get("isError"):
        detail = "\n".join(
            part.get("text", "")
            for part in (result.get("content") or [])
            if isinstance(part, dict) and part.get("type") == "text"
        ).strip()
        raise IntegrationError(detail or "MCP 工具返回错误")
    parts = result.get("content") or []
    texts = [part.get("text", "") for part in parts if part.get("type") == "text"]
    if texts:
        return "\n".join(text for text in texts if text).strip()
    structured = result.get("structuredContent")
    return json.dumps(structured, ensure_ascii=False) if structured is not None else ""


class AIClient:
    def __init__(self, url: str, key: str, model: str) -> None:
        self.url = url.rstrip("/")
        self.key = key
        self.model = model

    @property
    def ready(self) -> bool:
        return bool(self.url and self.key and self.model)

    @property
    def endpoint(self) -> str:
        if self.url.endswith("/chat/completions"):
            return self.url
        if self.url.endswith("/v1"):
            return f"{self.url}/chat/completions"
        return f"{self.url}/v1/chat/completions"

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.9,
        max_tokens: int | None = None,
    ) -> str:
        if not self.ready:
            raise IntegrationError("聊天 API 尚未配置")
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens:
            body["max_tokens"] = max_tokens
        try:
            response = requests.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.key}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=(15, 150),
            )
        except requests.Timeout as error:
            raise IntegrationError("AI 响应超时，请稍后再试") from error
        except requests.RequestException as error:
            raise IntegrationError("无法连接聊天 API") from error
        if not response.ok:
            detail = response.text[:300]
            raise IntegrationError(
                f"聊天 API 返回 {response.status_code}：{detail}"
            )
        try:
            content = (
                response.json()["choices"][0]["message"]["content"]
            )
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise IntegrationError("聊天 API 返回格式无法识别") from error
        if isinstance(content, list):
            content = "".join(
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            )
        answer = str(content).strip()
        if not answer:
            raise IntegrationError("AI 没有返回文字")
        return answer

    def short_text(self, system: str, prompt: str, fallback: str) -> str:
        try:
            return self.chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                temperature=1.0,
                max_tokens=160,
            )
        except IntegrationError:
            return fallback

    def suggest_points(self, title: str) -> int:
        text = self.short_text(
            "你只输出一个 1 到 50 的整数，按事项的难度、耗时和坚持成本评估积分。",
            f"给这件事设置积分：{title}",
            "5",
        )
        match = re.search(r"\d+", text)
        return min(max(int(match.group()) if match else 5, 1), 50)


class MCPClient:
    """Minimal Streamable HTTP MCP client with graceful fallback."""

    protocol_version = "2025-06-18"

    def __init__(
        self,
        url: str,
        token: str = "",
        enabled: bool = False,
        label: str = "MCP 服务",
    ) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.enabled = enabled and bool(url)
        self.label = label

    def _headers(self, session_id: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        return headers

    @staticmethod
    def _parse(response: requests.Response) -> dict[str, Any]:
        if not response.content:
            return {"accepted": True}
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json()
        for line in response.text.splitlines():
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload and payload != "[DONE]":
                    value = json.loads(payload)
                    if isinstance(value, dict) and (
                        "result" in value or "error" in value
                    ):
                        return value
        raise IntegrationError(f"{self.label}返回了无法识别的 MCP 响应")

    def _post(
        self, payload: dict[str, Any], session_id: str | None = None
    ) -> tuple[dict[str, Any], str | None]:
        try:
            response = requests.post(
                self.url,
                headers=self._headers(session_id),
                json=payload,
                timeout=(10, 60),
            )
        except requests.RequestException as error:
            raise IntegrationError(f"无法连接{self.label}") from error
        if response.status_code == 401:
            raise IntegrationError(
                f"{self.label}需要 OAuth/Bearer 授权，请配置访问令牌"
            )
        if not response.ok:
            raise IntegrationError(
                f"{self.label}返回 {response.status_code}"
            )
        return self._parse(response), response.headers.get("Mcp-Session-Id")

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        if not self.enabled:
            return ""
        init, session_id = self._post(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": self.protocol_version,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "yuk-ches-home",
                        "version": "1.0.0",
                    },
                },
            }
        )
        if init.get("error"):
            raise IntegrationError(str(init["error"].get("message", "初始化失败")))
        self._post(
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
            session_id,
        )
        result, _ = self._post(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
            session_id,
        )
        if result.get("error"):
            raise IntegrationError(
                str(result["error"].get("message", "工具调用失败"))
            )
        return _text_from_mcp(result)

    def list_tools(self) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        init, session_id = self._post(
            {
                "jsonrpc": "2.0",
                "id": 11,
                "method": "initialize",
                "params": {
                    "protocolVersion": self.protocol_version,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "yuk-ches-home",
                        "version": "1.0.0",
                    },
                },
            }
        )
        if init.get("error"):
            raise IntegrationError(
                str(init["error"].get("message", "初始化失败"))
            )
        self._post(
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
            session_id,
        )
        result, _ = self._post(
            {
                "jsonrpc": "2.0",
                "id": 12,
                "method": "tools/list",
                "params": {},
            },
            session_id,
        )
        if result.get("error"):
            raise IntegrationError(
                str(result["error"].get("message", "读取工具列表失败"))
            )
        return (result.get("result") or {}).get("tools") or []

    def recall(self, query: str) -> str:
        if not self.enabled:
            return ""
        surfaced = self.call_tool("breath", {})
        searched = self.call_tool(
            "breath_search", {"query": query[:500], "max_results": 5}
        )
        return "\n".join(part for part in (surfaced, searched) if part)[:12000]

    def remember(self, transcript: str) -> str:
        if not self.enabled:
            return ""
        if len(transcript) > 500:
            return self.call_tool("grow", {"content": transcript[:12000]})
        return self.call_tool("hold", {"content": transcript[:12000]})

    def status(self) -> dict[str, Any]:
        if not self.enabled:
            return {"enabled": False, "ok": False, "message": "未启用"}
        try:
            result = self.call_tool("pulse", {})
            return {"enabled": True, "ok": True, "message": result[:500]}
        except IntegrationError as error:
            return {"enabled": True, "ok": False, "message": str(error)}


class OmbreBrainClient(MCPClient):
    """Ombre Brain lives inside the app's memory system."""

    def __init__(self, url: str, token: str = "", enabled: bool = False) -> None:
        super().__init__(
            url,
            token,
            enabled=enabled,
            label="Ombre Brain",
        )


@dataclass
class CoReadingClient:
    base_url: str
    mcp_url: str = ""
    token: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.base_url or self.mcp_url)

    @property
    def mcp(self) -> MCPClient:
        endpoint = self.mcp_url or (
            f"{self.base_url.rstrip('/')}/mcp" if self.base_url else ""
        )
        return MCPClient(
            endpoint,
            self.token,
            enabled=bool(endpoint),
            label="co-reading-mcp",
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        if not self.enabled:
            raise IntegrationError("co-reading-mcp 尚未配置")
        if not self.base_url:
            raise IntegrationError("co-reading-mcp REST 地址尚未配置")
        try:
            response = requests.request(
                method,
                f"{self.base_url.rstrip('/')}{path}",
                params=params,
                json=json_body,
                headers=(
                    {"Authorization": f"Bearer {self.token}"}
                    if self.token
                    else None
                ),
                timeout=(10, 60),
            )
        except requests.RequestException as error:
            raise IntegrationError("无法连接 co-reading-mcp") from error
        if not response.ok:
            raise IntegrationError(
                f"co-reading-mcp 返回 {response.status_code}"
            )
        return response.json()

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        return self.mcp.call_tool(name, arguments)

    def status(self) -> dict[str, Any]:
        if not self.enabled:
            return {"enabled": False, "ok": False, "message": "未启用"}
        try:
            tools = self.mcp.list_tools()
            return {
                "enabled": True,
                "ok": True,
                "message": f"已连接，共 {len(tools)} 个阅读工具",
                "tools": [tool.get("name") for tool in tools],
            }
        except IntegrationError as error:
            return {"enabled": True, "ok": False, "message": str(error)}


class ImageClient:
    """NovelAI and OpenAI-compatible image generation adapter."""

    def __init__(
        self,
        provider: str,
        url: str,
        key: str,
        model: str,
        *,
        sampler: str = "k_euler_ancestral",
        steps: int = 28,
        scale: float = 5.0,
    ) -> None:
        self.provider = provider
        self.url = url.rstrip("/")
        self.key = key
        self.model = model
        self.sampler = sampler
        self.steps = steps
        self.scale = scale

    @property
    def ready(self) -> bool:
        return bool(self.provider and self.url and self.key and self.model)

    def generate(
        self,
        prompt: str,
        *,
        negative_prompt: str = "",
        width: int = 832,
        height: int = 1216,
        seed: int | None = None,
    ) -> dict[str, Any]:
        if not self.ready:
            raise IntegrationError("生图 API 尚未配置")
        width = min(max(int(width), 256), 1536)
        height = min(max(int(height), 256), 1536)
        if self.provider in {"novelai", "nai"}:
            return self._generate_nai(
                prompt,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                seed=seed,
            )
        return self._generate_openai(prompt, width=width, height=height)

    def _generate_openai(
        self, prompt: str, *, width: int, height: int
    ) -> dict[str, Any]:
        endpoint = (
            self.url
            if self.url.endswith("/images/generations")
            else f"{self.url}/v1/images/generations"
        )
        try:
            response = requests.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {self.key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "size": f"{width}x{height}",
                    "response_format": "b64_json",
                },
                timeout=(15, 240),
            )
        except requests.RequestException as error:
            raise IntegrationError("无法连接生图 API") from error
        if not response.ok:
            raise IntegrationError(
                f"生图 API 返回 {response.status_code}：{response.text[:240]}"
            )
        data = response.json().get("data") or []
        if not data:
            raise IntegrationError("生图 API 没有返回图片")
        first = data[0]
        return {
            "base64": first.get("b64_json"),
            "url": first.get("url"),
            "provider": self.provider,
        }

    def _generate_nai(
        self,
        prompt: str,
        *,
        negative_prompt: str,
        width: int,
        height: int,
        seed: int | None,
    ) -> dict[str, Any]:
        endpoint = (
            self.url
            if self.url.endswith("/ai/generate-image")
            else f"{self.url}/ai/generate-image"
        )
        try:
            response = requests.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {self.key}",
                    "Content-Type": "application/json",
                },
                json={
                    "action": "generate",
                    "input": prompt,
                    "model": self.model,
                    "parameters": {
                        "width": width,
                        "height": height,
                        "scale": self.scale,
                        "sampler": self.sampler,
                        "steps": self.steps,
                        "seed": (
                            seed
                            if seed is not None
                            else random.randint(0, 2**32 - 1)
                        ),
                        "n_samples": 1,
                        "ucPreset": 0,
                        "qualityToggle": True,
                        "negative_prompt": negative_prompt,
                    },
                },
                timeout=(15, 300),
            )
        except requests.RequestException as error:
            raise IntegrationError("无法连接 NovelAI") from error
        if not response.ok:
            raise IntegrationError(
                f"NovelAI 返回 {response.status_code}：{response.text[:240]}"
            )
        raw = response.content
        content_type = response.headers.get("content-type", "")
        if "zip" in content_type or raw.startswith(b"PK"):
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                image_name = next(
                    (
                        name
                        for name in archive.namelist()
                        if name.lower().endswith(
                            (".png", ".jpg", ".jpeg", ".webp")
                        )
                    ),
                    None,
                )
                if not image_name:
                    raise IntegrationError("NovelAI 压缩包中没有图片")
                raw = archive.read(image_name)
        return {
            "base64": base64.b64encode(raw).decode("ascii"),
            "url": None,
            "provider": "novelai",
        }


def weather_now(latitude: str, longitude: str, location: str) -> dict[str, Any]:
    codes = {
        0: "晴",
        1: "大致晴朗",
        2: "多云",
        3: "阴",
        45: "雾",
        48: "雾凇",
        51: "小毛毛雨",
        53: "毛毛雨",
        55: "强毛毛雨",
        61: "小雨",
        63: "中雨",
        65: "大雨",
        71: "小雪",
        73: "中雪",
        75: "大雪",
        80: "阵雨",
        81: "阵雨",
        82: "强阵雨",
        95: "雷雨",
    }
    try:
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,weather_code",
                "timezone": "auto",
            },
            timeout=(5, 12),
        )
        response.raise_for_status()
        current = response.json().get("current") or {}
        code = int(current.get("weather_code", -1))
        return {
            "location": location,
            "temperature": current.get("temperature_2m"),
            "condition": codes.get(code, "天气未知"),
            "source": "Open-Meteo",
        }
    except (requests.RequestException, TypeError, ValueError):
        return {
            "location": location,
            "temperature": None,
            "condition": random.choice(["风很轻", "窗外安静", "适合待在家"]),
            "source": "fallback",
        }
