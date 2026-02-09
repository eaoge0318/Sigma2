# Part 3: API 路由设计

## API 架构总览

```
/api/analysis/
├── POST   /prepare        # 为文件建立分析索引
├── POST   /chat           # 智能对话分析
├── GET    /files          # 获取可分析的文件列表
├── GET    /summary/{file_id}  # 获取文件摘要
├── DELETE /clear-session  # 清除会话历史
└── GET    /tools          # 获取可用工具列表
```

## 详细实现

### 1. 路由文件 (`analysis_router.py`)

```python
# backend/routers/analysis_router.py

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from backend.services.analysis_service import AnalysisService
from backend.services.analysis_tool_executor import AnalysisToolExecutor
from backend.services.llm_analysis_agent_simple import LLMAnalysisAgentSimple
from backend.services.file_service import FileService
from backend.dependencies import get_file_service

router = APIRouter(prefix="/api/analysis", tags=["Intelligent Analysis"])

# 全局服务实例（可以改用依赖注入）
analysis_service = AnalysisService()
tool_executor = AnalysisToolExecutor(analysis_service)
llm_agent = LLMAnalysisAgentSimple(tool_executor)


# ========== 请求/响应模型 ==========

class PrepareFileRequest(BaseModel):
    """准备文件分析的请求"""
    filename: str
    session_id: str = "default"

class PrepareFileResponse(BaseModel):
    """准备文件分析的响应"""
    status: str
    file_id: str
    summary: Dict[str, Any]
    message: str

class ChatRequest(BaseModel):
    """智能对话请求"""
    session_id: str = "default"
    file_id: str
    message: str
    conversation_id: str = "default"

class ChatResponse(BaseModel):
    """智能对话响应"""
    response: str
    tool_used: Optional[str] = None
    tool_params: Optional[Dict] = None
    tool_result: Optional[Dict] = None

class FileListResponse(BaseModel):
    """文件列表响应"""
    files: List[Dict[str, Any]]


# ========== API 端点 ==========

@router.post("/prepare", response_model=PrepareFileResponse)
async def prepare_file_for_analysis(
    request: PrepareFileRequest,
    file_service: FileService = Depends(get_file_service)
):
    """
    为CSV文件建立分析索引
    
    这是一次性操作，后续分析会使用缓存的索引
    时间：根据文件大小，约1-3分钟
    """
    try:
        # 获取文件路径
        csv_path = file_service.get_file_path(request.filename, request.session_id)
        
        # 检查文件是否存在
        import os
        if not os.path.exists(csv_path):
            raise HTTPException(404, detail=f"文件不存在: {request.filename}")
        
        # 建立索引
        summary = await analysis_service.build_analysis_index(
            csv_path=csv_path,
            session_id=request.session_id,
            filename=request.filename
        )
        
        return PrepareFileResponse(
            status="success",
            file_id=summary["file_id"],
            summary=summary,
            message=f"文件 {request.filename} 分析索引建立完成"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, detail=f"索引建立失败: {str(e)}")


@router.post("/chat", response_model=ChatResponse)
async def chat_with_ai(request: ChatRequest):
    """
    智能对话分析
    
    用户用自然语言提问，AI 自动调用工具并回答
    """
    try:
        # 验证 file_id 有效性
        from pathlib import Path
        analysis_path = analysis_service.get_analysis_path(
            request.session_id, 
            request.file_id
        )
        
        if not (analysis_path / "summary.json").exists():
            raise HTTPException(
                400, 
                detail="文件尚未准备好，请先调用 /prepare 接口"
            )
        
        # 调用 LLM Agent
        result = llm_agent.analyze(
            session_id=request.session_id,
            file_id=request.file_id,
            user_question=request.message
        )
        
        return ChatResponse(**result)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, detail=f"分析失败: {str(e)}")


@router.get("/files", response_model=FileListResponse)
async def list_analysis_files(
    session_id: str = Query("default"),
    file_service: FileService = Depends(get_file_service)
):
    """
    获取当前用户可分析的文件列表
    
    返回已上传的CSV文件及其分析状态
    """
    try:
        # 获取上传的文件
        uploaded_files = await file_service.list_files(session_id)
        
        # 检查每个文件的分析状态
        files_with_status = []
        for file_info in uploaded_files["files"]:
            filename = file_info["filename"]
            
            # 只处理CSV文件
            if not filename.endswith('.csv'):
                continue
            
            file_id = analysis_service.get_file_id(filename)
            analysis_path = analysis_service.get_analysis_path(session_id, file_id)
            
            # 检查是否已建立索引
            is_indexed = (analysis_path / "summary.json").exists()
            
            files_with_status.append({
                "filename": filename,
                "file_id": file_id,
                "size": file_info["size"],
                "uploaded_at": file_info["uploaded_at"],
                "is_indexed": is_indexed,
                "status": "ready" if is_indexed else "not_prepared"
            })
        
        return FileListResponse(files=files_with_status)
        
    except Exception as e:
        raise HTTPException(500, detail=f"获取文件列表失败: {str(e)}")


@router.get("/summary/{file_id}")
async def get_file_summary(
    file_id: str,
    session_id: str = Query("default")
):
    """
    获取文件的分析摘要
    
    包含参数数量、分类、基本统计等信息
    """
    try:
        analysis_path = analysis_service.get_analysis_path(session_id, file_id)
        summary_file = analysis_path / "summary.json"
        
        if not summary_file.exists():
            raise HTTPException(404, detail="文件摘要不存在")
        
        import json
        with open(summary_file, 'r', encoding='utf-8') as f:
            summary = json.load(f)
        
        return summary
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, detail=f"获取摘要失败: {str(e)}")


@router.delete("/clear-session")
async def clear_conversation_session(
    session_id: str = Query("default"),
    conversation_id: str = Query("default")
):
    """
    清除对话历史
    
    用于开始新的分析话题
    """
    try:
        llm_agent.clear_conversation(session_id, conversation_id)
        
        return {
            "status": "success",
            "message": "对话历史已清除"
        }
        
    except Exception as e:
        raise HTTPException(500, detail=f"清除失败: {str(e)}")


@router.get("/tools")
async def get_available_tools():
    """
    获取可用的分析工具列表
    
    返回所有18个工具的说明，供前端展示
    """
    tools = [
        {
            "name": "get_parameter_list",
            "display_name": "参数列表",
            "description": "获取数据集的所有参数",
            "category": "数据查询"
        },
        {
            "name": "get_parameter_statistics",
            "display_name": "参数统计",
            "description": "获取指定参数的详细统计信息",
            "category": "数据查询"
        },
        {
            "name": "search_parameters_by_concept",
            "display_name": "概念搜索",
            "description": "根据中文概念智能搜索相关参数",
            "category": "数据查询"
        },
        {
            "name": "calculate_correlation",
            "display_name": "相关性分析",
            "description": "计算参数间的相关系数",
            "category": "统计分析"
        },
        {
            "name": "get_top_correlations",
            "display_name": "Top相关性",
            "description": "快速找到与目标最相关的参数",
            "category": "统计分析"
        },
        {
            "name": "compare_groups",
            "display_name": "组间比较",
            "description": "比较不同条件下的参数差异",
            "category": "统计分析"
        },
        {
            "name": "detect_outliers",
            "display_name": "异常检测",
            "description": "识别数据中的离群值",
            "category": "统计分析"
        },
        {
            "name": "analyze_distribution",
            "display_name": "分布分析",
            "description": "分析参数的分布特征",
            "category": "统计分析"
        },
        {
            "name": "perform_regression",
            "display_name": "回归分析",
            "description": "建立预测模型",
            "category": "统计分析"
        },
        {
            "name": "find_temporal_patterns",
            "display_name": "时序模式",
            "description": "发现趋势、周期性和突变点",
            "category": "模式发现"
        },
        {
            "name": "find_event_patterns",
            "display_name": "事件模式",
            "description": "分析特定事件前后的参数变化",
            "category": "模式发现"
        },
        {
            "name": "cluster_analysis",
            "display_name": "聚类分析",
            "description": "发现数据中的隐藏分组",
            "category": "模式发现"
        }
    ]
    
    return {
        "tools": tools,
        "total_count": len(tools)
    }
```

