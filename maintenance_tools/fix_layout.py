import re
import os

filepath = r"c:\Users\foresight\Desktop\MantleTemp\pythaon\Sigma2\dashboard.html"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# Pattern to find the content inside train-step-panel-1
# From <h3> to the last </div> before the "Next Step" button div.
pattern = re.compile(
    r'(<div id="train-step-panel-1".*?>\s*<h3.*?>.*?第一步：🎯.*?標的</h3>)\s*(<div.*?選擇標的欄位.*?</div>)\s*(<div.*?display: flex; gap: 20px;.*?SCATTER PREVIEW.*?</div>\s*</div>)',
    re.DOTALL,
)

replacement = r"""\1

                                             <div style="display: flex; gap: 20px; flex: 1; min-height: 0; margin-bottom: 10px;">
                                                 <!-- Left Column -->
                                                 <div style="flex: 1; display: flex; flex-direction: column; gap: 10px; min-width: 0;">
                                                     \2
                                                     
                                                     <!-- Scatter Plot Area -->
                                                     <div style="flex: 1; min-width: 0; background: #fff; border-radius: 12px; border: 1px solid #e2e8f0; position: relative; padding: 15px; display: flex; flex-direction: column; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
                                                         <div style="font-size: 11px; color: #64748b; margin-bottom: 8px; font-weight: 700; display: flex; align-items: center; gap: 6px;">
                                                             <span style="width: 8px; height: 8px; background: #3b82f6; border-radius: 50%;"></span>
                                                             數據分佈即時預覽 (SCATTER PREVIEW)
                                                         </div>
                                                         <div id="goal-column-chart" style="flex: 1; width: 100%; position: relative; overflow: hidden;">
                                                             <canvas id="goal-column-chart-canvas"></canvas>
                                                         </div>
                                                     </div>
                                                 </div>

                                                 <!-- Right Column: Specs Panel -->
                                                 <div style="flex: 0 0 220px; display: flex; flex-direction: column; gap: 10px; background: #f8fafc; padding: 16px; border-radius: 12px; border: 1px solid #e2e8f0; box-shadow: 0 4px 10px -2px rgba(0,0,0,0.06);">
                                                     <div style="font-size: 13px; font-weight: 800; color: #1e293b; margin-bottom: 5px; text-align: center; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px;">
                                                         🎯 規格參數配置
                                                     </div>

                                                     <div class="setting-item">
                                                         <label style="display: block; font-size: 11px; font-weight: 700; color: #475569; margin-bottom: 4px;">目標值 (Target)</label>
                                                         <input type="number" id="goal-target" placeholder="輸入數值..." oninput="updateGoalChartLines()"
                                                             style="width: 100%; padding: 8px 12px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 13px; outline: none; background: #fff;">
                                                     </div>

                                                     <div class="setting-item">
                                                         <label style="display: block; font-size: 11px; font-weight: 700; color: #475569; margin-bottom: 4px;">上限 (USL)</label>
                                                         <input type="number" id="goal-usl" placeholder="輸入上限..." oninput="updateGoalChartLines()"
                                                             style="width: 100%; padding: 8px 12px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 13px; outline: none; background: #fff;">
                                                     </div>

                                                     <div class="setting-item">
                                                         <label style="display: block; font-size: 11px; font-weight: 700; color: #475569; margin-bottom: 4px;">下限 (LSL)</label>
                                                         <input type="number" id="goal-lsl" placeholder="輸入下限..." oninput="updateGoalChartLines()"
                                                             style="width: 100%; padding: 8px 12px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 13px; outline: none; background: #fff;">
                                                     </div>

                                                     <div id="goal-stat-box" style="margin-top: auto; padding: 12px; background: #fff; border-radius: 12px; border: 1px solid #e2e8f0; box-shadow: inset 0 2px 4px rgba(0,0,0,0.02);">
                                                         <div style="display: flex; justify-content: space-between; font-size: 12px; color: #64748b; margin-bottom: 8px;">
                                                             <span>超規筆數:</span>
                                                             <b style="color: #ef4444; font-size: 15px;">
                                                                 <span id="goal-out-count">0</span>
                                                                 <span id="goal-total-count" style="font-size: 11px; color: #94a3b8; font-weight: 400; margin-left: 2px;">(0)</span>
                                                             </b>
                                                         </div>
                                                         <div style="display: flex; justify-content: space-between; font-size: 12px; color: #64748b;">
                                                             <span>超規比例:</span>
                                                             <b id="goal-out-ratio" style="color: #ef4444; font-size: 15px;">0.00%</b>
                                                         </div>
                                                     </div>
                                                 </div>
                                             </div>"""

new_content = pattern.sub(replacement, content)

if new_content != content:
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_content)
    print("Successfully updated layout.")
else:
    print("Could not find pattern to replace.")
