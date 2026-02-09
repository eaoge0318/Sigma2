# Part 4: 前端整合方案

## UI 设计概览

在现有 `dashboard.html` 的即时看板下方，新增**智能分析**功能页面。

### 页面结构

```
Dashboard 导航栏
├── 即时看板 (现有)
├── 模型训练 (现有)
└── 智能分析 (新增) ← 本次实现
```

---

## 1. HTML 结构

### 在 `dashboard.html` 中新增智能分析区块

```html
<!-- 在即时看板 section 之后添加 -->

<!-- ========== 智能分析区块 ========== -->
<section id="intelligent-analysis-section" class="main-section" style="display: none;">
    <div class="section-header">
        <h2>💡 智能分析助手</h2>
        <p class="subtitle">用自然语言提问，AI 帮您深入分析数据</p>
    </div>

    <div class="analysis-container">
        <!-- 左侧：文件选择与信息 -->
        <div class="analysis-sidebar">
            <div class="card">
                <h3>📂 选择数据文件</h3>
                <select id="analysis-file-selector" class="form-select">
                    <option value="">-- 请选择文件 --</option>
                </select>
                
                <button id="prepare-file-btn" class="btn btn-primary" style="margin-top: 10px; display: none;">
                    准备分析索引
                </button>
                
                <div id="file-info-card" style="margin-top: 15px; display: none;">
                    <div class="info-item">
                        <span class="label">文件名:</span>
                        <span id="info-filename">-</span>
                    </div>
                    <div class="info-item">
                        <span class="label">总行数:</span>
                        <span id="info-rows">-</span>
                    </div>
                    <div class="info-item">
                        <span class="label">参数数:</span>
                        <span id="info-params">-</span>
                    </div>
                    <div class="info-item">
                        <span class="label">状态:</span>
                        <span id="info-status" class="badge">-</span>
                    </div>
                </div>
            </div>

            <!-- 快捷操作 -->
            <div class="card" style="margin-top: 15px;">
                <h3>🔧 快捷操作</h3>
                <div class="quick-actions">
                    <button class="quick-btn" data-prompt="有哪些参数？">
                        查看参数列表
                    </button>
                    <button class="quick-btn" data-prompt="温度相关的参数有哪些？">
                        搜索温度参数
                    </button>
                    <button class="quick-btn" data-prompt="分析参数之间的相关性">
                        相关性分析
                    </button>
                    <button class="quick-btn" data-prompt="检测异常值">
                        异常值检测
                    </button>
                </div>
            </div>

            <!-- 可用工具 -->
            <div class="card" style="margin-top: 15px;">
                <h3>🛠️ 可用工具</h3>
                <div id="tools-list" class="tools-list">
                    <!-- 动态加载 -->
                </div>
            </div>
        </div>

        <!-- 右侧：对话区 -->
        <div class="analysis-chat">
            <div class="chat-messages" id="chat-messages">
                <div class="welcome-message">
                    <h3>👋 欢迎使用智能分析助手</h3>
                    <p>请先选择一个CSV文件，然后开始提问。</p>
                    <p class="tip">💡 提示：您可以问"有哪些温度参数？"、"分析相关性"等</p>
                </div>
            </div>

            <div class="chat-input-area">
                <textarea 
                    id="user-question" 
                    placeholder="在此输入您的问题，例如：为什么品质下降？哪些参数与断纸相关？"
                    rows="2"
                ></textarea>
                <div class="input-actions">
                    <button id="clear-chat-btn" class="btn btn-secondary">清除对话</button>
                    <button id="send-question-btn" class="btn btn-primary">
                        <span>发送</span>
                        <span class="loading" style="display: none;">分析中...</span>
                    </button>
                </div>
            </div>
        </div>
    </div>
</section>
```

---

## 2. CSS 样式

### 新增样式文件或在 `dashboard.html` 的 `<style>` 中添加

