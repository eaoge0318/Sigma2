# Part 2: LLM Agent 实现方案

## 核心架构

基于您现有的 `LLMReporter` 类，我们将创建一个专门的 `LLMAnalysisAgent`，负责：
1. 管理与 Ollama 的对话
2. 解析用户意图
3. 调用合适的分析工具
4. 组织和返回结果

## 1. LLM Analysis Agent (`llm_analysis_agent.py`)

```python
# backend/services/llm_analysis_agent.py

import json
import logging
from typing import Dict, List, Any
from core_logic.llm_reporter import LLMReporter
from backend.services.analysis_tool_executor import AnalysisToolExecutor
import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LLMAnalysisAgent:
    """
    智能分析 LLM Agent
    基于现有的 LLMReporter，扩展支持工具调用
    """
    
    def __init__(self, tool_executor: AnalysisToolExecutor):
        self.llm = LLMReporter()
        self.tool_executor = tool_executor
        self.conversation_sessions = {}  # {session_key: messages}
    
    def chat(self, 
             session_id: str, 
             file_id: str, 
             user_message: str,
             conversation_id: str = "default") -> Dict:
        """
        处理用户的分析请求
        
        Args:
            session_id: 用户会话ID
            file_id: 分析的文件ID
            user_message: 用户消息
            conversation_id: 对话ID（用于多轮对话）
        
        Returns:
            包含回复和工具调用记录的字典
        """
        session_key = f"{session_id}_{conversation_id}"
        
        # 初始化或获取对话历史
        if session_key not in self.conversation_sessions:
            self.conversation_sessions[session_key] = [
                {
                    "role": "system",
                    "content": self._build_system_prompt(session_id, file_id)
                }
            ]
        
        messages = self.conversation_sessions[session_key]
        
        # 添加用户消息
        messages.append({
            "role": "user",
            "content": user_message
        })
        
        # 工具调用循环（最多3轮）
        max_iterations = 3
        tool_calls_log = []
        
        for iteration in range(max_iterations):
            # 调用 Ollama
            response_text = self._call_ollama(messages, session_id, file_id)
            
            # 解析是否需要调用工具
            tool_request = self._parse_tool_request(response_text)
            
            if not tool_request:
                # 没有工具调用，直接返回结果
                messages.append({
                    "role": "assistant",
                    "content": response_text
                })
                
                return {
                    "response": response_text,
                    "tool_calls": tool_calls_log,
                    "iterations": iteration + 1
                }
            
            # 执行工具
            tool_name = tool_request["tool"]
            tool_params = tool_request["params"]
            
            logger.info(f"Calling tool: {tool_name} with params: {tool_params}")
            
            try:
                tool_result = self.tool_executor.execute_tool(
                    tool_name, 
                    tool_params, 
                    session_id
                )
                
                tool_calls_log.append({
                    "tool": tool_name,
                    "params": tool_params,
                    "result": tool_result
                })
                
                # 将工具结果注入对话
                messages.append({
                    "role": "assistant",
                    "content": f"[调用工具: {tool_name}]"
                })
                messages.append({
                    "role": "user",
                    "content": f"工具执行结果:\n{json.dumps(tool_result, ensure_ascii=False, indent=2)}\n\n请基于这个结果回答我的问题。"
                })
                
            except Exception as e:
                logger.error(f"Tool execution failed: {str(e)}")
                return {
                    "response": f"工具执行失败: {str(e)}",
                    "tool_calls": tool_calls_log,
                    "error": True
                }
        
        # 达到最大迭代次数
        return {
            "response": "分析过程过于复杂，请尝试简化您的问题。",
            "tool_calls": tool_calls_log,
            "max_iterations_reached": True
        }
    
    def _call_ollama(self, messages: List[Dict], session_id: str, file_id: str) -> str:
        """
        调用 Ollama API
        使用现有的 llm_reporter 连接方式
        """
        import requests
        
        payload = {
            "model": config.LLM_MODEL,
            "messages": messages,
            "stream": False,
        }
        
        try:
            response = requests.post(
                config.LLM_API_URL, 
                json=payload, 
                timeout=60.0
            )
            response.raise_for_status()
            result = response.json()
            return result.get("message", {}).get("content", "无法获取回复")
            
        except requests.exceptions.Timeout:
            return "❌ LLM 请求超时，请稍后再试"
        except requests.exceptions.ConnectionError:
            return f"❌ 无法连接到 LLM 服务: {config.LLM_API_URL}"
        except Exception as e:
            return f"❌ LLM 调用失败: {str(e)}"
    
    def _build_system_prompt(self, session_id: str, file_id: str) -> str:
        """
        构建系统提示词
        包含可用工具的说明
        """
        # 读取文件摘要
        from backend.services.analysis_service import AnalysisService
        analysis_service = AnalysisService()
        analysis_path = analysis_service.get_analysis_path(session_id, file_id)
        
        try:
            with open(analysis_path / "summary.json", 'r', encoding='utf-8') as f:
                summary = json.load(f)
            
            file_info = f"""
当前分析文件: {summary['filename']}
- 总行数: {summary['total_rows']}
- 总参数数: {summary['total_columns']}
- 参数分类: {list(summary['categories'].keys())}
"""
        except:
            file_info = "文件信息加载失败"
        
        return f"""你是一位专业的工业数据分析助手，正在帮助用户分析制程数据。

{file_info}

**你的能力:**
你可以调用以下分析工具来回答用户的问题。当需要使用工具时，请在回复中使用以下格式：

```tool
{{
  "tool": "工具名称",
  "params": {{
    "file_id": "{file_id}",
    "参数名": "参数值"
  }}
}}
```

**可用工具列表:**

1. **get_parameter_list** - 获取所有参数列表
   - 参数: keyword (可选), category (可选)

2. **get_parameter_statistics** - 获取参数统计信息
   - 参数: parameter (必需), include_distribution (可选)

3. **get_data_overview** - 获取数据总览

4. **search_parameters_by_concept** - 根据概念搜索参数
   - 参数: concept (必需), search_method (可选)

5. **calculate_correlation** - 计算相关性
   - 参数: method, parameters, target (可选)

6. **get_top_correlations** - 获取Top相关性
   - 参数: target (必需), top_n, min_correlation

7. **compare_groups** - 组间比较
   - 参数: parameter, group_by, test_type

8. **detect_outliers** - 检测异常值
   - 参数: parameter, method, threshold

9. **analyze_distribution** - 分析分布
   - 参数: parameter

10. **perform_regression** - 回归分析
    - 参数: target, features, regression_type

11. **find_temporal_patterns** - 发现时序模式
    - 参数: parameter, pattern_type

12. **find_event_patterns** - 分析事件模式
    - 参数: event_parameter, event_value, analysis_parameters, time_window

13. **cluster_analysis** - 聚类分析
    - 参数: parameters, n_clusters, method

14. **suggest_next_analysis** - 推荐下一步分析
    - 参数: current_findings, analysis_history

**重要规则:**
1. 当用户问题需要数据支持时，必须先调用相应工具
2. 回答要基于工具返回的实际数据，不要臆测
3. 对于参数代码（如 PM21_A123），只报告数据，不推测含义
4. 如果不确定用哪个工具，请先用 search_parameters_by_concept 搜索相关参数

**回答风格:**
- 简洁专业
- 数据驱动
- 提供可操作建议
"""
    
    def _parse_tool_request(self, response_text: str) -> Dict | None:
        """
        解析 LLM 回复中的工具调用请求
        
        格式:
        ```tool
        {
          "tool": "get_parameter_list",
          "params": {...}
        }
        ```
        """
        # 查找 ```tool 代码块
        if "```tool" not in response_text:
            return None
        
        try:
            # 提取 JSON
            start = response_text.find("```tool") + 7
            end = response_text.find("```", start)
            json_str = response_text[start:end].strip()
            
            tool_request = json.loads(json_str)
            
            # 验证格式
            if "tool" not in tool_request or "params" not in tool_request:
                return None
            
            return tool_request
            
        except Exception as e:
            logger.error(f"Failed to parse tool request: {str(e)}")
            return None
    
    def get_conversation_history(self, session_id: str, conversation_id: str = "default") -> List[Dict]:
        """获取对话历史"""
        session_key = f"{session_id}_{conversation_id}"
        return self.conversation_sessions.get(session_key, [])
    
    def clear_conversation(self, session_id: str, conversation_id: str = "default"):
        """清除对话历史"""
        session_key = f"{session_id}_{conversation_id}"
        if session_key in self.conversation_sessions:
            del self.conversation_sessions[session_key]
