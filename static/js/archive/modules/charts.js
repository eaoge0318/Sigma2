// 圖表管理模組 - 使用 ECharts 管理所有圖表
export class ChartsManager {
    constructor() {
        this.charts = {};
        this.WINDOW_SIZE = 40;
    }

    initCharts() {
        // 初始化所有圖表
        this.charts.feature = echarts.init(document.getElementById('chart-feature'));
        this.charts.reward = echarts.init(document.getElementById('chart-reward'));
        this.charts.action = echarts.init(document.getElementById('chart-action'));
        this.charts.qval = echarts.init(document.getElementById('chart-qval'));

        // 設定初始配置
        this._setFeatureChartOption();
        this._setRewardChartOption();
        this._setActionChartOption();
        this._setQValueChartOption();

        // 掛載到 window 供其他模組使用
        window.charts = this.charts;
    }

    _setFeatureChartOption() {
        this.charts.feature.setOption({
            title: { text: '特徵趨勢', left: 'center', textStyle: { color: '#334155', fontSize: 14, fontWeight: 600 } },
            tooltip: { trigger: 'axis' },
            legend: { data: [], bottom: 10, textStyle: { color: '#64748b' } },
            grid: { left: '10%', right: '10%', bottom: '15%', top: '15%', containLabel: true },
            xAxis: { type: 'category', data: [], axisLabel: { color: '#94a3b8' } },
            yAxis: { type: 'value', axisLabel: { color: '#94a3b8' } },
            series: []
        });
    }

    _setRewardChartOption() {
        this.charts.reward.setOption({
            title: { text: 'Reward 曲線', left: 'center', textStyle: { color: '#334155', fontSize: 14, fontWeight: 600 } },
            tooltip: { trigger: 'axis' },
            grid: { left: '10%', right: '10%', bottom: '15%', top: '15%' },
            xAxis: { type: 'category', data: [], axisLabel: { color: '#94a3b8' } },
            yAxis: { type: 'value', axisLabel: { color: '#94a3b8' } },
            series: [{
                name: 'Reward',
                type: 'line',
                data: [],
                smooth: true,
                lineStyle: { color: '#3b82f6', width: 2 },
                itemStyle: { color: '#3b82f6' },
                areaStyle: {
                    color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                        { offset: 0, color: 'rgba(59, 130, 246, 0.3)' },
                        { offset: 1, color: 'rgba(59, 130, 246, 0.05)' }
                    ])
                }
            }]
        });
    }

    _setActionChartOption() {
        this.charts.action.setOption({
            title: { text: 'Action 分佈', left: 'center', textStyle: { color: '#334155', fontSize: 14, fontWeight: 600 } },
            tooltip: { trigger: 'axis' },
            grid: { left: '10%', right: '10%', bottom: '15%', top: '15%' },
            xAxis: { type: 'category', data: [], axisLabel: { color: '#94a3b8' } },
            yAxis: { type: 'value', axisLabel: { color: '#94a3b8' } },
            series: [{
                name: 'Action',
                type: 'bar',
                data: [],
                itemStyle: { color: '#10b981' }
            }]
        });
    }

    _setQValueChartOption() {
        this.charts.qval.setOption({
            title: { text: 'Q-Value 分佈', left: 'center', textStyle: { color: '#334155', fontSize: 14, fontWeight: 600 } },
            tooltip: { trigger: 'axis' },
            grid: { left: '10%', right: '10%', bottom: '15%', top: '15%' },
            xAxis: { type: 'category', data: [], axisLabel: { color: '#94a3b8' } },
            yAxis: { type: 'value', axisLabel: { color: '#94a3b8' } },
            series: []
        });
    }

    updateFeatureChart(data) {
        if (!data || !data.features) return;

        const steps = data.steps || [];
        const features = data.features || {};

        const series = Object.keys(features).map(key => ({
            name: key,
            type: 'line',
            data: features[key],
            smooth: true
        }));

        this.charts.feature.setOption({
            xAxis: { data: steps },
            series: series,
            legend: { data: Object.keys(features) }
        });
    }

    updateRewardChart(data) {
        if (!data || !data.steps) return;

        this.charts.reward.setOption({
            xAxis: { data: data.steps },
            series: [{ data: data.rewards || [] }]
        });
    }

    updateActionChart(data) {
        if (!data || !data.steps) return;

        this.charts.action.setOption({
            xAxis: { data: data.steps },
            series: [{ data: data.actions || [] }]
        });
    }

    updateQValueChart(data) {
        if (!data || !data.steps) return;

        const qValues = data.q_values || {};
        const series = Object.keys(qValues).map(key => ({
            name: key,
            type: 'line',
            data: qValues[key],
            smooth: true
        }));

        this.charts.qval.setOption({
            xAxis: { data: data.steps },
            series: series,
            legend: { data: Object.keys(qValues) }
        });
    }

    resizeAll() {
        Object.values(this.charts).forEach(chart => {
            if (chart && chart.resize) {
                chart.resize();
            }
        });
    }

    clear() {
        this.charts.feature.clear();
        this.charts.reward.clear();
        this.charts.action.clear();
        this.charts.qval.clear();
        this._setFeatureChartOption();
        this._setRewardChartOption();
        this._setActionChartOption();
        this._setQValueChartOption();
    }
}
