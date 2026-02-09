# 03. API 路由设计

> 基于模块化架构的 RESTful API 设计

---

## API 端点总览

| 端点 | 方法 | 用途 | 认证 |
|------|------|------|------|
| `/api/analysis/prepare` | POST | 建立文件分析索引 | session_id |
| `/api/analysis/chat` | POST | 智能对话分析 (一次性) | session_id |
| `/api/analysis/chat/stream` | POST | 智能对话分析 (SSE串流) | session_id |
| `/api/analysis/stop_generation` | POST | 停止生成 | session_id |
| `/api/analysis/files` | GET | 获取可分析文件列表 | session_id |
| `/api/analysis/summary/{file_id}` | GET | 获取文件摘要信息 | session_id |
| `/api/analysis/clear-session` | DELETE | 清除对话历史 | session_id |
| `/api/analysis/tools` | GET | 获取可用工具列表 | 无 |

---

## 完整代码实现

### `backend/routers/analysis_router.py` (~200行)

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import logging

from backend.dependencies import (
    get_analysis_service,
    get_llm_agent,
    get_file_service
)
from backend.services.analysis import AnalysisService, LLMAnalysisAgent
from backend.services.file_service import FileService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analysis", tags=["智能分析"])

# ==================== 请求/响应模型 ====================

class PrepareRequest(BaseModel):
    """索引准备请求"""
    filename: str
    session_id: str = "default"

class PrepareResponse(BaseModel):
    """索引准备响应"""
    status: str
    message: str
    file_id: str
    summary: Dict[str, Any]

class ChatRequest(BaseModel):
    """对话请求"""
    session_id: str
    file_id: str
    message: str
    conversation_id: str = "default"

class ChatResponse(BaseModel):
    """对话响应"""
    response: str
    tool_used: Optional[str] = None
    tool_params: Optional[Dict] = None
    tool_result: Optional[Dict] = None

class FileInfo(BaseModel):
    """文件信息"""
    file_id: str
    filename: str
    is_indexed: bool
    created_at: Optional[str] = None

class FilesResponse(BaseModel):
    """文件列表响应"""
    files: List[FileInfo]

class ToolInfo(BaseModel):
    """工具信息"""
    name: str
    display_name: str
    description: str
    category: str
    required_params: List[str]

class ToolsResponse(BaseModel):
    """工具列表响应"""
    tools: List[ToolInfo]

# ==================== API 端点 ====================

@router.post("/prepare", response_model=PrepareResponse)
async def prepare_file(
    request: PrepareRequest,
    analysis_service: AnalysisService = Depends(get_analysis_service),
    file_service: FileService = Depends(get_file_service)
):
    """
    为CSV文件建立分析索引
    
    这是一次性操作，会生成：
    - summary.json: 文件摘要
    - statistics.json: 统计信息
    - correlations.json: 相关性矩阵
    - semantic_index.json: 语义索引
    """
    try:
        # 获取文件路径
        user_path = file_service.get_user_path(request.session_id, "uploads")
        csv_path = f"{user_path}/{request.filename}"
        
        # 建立索引
        summary = await analysis_service.build_analysis_index(
            csv_path=csv_path,
            session_id=request.session_id,
            filename=request.filename
        )
        
        return PrepareResponse(
            status="success",
            message="索引建立完成",
            file_id=summary['file_id'],
            summary=summary
        )
    
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"文件未找到: {request.filename}")
    except Exception as e:
        logger.error(f"索引建立失败: {e}")
        raise HTTPException(status_code=500, detail=f"索引建立失败: {str(e)}")