```

## 2. 简化方案：直接指令模式（推荐）

考虑到 Ollama 本地模型可能不完全支持 Function Calling，我们提供一个**简化版本**：

```python
# backend/services/llm_analysis_agent_simple.py

class LLMAnalysisAgentSimple:
    """
    简化版 LLM Agent
    使用意图识别 + 规则匹配的方式
    """
    
    def __init__(self, tool_executor: AnalysisToolExecutor):
        self.llm = LLMReporter()
        self.tool_executor = tool_executor
    
    def analyze(self, session_id: str, file_id: str, user_question: str) -> Dict:
        """
        分析用户问题并执行
        
        流程:
        1. 意图识别（调用LLM判断用户想做什么）
        2. 参数提取
        3. 执行工具
        4. 生成回答（调用LLM基于工具结果回答）
        """
        
        # Step 1: 意图识别
        intent = self._identify_intent(user_question, file_id)
        
        if not intent["tool"]:
            # 无法识别意图，直接对话
            return {
                "response": "抱歉，我不确定您想做什么分析。您可以尝试：\n- 查看参数列表\n- 分析相关性\n- 比较组间差异",
                "tool_used": None
            }
        
        # Step 2: 执行工具
        tool_result = self.tool_executor.execute_tool(
            intent["tool"],
            intent["params"],
            session_id
        )
        
        # Step 3: 生成自然语言回答
        response = self._generate_response(
            user_question,
            intent["tool"],
            tool_result
        )
        
        return {
            "response": response,
            "tool_used": intent["tool"],
            "tool_params": intent["params"],
            "tool_result": tool_result
        }
    
    def _identify_intent(self, user_question: str, file_id: str) -> Dict:
        """
        识别用户意图
        使用规则匹配 + LLM辅助
        """
        q_lower = user_question.lower()
        
        # 规则1: 参数列表
        if any(kw in q_lower for kw in ["有哪些参数", "参数列表", "所有参数"]):
            keyword = None
            # 提取关键词
            for concept in ["温度", "张力", "湿度", "速度", "品质"]:
                if concept in user_question:
                    keyword = concept
                    break
            
            return {
                "tool": "get_parameter_list",
                "params": {"file_id": file_id, "keyword": keyword}
            }
        
        # 规则2: 相关性分析
        if any(kw in q_lower for kw in ["相关", "关联", "影响"]):
            # 尝试提取参数名
            return {
                "tool": "calculate_correlation",
                "params": {"file_id": file_id, "method": "pearson"}
            }
        
        # 规则3: 比较分析
        if any(kw in q_lower for kw in ["比较", "差异", "对比"]):
            return {
                "tool": "compare_groups",
                "params": {"file_id": file_id}
            }
        
        # 规则4: 异常检测
        if any(kw in q_lower for kw in ["异常", "离群", "outlier"]):
            return {
                "tool": "detect_outliers",
                "params": {"file_id": file_id, "method": "zscore"}
            }
        
        # 规则5: 概念搜索
        if "为什么" in user_question or "哪些" in user_question:
            # 提取概念
            concepts = ["断纸", "品质", "温度", "张力", "湿度"]
            for concept in concepts:
                if concept in user_question:
                    return {
                        "tool": "search_parameters_by_concept",
                        "params": {"file_id": file_id, "concept": concept}
                    }
        
        return {"tool": None, "params": {}}
    
    def _generate_response(self, question: str, tool_name: str, tool_result: Dict) -> str:
        """
        基于工具结果生成自然语言回答
        调用 LLM
        """
        prompt = f"""用户问题: {question}

我已经使用工具 [{tool_name}] 分析了数据，结果如下:
{json.dumps(tool_result, ensure_ascii=False, indent=2)}

请用简洁专业的中文回答用户的问题。要求:
1. 直接回答问题，不要重复工具名称
2. 突出关键发现
3. 如有必要，提供建议
4. 不超过200字

回答:"""
        
        messages = [{"role": "user", "content": prompt}]
        
        import requests
        payload = {
            "model": config.LLM_MODEL,
            "messages": messages,
            "stream": False,
        }
        
        try:
            response = requests.post(config.LLM_API_URL, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
            return result.get("message", {}).get("content", "无法生成回答")
        except:
            # Fallback: 直接返回工具结果的摘要
            return self._fallback_response(tool_name, tool_result)
    
    def _fallback_response(self, tool_name: str, tool_result: Dict) -> str:
        """备用回答生成（不依赖LLM）"""
        if "error" in tool_result:
            return f"❌ 分析失败: {tool_result['error']}"
        
        if tool_name == "get_parameter_list":
            params = tool_result.get("parameters", [])
            return f"找到 {len(params)} 个参数:\n" + "\n".join(f"- {p}" for p in params[:10])
        
        elif tool_name == "calculate_correlation":
            results = tool_result.get("results", [])
            if results:
                top = results[0]
                return f"相关性分析结果:\n{top['param1']} 与 {top['param2']} 的相关系数为 {top['correlation']:.3f}"
        
        return json.dumps(tool_result, ensure_ascii=False, indent=2)
```

## 3. 推荐使用方案

**建议使用简化版 (`LLMAnalysisAgentSimple`)**，原因：
1. ✅ 不依赖 Function Calling 支持
2. ✅ 规则清晰，可控性强
3. ✅ 响应速度快
4. ✅ 容易调试和优化

**未来升级路径:**
- 当本地模型支持更好的 Function Calling 时，可切换到完整版
- 可以使用 LangChain 或 LlamaIndex 框架进一步增强

---

## 下一步

请查看 **Part 3: API 路由设计** 了解如何将这个 Agent 暴露为 API 接口。
