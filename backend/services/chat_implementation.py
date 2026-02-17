
    @llm_chat_callback()
    def chat(self, messages: list[ChatMessage], **kwargs: Any) -> ChatResponse:
        is_openai = "/v1/chat/completions" in self.api_url
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": m.role.value, "content": m.content} for m in messages
            ],
            "stream": False,
        }
        try:
            response = requests.post(self.api_url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            result = response.json()
            if is_openai:
                content = result["choices"][0]["message"]["content"]
            else:
                content = result.get("message", {}).get("content", "")
            return ChatResponse(
                message=ChatMessage(role="assistant", content=content),
                raw=result,
            )
        except Exception as e:
            provider = "OpenAI/VLLM" if is_openai else "Ollama"
            logger.error(f"{provider} Sync Chat 連線錯誤: {str(e)}")
            raise ConnectionError(f"無法同步 Chat 連線至 {provider}: {str(e)}")

    @llm_chat_callback()
    def stream_chat(
        self, messages: list[ChatMessage], **kwargs: Any
    ) -> ChatResponseGen:
        # 簡單實現：呼叫 complete 模擬
        # 實際應用中若要串流，需參考 astream_chat
        # 這裡為了簡化，暫時使用同步調用（通常 LlamaIndex 主要用 async）
        response = self.chat(messages, **kwargs)
        yield response

    @llm_chat_callback()
    async def achat(
        self, messages: list[ChatMessage], **kwargs: Any
    ) -> ChatResponse:
        is_openai = "/v1/chat/completions" in self.api_url
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": m.role.value, "content": m.content} for m in messages
            ],
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.api_url, json=payload)
                response.raise_for_status()
                result = response.json()
                if is_openai:
                    content = result["choices"][0]["message"]["content"]
                else:
                    content = result.get("message", {}).get("content", "")
                return ChatResponse(
                    message=ChatMessage(role="assistant", content=content),
                    raw=result,
                )
        except Exception as e:
            provider = "OpenAI/VLLM" if is_openai else "Ollama"
            logger.error(f"{provider} Async Chat 連線錯誤: {str(e)}")
            raise ConnectionError(f"無法非同步 Chat 連線至 {provider}: {str(e)}")

    @llm_chat_callback()
    async def astream_chat(
        self, messages: list[ChatMessage], **kwargs: Any
    ) -> ChatResponseGen:
        is_openai = "/v1/chat/completions" in self.api_url
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": m.role.value, "content": m.content} for m in messages
            ],
            "stream": True,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST", self.api_url, json=payload
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        
                        if is_openai:
                            if line.startswith("data: "):
                                data_str = line[6:].strip()
                                if data_str == "[DONE]":
                                    break
                                try:
                                    chunk = json.loads(data_str)
                                    if len(chunk["choices"]) > 0:
                                        delta = chunk["choices"][0]["delta"]
                                        content = delta.get("content", "")
                                        if content:
                                            yield ChatResponse(
                                                message=ChatMessage(role="assistant", content=content),
                                                delta=content
                                            )
                                except json.JSONDecodeError:
                                    pass
                        else:
                            try:
                                chunk = json.loads(line)
                                if "message" in chunk:
                                    content = chunk["message"].get("content", "")
                                    yield ChatResponse(
                                        message=ChatMessage(role="assistant", content=content),
                                        delta=content
                                    )
                                if chunk.get("done"):
                                    break
                            except json.JSONDecodeError:
                                pass
        except Exception as e:
            provider = "OpenAI/VLLM" if is_openai else "Ollama"
            logger.error(f"{provider} Async Stream Chat 連線錯誤: {str(e)}")
            raise ConnectionError(f"無法串流 Chat 連線至 {provider}: {str(e)}")