### 2. 依赖注入更新 (`dependencies.py`)

```python
# backend/dependencies.py (新增部分)

from backend.services.analysis_service import AnalysisService
from backend.services.analysis_tool_executor import AnalysisToolExecutor
from backend.services.llm_analysis_agent_simple import LLMAnalysisAgentSimple

# 单例实例
_analysis_service = None
_tool_executor = None
_llm_agent = None

def get_analysis_service() -> AnalysisService:
    """获取分析服务实例"""
    global _analysis_service
    if _analysis_service is None:
        _analysis_service = AnalysisService()
    return _analysis_service

def get_tool_executor() -> AnalysisToolExecutor:
    """获取工具执行器实例"""
    global _tool_executor
    if _tool_executor is None:
        analysis_service = get_analysis_service()
        _tool_executor = AnalysisToolExecutor(analysis_service)
    return _tool_executor

def get_llm_agent() -> LLMAnalysisAgentSimple:
    """获取LLM Agent实例"""
    global _llm_agent
    if _llm_agent is None:
        tool_executor = get_tool_executor()
        _llm_agent = LLMAnalysisAgentSimple(tool_executor)
    return _llm_agent
```

### 3. 主应用注册路由 (`api_entry.py`)

```python
# api_entry.py (新增部分)

from backend.routers import analysis_router

# 在现有的路由注册之后添加
app.include_router(analysis_router.router)
```