@router.post("/stop_generation")
async def stop_generation_endpoint(
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_analysis_service),
):
    """
    停止當前的 AI 生成過程
    """
    analysis_service.stop_generation(session_id)
    return {"status": "success", "message": "Stop signal sent"}


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    analysis_service: AnalysisService = Depends(get_analysis_service),
    workflow: SigmaAnalysisWorkflow = Depends(get_analysis_workflow)
):
    """
    智慧對話分析 (Workflow 模式)
    """
    try:
        # 清除之前的停止信號
        analysis_service.clear_stop_signal(request.session_id)
        
        # 執行工作流
        result = await workflow.run(
            session_id=request.session_id,
            file_id=request.file_id,
            query=request.user_question
        )
        return result
    
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="文件索引未找到，请先准备文件")
    except Exception as e:
        logger.error(f"对话分析失败: {e}")
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    analysis_service: AnalysisService = Depends(get_analysis_service),
    workflow: SigmaAnalysisWorkflow = Depends(get_analysis_workflow)
):
    """
    智慧對話分析 (SSE 串流 - Workflow 驅動)
    """
    try:
        # 清除之前的停止信號
        analysis_service.clear_stop_signal(request.session_id)

        # 啟動工作流處理器 (Workflow Handler)
        handler = workflow.run(
            session_id=request.session_id,
            file_id=request.file_id,
            query=request.user_question
        )

        return EventSourceResponse(workflow.stream_results(handler, request.session_id))


@router.get("/files", response_model=FileListResponse)
async def list_analysis_files(
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
    file_service: FileService = Depends(get_file_service) # Keep file_service for uploaded files
):
    """
    獲取當前用戶可分析的文件列表
    返回已上傳的CSV文件及其分析狀態
    Response:
    - filename: 文件名
    - file_id: 文件ID (hash)
    - size: 文件大小
    - is_indexed: 是否已建立分析索引
    - status: "ready" | "not_prepared"
    """
    try:
        # 获取已上传的文件
        uploaded_files = await file_service.list_files(session_id)
        
        files = []
        for file_info in uploaded_files.get('files', []):
            filename = file_info['name']
            
            # 检查是否已建立索引
            file_id = analysis_service.get_file_id(filename)
            analysis_path = analysis_service.get_analysis_path(session_id, file_id)
            summary_file = analysis_path / "summary.json"
            is_indexed = summary_file.exists()
            
            files.append(FileListItem( # Changed to FileListItem
                file_id=file_id,
                filename=filename,
                is_indexed=is_indexed,
                size=file_info.get('size', 0), # Assuming size is available
                status="ready" if is_indexed else "not_prepared"
            ))
        
        return FileListResponse(files=files) # Changed to FileListResponse
    
    except Exception as e:
        logger.error(f"获取文件列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取文件列表失败: {str(e)}")


@router.get("/summary/{file_id}")
async def get_summary(
    file_id: str,
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_analysis_service)
):
    """
    获取文件的分析摘要
    
    包含：
    - 基本信息（行数、列数）
    - 参数列表
    - 参数分类
    """
    try:
        summary = analysis_service.load_summary(session_id, file_id)
        return summary
    
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="文件摘要未找到，请先准备文件")
    except Exception as e:
        logger.error(f"获取摘要失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取摘要失败: {str(e)}")


@router.delete("/clear-session")
async def clear_session(
    session_id: str = Query("default"),
    conversation_id: str = Query("default")
):
    """
    清除对话历史
    
    注意：这只清除对话上下文，不删除文件索引
    """
    try:
        # TODO: 实现对话历史管理
        # 目前简化版Agent没有维护对话历史
        return {"status": "success", "message": "对话历史已清除"}
    
    except Exception as e:
        logger.error(f"清除会话失败: {e}")
        raise HTTPException(status_code=500, detail=f"清除会话失败: {str(e)}")


