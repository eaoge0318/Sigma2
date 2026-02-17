from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
import json
from backend.services.analysis.analysis_types import (
    AnalysisContext,
    AnalysisState,
    RoleInput,
    RoleOutput,
)


class BaseRole(ABC):
    def __init__(self, llm: Any):
        self.llm = llm

    @abstractmethod
    async def execute(self, input_data: RoleInput) -> RoleOutput:
        """
        Execute the role's logic.
        """
        pass

    async def _call_llm(self, sys_prompt: str, user_prompt: str) -> str:
        """
        Standardized LLM call wrapper. Supports both Chat and Completion interfaces.
        """
        try:
            # Try chat interface first (preferred for instructions)
            if hasattr(self.llm, "achat"):
                from llama_index.core.llms import ChatMessage, MessageRole

                messages = [
                    ChatMessage(role=MessageRole.SYSTEM, content=sys_prompt),
                    ChatMessage(role=MessageRole.USER, content=user_prompt),
                ]
                response = await self.llm.achat(messages)
                return response.message.content

            # Fallback to completion interface
            full_prompt = f"System Instruction: {sys_prompt}\n\nUser Query: {user_prompt}\n\nResponse:"
            response = await self.llm.acomplete(full_prompt)
            return response.text

        except Exception as e:
            # Last ditch effort: simple string
            print(f"LLM call error: {e}, falling back to simple prompt")
            return "Error calling LLM"

    def _parse_json(self, response: str) -> Dict[str, Any]:
        """
        三層容錯的 JSON 解析器
        Layer 1: 直接解析
        Layer 2: 提取 markdown 包裝的 JSON
        Layer 3: LLM 自我修正 (同步版本，避免 async 污染)
        """
        import re

        # Layer 1: 直接解析
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # Layer 2: 提取 markdown 包裝的 JSON (支援 ```json 和 ``` 兩種格式)
        patterns = [
            r"```json\s*(\{.*?\})\s*```",  # ```json { ... } ```
            r"```\s*(\{.*?\})\s*```",  # ``` { ... } ```
            r"\{.*?\}",  # 直接找第一個完整的 JSON 物件
        ]

        for pattern in patterns:
            match = re.search(pattern, response, re.DOTALL)
            if match:
                try:
                    json_str = match.group(1) if match.lastindex else match.group(0)
                    return json.loads(json_str)
                except (json.JSONDecodeError, IndexError):
                    continue

        # Layer 3: 嘗試提取 { } 之間的內容並修正常見錯誤
        try:
            start = response.find("{")
            end = response.rfind("}") + 1
            if start != -1 and end > start:
                json_str = response[start:end]
                # 移除常見的非法字符（例如尾隨逗號、註解）
                json_str = re.sub(r",\s*}", "}", json_str)  # 移除尾隨逗號
                json_str = re.sub(r",\s*]", "]", json_str)
                json_str = re.sub(r"//.*?\n", "\n", json_str)  # 移除單行註解
                return json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            pass

        # Final fallback: 回傳錯誤結構
        print(f"[JSON Parse Error] Failed to parse LLM response: {response[:200]}...")
        return {
            "error": "JSON parsing failed after 3 layers",
            "decision": "WAIT",
            "reasoning": "LLM 回傳格式錯誤，請重試。",
        }