---

## API 使用流程示例

### 完整流程

```javascript
// 1. 获取可分析的文件列表
const filesResponse = await fetch('/api/analysis/files?session_id=user123');
const { files } = await filesResponse.json();
// files = [
//   {filename: "data.csv", file_id: "abc123", is_indexed: false, status: "not_prepared"},
//   ...
// ]

// 2. 为文件建立索引（如果尚未准备）
if (!files[0].is_indexed) {
    const prepareResponse = await fetch('/api/analysis/prepare', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            filename: "data.csv",
            session_id: "user123"
        })
    });
    const result = await prepareResponse.json();
    // result.file_id = "abc123"
}

// 3. 开始智能对话
const chatResponse = await fetch('/api/analysis/chat', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
        session_id: "user123",
        file_id: "abc123",
        message: "有哪些温度相关的参数？"
    })
});
const chatResult = await chatResponse.json();
// chatResult = {
//   response: "找到12个温度相关参数：BCDRY-TEMP-A101, ...",
//   tool_used: "search_parameters_by_concept",
//   tool_params: {concept: "温度"},
//   tool_result: {...}
// }

// 4. 继续对话
const followUp = await fetch('/api/analysis/chat', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
        session_id: "user123",
        file_id: "abc123",
        message: "这些参数中哪个与品质相关性最强？"
    })
});
```

---

## 错误处理

所有 API 都遵循统一的错误格式：

```json
{
  "detail": "错误描述信息"
}
```

常见错误码：
- `400`: 请求参数错误
- `404`: 资源不存在（文件或索引）
- `500`: 服务器内部错误

---

## 性能优化建议

1. **索引缓存**: `summary.json` 等文件自动缓存，避免重复计算
2. **异步处理**: `prepare` 接口可改为后台任务（使用 Celery）
3. **限流**: 对 `/chat` 接口添加频率限制
4. **超时控制**: LLM 调用设置合理超时

---

下一步请查看 **Part 4: 前端整合方案**
