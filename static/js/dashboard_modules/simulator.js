
// =========================
// simulator.js - Playback Logic
// =========================
import { DOM, API } from './utils.js';
// We need to import updateDashboard from somewhere, or main.js sets it?
// Circular dependency risk.
// Solution: main.js injects updateDashboard or we use an event bus.
// For now, assume window.updateDashboard is available or we export a setup function.

let autoPlayTimer = null;

export async function triggerSimulatorNext() {
    try {
        const data = await API.post('/api/simulator/next');
        if (data.status === 'EOF') {
            alert(data.message);
            stopAutoPlay();
        } else {
            // Assuming updateDashboard is global or we import it.
            // Since dashboard_main.js will expose globals, we can use window.updateDashboard if strictly necessary,
            // but better to allow passing a callback.
            if (typeof window.updateDashboard === 'function') {
                window.updateDashboard();
            }
        }
    } catch (err) { console.error("Simulator Error:", err); }
}

export async function runFullSimulation() {
    stopAutoPlay(); // Stop existing
    await API.post('/api/clear');

    // Reset UI
    DOM.setHTML('reasoning-logs', '<div id="log-empty-msg" style="color: #94a3b8; text-align: center; padding: 30px;">目前沒有數據，請先啟動系統以收集數據。</div>');
    DOM.setHTML('ai-report-content', '<div class="ai-bubble chat-bubble">👋 模擬已重設，正在重新讀取數據集...</div>');
    DOM.setText('status-text', "Initializing Simulator...");

    // Reset charts via updateDashboard
    setTimeout(async () => {
        if (typeof window.updateDashboard === 'function') {
            await window.updateDashboard();
        }
        startAutoPlay();
    }, 100);
}

export function startAutoPlay() {
    const btn = DOM.get('btn-autoplay');
    if (autoPlayTimer) return;
    if (btn) {
        btn.innerText = "Stop Auto ⏹️";
        btn.style.background = "#fee2e2";
        btn.style.borderColor = "#ef4444";
    }
    triggerSimulatorNext(); // Run first immediately
    autoPlayTimer = setInterval(triggerSimulatorNext, 2000);
}

export function stopAutoPlay() {
    const btn = DOM.get('btn-autoplay');
    if (autoPlayTimer) {
        clearInterval(autoPlayTimer);
        autoPlayTimer = null;
    }
    if (btn) {
        btn.innerText = "Auto Play ▶️";
        btn.style.background = "";
        btn.style.borderColor = "";
    }
}

export function toggleAutoPlay() {
    if (autoPlayTimer) {
        stopAutoPlay();
    } else {
        startAutoPlay();
    }
}

export async function clearHistory() {
    if (!confirm("確定要清除所有監控紀錄並重設模擬進度嗎？")) return;
    // Pass session_id
    await fetch('/api/clear', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: window.SESSION_ID })
    });
    location.reload();
}

/**
 * 初始化儀表板上的模擬器下拉選單（檔案與模型）
 */
export function initSimulatorSelectors() {
    const fileSelect = document.getElementById('dashboard-file-select');
    const modelSelect = document.getElementById('dashboard-model-select');

    if (fileSelect) {
        fileSelect.addEventListener('change', async (e) => {
            const filename = e.target.value;
            if (!filename) return;

            try {
                const result = await API.post('/api/simulator/load_file', { filename });
                if (result.status === 'success') {
                    alert(`✅ 已載入模擬檔案:\n${filename}\n(${result.rows} 筆數據)`);
                } else {
                    alert(`⚠️ 檔案載入異常`);
                }
            } catch (err) {
                alert(`❌ 檔案載入失敗: ${err.message}`);
            }
        });
    }

    if (modelSelect) {
        modelSelect.addEventListener('change', async (e) => {
            const modelPath = e.target.value;
            if (!modelPath) return;

            try {
                const result = await API.post('/api/model/load', { model_path: modelPath });
                if (result.status === 'success') {
                    // Apply Y2 Axis Range from Model Config
                    // Apply Y2 Ranges (Detailed Dictionary) - NEW
                    if (result.config && result.config.y2_axis_ranges && typeof window.setAllY2Ranges === 'function') {
                        window.setAllY2Ranges(result.config.y2_axis_ranges);
                        // Clear global manual override so specific ranges take precedence
                        if (typeof window.setY2Range === 'function') window.setY2Range(null, null);
                        console.log("Applied detailed per-parameter Y2 ranges");
                    }
                    // Apply Y2 Axis Range (Legacy Global List) - OLD
                    else if (result.config && result.config.y2_axis_range && Array.isArray(result.config.y2_axis_range)) {
                        const [min, max] = result.config.y2_axis_range;
                        if (typeof window.setY2Range === 'function') {
                            window.setY2Range(min, max);
                            console.log(`Applied legacy model Y2 range: ${min} - ${max}`);
                        }
                    } else {
                        // Reset if no range specified
                        if (typeof window.setY2Range === 'function') {
                            window.setY2Range(null, null);
                        }
                        if (typeof window.setAllY2Ranges === 'function') {
                            window.setAllY2Ranges({});
                        }
                    }
                    alert(`✅ 已載入模型:\n${result.run_path || modelPath}`);
                } else {
                    alert(`⚠️ 模型載入異常`);
                }
            } catch (err) {
                alert(`❌ 模型載入失敗: ${err.message}`);
            }
        });
    }
}