@router.get("/tools", response_model=ToolsResponse)
async def list_tools():
    """
    获取所有可用的分析工具列表
    
    用于前端展示工具说明
    """
    tools = [
        # 数据查询工具
        ToolInfo(
            name="get_parameter_list",
            display_name="字段列表",
            description="获取数据集的所有字段，支持关键字过滤",
            category="数据查询",
            required_params=["file_id"]
        ),
        ToolInfo(
            name="get_parameter_statistics",
            display_name="字段统计",
            description="获取指定字段的详细统计信息",
            category="数据查询",
            required_params=["file_id", "parameter"]
        ),
        ToolInfo(
            name="search_parameters_by_concept",
            display_name="概念搜索",
            description="根据关键词（如价格、面积、成交量）智能搜索相关字段",
            category="数据查询",
            required_params=["file_id", "concept"]
        ),
        
        # 统计分析工具
        ToolInfo(
            name="calculate_correlation",
            display_name="计算相关性",
            description="计算字段间的相关系数（Pearson/Spearman）",
            category="统计分析",
            required_params=["file_id", "parameters"]
        ),
        ToolInfo(
            name="get_top_correlations",
            display_name="Top相关性",
            description="快速获取与目标变量相关性最强的参数",
            category="统计分析",
            required_params=["file_id", "target"]
        ),
        ToolInfo(
            name="compare_groups",
            display_name="组间比较",
            description="比较不同条件下字段的差异（t-test）",
            category="统计分析",
            required_params=["file_id", "parameter", "group_by"]
        ),
    ]
    
    return ToolsResponse(tools=tools)
```

---

## 使用示例

### 1. 准备文件索引

```javascript
// 前端调用
const response = await fetch('/api/analysis/prepare', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
        filename: 'production_data.csv',
        session_id: 'user123'
    })
});

const result = await response.json();
console.log(result.file_id);  // "a3b8c9d2e4f5"
```

### 2. 智能对话

```javascript
const response = await fetch('/api/analysis/chat', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
        session_id: 'user123',
        file_id: 'a3b8c9d2e4f5',
        message: '温度相关的参数有哪些？'
    })
});

const result = await response.json();
/*
{
    "response": "找到12个价格相关字段：售价、成交价、评估价...",
    "tool_used": "search_parameters_by_concept",
    "tool_params": {"concept": "温度"},
    "tool_result": {...}
}
*/
```

### 3. 智能对话 (SSE串流)

```javascript
const response = await fetch('/api/analysis/chat/stream', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ ... })
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
    const {value, done} = await reader.read();
    if (done) break;
    const chunk = decoder.decode(value);
    // Parse SSE data: ...
}
```

### 4. 获取文件列表

```javascript
const response = await fetch('/api/analysis/files?session_id=user123');
const result = await response.json();
/*
{
    "files": [
        {
            "file_id": "a3b8c9d2e4f5",
            "filename": "production_data.csv",
            "is_indexed": true
        }
    ]
}
*/
```

---

## 错误处理

### 标准错误响应

```json
{
    "detail": "错误描述信息"
}
```

### 常见错误码

| 状态码 | 说明 | 处理建议 |
|--------|------|---------|
| 404 | 文件或索引未找到 | 检查file_id，或先调用/prepare |
| 500 | 服务器内部错误 | 查看日志，重试 |

---

## 性能考虑

### 1. 索引缓存
- 索引只生成一次
- 后续查询直接读取JSON

### 2. 异步处理（可选优化）
```python
# 可以改为后台任务
@router.post("/prepare")
async def prepare_file(...):
    task_id = start_background_task(build_index, ...)
    return {"task_id": task_id, "status": "processing"}
```

---

## 依赖注入配置

### 在 `backend/dependencies.py` 中添加

```python
from backend.services.analysis import AnalysisService, LLMAnalysisAgent
from backend.services.analysis.tools import ToolExecutor

_analysis_service = None
_tool_executor = None
_llm_agent = None

def get_analysis_service():
    global _analysis_service
    if _analysis_service is None:
        _analysis_service = AnalysisService()
    return _analysis_service

def get_tool_executor():
    global _tool_executor
    if _tool_executor is None:
        _tool_executor = ToolExecutor(get_analysis_service())
    return _tool_executor

def get_llm_agent():
    global _llm_agent
    if _llm_agent is None:
        _llm_agent = LLMAnalysisAgent(get_tool_executor())
    return _llm_agent
```

### 在 `api_entry.py` 中注册路由

```python
from backend.routers import analysis_router

app.include_router(analysis_router.router)
```

---

## 下一步

查看 **[04_frontend.md](./04_frontend.md)** 了解前端实现。