```css
/* ========== 智能分析样式 ========== */

.analysis-container {
    display: grid;
    grid-template-columns: 350px 1fr;
    gap: 20px;
    margin-top: 20px;
}

.analysis-sidebar {
    display: flex;
    flex-direction: column;
}

.analysis-sidebar .card {
    background: white;
    border-radius: 8px;
    padding: 20px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}

.analysis-sidebar h3 {
    font-size: 16px;
    margin-bottom: 15px;
    color: #333;
}

.info-item {
    display: flex;
    justify-content: space-between;
    padding: 8px 0;
    border-bottom: 1px solid #f0f0f0;
}

.info-item .label {
    font-weight: 500;
    color: #666;
}

.badge {
    padding: 4px 12px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
}

.badge.ready {
    background: #d4edda;
    color: #155724;
}

.badge.not-ready {
    background: #fff3cd;
    color: #856404;
}

/* 快捷操作按钮 */
.quick-actions {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.quick-btn {
    padding: 10px 15px;
    background: #f8f9fa;
    border: 1px solid #dee2e6;
    border-radius: 6px;
    text-align: left;
    cursor: pointer;
    transition: all 0.2s;
}

.quick-btn:hover {
    background: #e9ecef;
    border-color: #adb5bd;
}

/* 工具列表 */
.tools-list {
    max-height: 300px;
    overflow-y: auto;
}

.tool-item {
    padding: 8px;
    margin-bottom: 8px;
    background: #f8f9fa;
    border-radius: 4px;
    font-size: 13px;
}

.tool-item .tool-name {
    font-weight: 600;
    color: #007bff;
}

.tool-item .tool-desc {
    color: #6c757d;
    margin-top: 4px;
}

/* 对话区 */
.analysis-chat {
    background: white;
    border-radius: 8px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    display: flex;
    flex-direction: column;
    height: calc(100vh - 250px);
    min-height: 600px;
}

.chat-messages {
    flex: 1;
    overflow-y: auto;
    padding: 20px;
}

.welcome-message {
    text-align: center;
    padding: 40px 20px;
    color: #666;
}

.welcome-message h3 {
    margin-bottom: 15px;
    color: #333;
}

.welcome-message .tip {
    margin-top: 20px;
    padding: 12px;
    background: #e7f3ff;
    border-radius: 6px;
    color: #004085;
}

/* 消息样式 */
.message {
    margin-bottom: 20px;
    animation: fadeIn 0.3s;
}

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
}

.message.user {
    display: flex;
    justify-content: flex-end;
}

.message.user .message-content {
    background: #007bff;
    color: white;
    padding: 12px 16px;
    border-radius: 18px 18px 4px 18px;
    max-width: 70%;
}

.message.assistant {
    display: flex;
    justify-content: flex-start;
}

.message.assistant .message-content {
    background: #f1f3f5;
    color: #333;
    padding: 12px 16px;
    border-radius: 18px 18px 18px 4px;
    max-width: 80%;
}

.message.thinking .message-content {
    background: #fff3cd;
    color: #856404;
    padding: 12px 16px;
    border-radius: 18px;
}

/* 工具调用展示 */
.tool-call-info {
    margin-top: 8px;
    padding: 8px 12px;
    background: #e9ecef;
    border-radius: 8px;
    font-size: 12px;
    color: #495057;
}

.tool-call-info .tool-badge {
    display: inline-block;
    padding: 2px 8px;
    background: #6c757d;
    color: white;
    border-radius: 4px;
    margin-right: 6px;
}

/* 输入区 */
.chat-input-area {
    border-top: 1px solid #dee2e6;
    padding: 15px;
}

.chat-input-area textarea {
    width: 100%;
    padding: 12px;
    border: 1px solid #ced4da;
    border-radius: 8px;
    resize: none;
    font-size: 14px;
    font-family: inherit;
}

.chat-input-area textarea:focus {
    outline: none;
    border-color: #007bff;
    box-shadow: 0 0 0 3px rgba(0,123,255,0.1);
}

.input-actions {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
    margin-top: 10px;
}

/* 响应式 */
@media (max-width: 1200px) {
    .analysis-container {
        grid-template-columns: 1fr;
    }
    
    .analysis-sidebar {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 15px;
    }
}
```

---

## 3. JavaScript 实现

### 新增 `static/js/intelligent_analysis.js`

```javascript
// static/js/intelligent_analysis.js

class IntelligentAnalysis {
    constructor() {
        this.sessionId = localStorage.getItem('session_id') || 'default';
        this.currentFileId = null;
        this.currentFilename = null;
        this.conversationId = 'default';
        
        this.init();
    }
    
    async init() {
        // 绑定事件
        this.bindEvents();
        
        // 加载文件列表
        await this.loadFiles();
        
        // 加载可用工具
        await this.loadTools();
    }
    
    bindEvents() {
        // 文件选择
        document.getElementById('analysis-file-selector').addEventListener('change', (e) => {
            this.onFileSelect(e.target.value);
        });
        
        // 准备文件
        document.getElementById('prepare-file-btn').addEventListener('click', () => {
            this.prepareFile();
        });
        
        // 发送消息
        document.getElementById('send-question-btn').addEventListener('click', () => {
            this.sendMessage();
        });
        
        // 回车发送
        document.getElementById('user-question').addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });
        
        // 清除对话
        document.getElementById('clear-chat-btn').addEventListener('click', () => {
            this.clearChat();
        });
        
        // 快捷按钮
        document.querySelectorAll('.quick-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const prompt = e.target.dataset.prompt;
                document.getElementById('user-question').value = prompt;
                this.sendMessage();
            });
        });
    }
    
    async loadFiles() {
        try {
            const response = await fetch(`/api/analysis/files?session_id=${this.sessionId}`);
            const data = await response.json();
            
            const selector = document.getElementById('analysis-file-selector');
            selector.innerHTML = '<option value="">-- 请选择文件 --</option>';
            
            data.files.forEach(file => {
                const option = document.createElement('option');
                option.value = file.file_id;
                option.textContent = `${file.filename} ${file.is_indexed ? '✓' : ''}`;
                option.dataset.filename = file.filename;
                option.dataset.indexed = file.is_indexed;
                selector.appendChild(option);
            });
            
        } catch (error) {
            console.error('加载文件列表失败:', error);
            this.showError('无法加载文件列表');
        }
    }
    
    async loadTools() {
        try {
            const response = await fetch('/api/analysis/tools');
            const data = await response.json();
            
            const toolsList = document.getElementById('tools-list');
            toolsList.innerHTML = '';
            
            // 按分类分组
            const categories = {};
            data.tools.forEach(tool => {
                if (!categories[tool.category]) {
                    categories[tool.category] = [];
                }
                categories[tool.category].push(tool);
            });
            
            // 渲染
            Object.entries(categories).forEach(([category, tools]) => {
                const categoryDiv = document.createElement('div');
                categoryDiv.className = 'tool-category';
                categoryDiv.innerHTML = `<h4 style="font-size: 13px; margin: 10px 0 5px 0; color: #666;">${category}</h4>`;
                
                tools.forEach(tool => {
                    const toolDiv = document.createElement('div');
                    toolDiv.className = 'tool-item';
                    toolDiv.innerHTML = `
                        <div class="tool-name">${tool.display_name}</div>
                        <div class="tool-desc">${tool.description}</div>
                    `;
                    categoryDiv.appendChild(toolDiv);
                });
                
                toolsList.appendChild(categoryDiv);
            });
            
        } catch (error) {
            console.error('加载工具列表失败:', error);
        }
    }
    
    onFileSelect(fileId) {
        const selector = document.getElementById('analysis-file-selector');
        const selectedOption = selector.options[selector.selectedIndex];
        
        if (!fileId) {
            document.getElementById('file-info-card').style.display = 'none';
            document.getElementById('prepare-file-btn').style.display = 'none';
            this.currentFileId = null;
            return;
        }
        
        this.currentFileId = fileId;
        this.currentFilename = selectedOption.dataset.filename;
        const isIndexed = selectedOption.dataset.indexed === 'true';
        
        if (isIndexed) {
            // 已索引，加载摘要
            this.loadFileSummary();
            document.getElementById('prepare-file-btn').style.display = 'none';
        } else {
            // 未索引，显示准备按钮
            document.getElementById('file-info-card').style.display = 'block';
            document.getElementById('info-filename').textContent = this.currentFilename;
            document.getElementById('info-status').textContent = '未准备';
            document.getElementById('info-status').className = 'badge not-ready';
            document.getElementById('prepare-file-btn').style.display = 'block';
        }
    }
    
    async loadFileSummary() {
        try {
            const response = await fetch(
                `/api/analysis/summary/${this.currentFileId}?session_id=${this.sessionId}`
            );
            const summary = await response.json();
            
            document.getElementById('file-info-card').style.display = 'block';
            document.getElementById('info-filename').textContent = summary.filename;
            document.getElementById('info-rows').textContent = summary.total_rows.toLocaleString();
            document.getElementById('info-params').textContent = summary.total_columns;
            document.getElementById('info-status').textContent = '已准备';
            document.getElementById('info-status').className = 'badge ready';
            
        } catch (error) {
            console.error('加载文件摘要失败:', error);
        }
    }
    
    async prepareFile() {
        const btn = document.getElementById('prepare-file-btn');
        btn.disabled = true;
        btn.textContent = '正在准备索引...';
        
        try {
            const response = await fetch('/api/analysis/prepare', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    filename: this.currentFilename,
                    session_id: this.sessionId
                })
            });
            
            const result = await response.json();
            
            if (result.status === 'success') {
                this.showSuccess('文件准备完成！');
                this.loadFileSummary();
                btn.style.display = 'none';
            } else {
                throw new Error(result.message || '准备失败');
            }
            
        } catch (error) {
            console.error('准备文件失败:', error);
            this.showError('准备文件失败: ' + error.message);
            btn.disabled = false;
            btn.textContent = '准备分析索引';
        }
    }
    
    async sendMessage() {
        if (!this.currentFileId) {
            this.showError('请先选择一个文件');
            return;
        }
        
        const textarea = document.getElementById('user-question');
        const message = textarea.value.trim();
        
        if (!message) return;
        
        // 清空输入
        textarea.value = '';
        
        // 显示用户消息
        this.addMessage('user', message);
        
        // 显示思考中
        const thinkingId = this.addMessage('thinking', '正在分析中...');
        
        // 禁用发送按钮
        const sendBtn = document.getElementById('send-question-btn');
        sendBtn.disabled = true;
        sendBtn.querySelector('.loading').style.display = 'inline';
        sendBtn.querySelector('span:first-child').style.display = 'none';
        
        try {
            const response = await fetch('/api/analysis/chat', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    session_id: this.sessionId,
                    file_id: this.currentFileId,
                    message: message,
                    conversation_id: this.conversationId
                })
            });
            
            const result = await response.json();
            
            // 移除思考中消息
            document.getElementById(thinkingId).remove();
            
            // 显示AI回复
            this.addMessage('assistant', result.response, {
                tool_used: result.tool_used,
                tool_params: result.tool_params
            });
            
        } catch (error) {
            console.error('发送消息失败:', error);
            document.getElementById(thinkingId).remove();
            this.addMessage('assistant', '❌ 分析失败: ' + error.message);
        } finally {
            sendBtn.disabled = false;
            sendBtn.querySelector('.loading').style.display = 'none';
            sendBtn.querySelector('span:first-child').style.display = 'inline';
        }
    }
    
    addMessage(role, content, metadata = {}) {
        const container = document.getElementById('chat-messages');
        
        // 移除欢迎消息
        const welcome = container.querySelector('.welcome-message');
        if (welcome) welcome.remove();
        
        const messageId = 'msg-' + Date.now();
        const messageDiv = document.createElement('div');
        messageDiv.id = messageId;
        messageDiv.className = `message ${role}`;
        
        let html = `<div class="message-content">${this.formatContent(content)}</div>`;
        
        // 添加工具调用信息
        if (metadata.tool_used) {
            html += `
                <div class="tool-call-info">
                    <span class="tool-badge">${metadata.tool_used}</span>
                    已调用工具进行分析
                </div>
            `;
        }
        
        messageDiv.innerHTML = html;
        container.appendChild(messageDiv);
        
        // 滚动到底部
        container.scrollTop = container.scrollHeight;
        
        return messageId;
    }
    
    formatContent(content) {
        // 简单的 Markdown 转换
        return content
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\n/g, '<br>');
    }
    
    clearChat() {
        if (confirm('确定要清除对话历史吗？')) {
            const container = document.getElementById('chat-messages');
            container.innerHTML = `
                <div class="welcome-message">
                    <h3>👋 对话已清除</h3>
                    <p>开始新的分析话题吧！</p>
                </div>
            `;
            
            // 调用后端清除
            fetch('/api/analysis/clear-session?' + new URLSearchParams({
                session_id: this.sessionId,
                conversation_id: this.conversationId
            }), {method: 'DELETE'});
        }
    }
    
    showError(message) {
        // 可以用更好的提示组件
        alert('错误: ' + message);
    }
    
    showSuccess(message) {
        alert('成功: ' + message);
    }
}

// 初始化
let intelligentAnalysis;
document.addEventListener('DOMContentLoaded', () => {
    intelligentAnalysis = new IntelligentAnalysis();
});
```

### 在 `dashboard.html` 中引入

```html
<!-- 在 </body> 前添加 -->
<script src="/static/js/intelligent_analysis.js"></script>
```

---

## 4. 导航整合

### 在现有的导航栏添加智能分析标签

```javascript
// 在 dashboard.html 的导航切换逻辑中添加
function showSection(sectionName) {
    // 隐藏所有区块
    document.querySelectorAll('.main-section').forEach(section => {
        section.style.display = 'none';
    });
    
    // 显示选中的区块
    if (sectionName === 'realtime') {
        document.getElementById('realtime-dashboard-section').style.display = 'block';
    } else if (sectionName === 'training') {
        document.getElementById('model-training-section').style.display = 'block';
    } else if (sectionName === 'analysis') {
        document.getElementById('intelligent-analysis-section').style.display = 'block';
    }
}
```

---

## 使用流程

1. 用户进入"智能分析"页面
2. 选择一个已上传的CSV文件
3. 如果文件未准备，点击"准备分析索引"（1-2分钟）
4. 索引建立完成后，开始提问
5. AI 自动调用工具并返回分析结果
6. 可以连续提问，进行深入分析

---

下一步请查看 **Part 5: 测试与验证计划**
