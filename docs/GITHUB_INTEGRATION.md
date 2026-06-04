# GitHub 资源集成说明（PDF → 本仓库）

来源：`GlobalAi26- DOC- QuantFin_RiskManagement.pdf` 中 **TRADING / CRYPTO** 与 **TRADING / POLYMARKET** 章节。

## 已接入（代码可运行）

| GitHub / API | 集成位置 | 说明 |
|--------------|----------|------|
| [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) | 本仓库 + `scripts/polymarket_meme_run.py` | 多智能体 LLM 分析 meme 标的 |
| [nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader) | `tradingagents/dataflows/nautilus_data.py` | `POLY:<slug>`；数据不足时回退 CLOB |
| [Polymarket/agents](https://github.com/Polymarket/agents) 数据模式 | `polymarket_gamma.py`, `polymarket_discovery.py` | Gamma + CLOB 公开 API（与官方 agent-skills 一致） |
| Polymarket Docs / CLOB | `polymarket_gamma.py` | `prices-history`, `markets?slug=` |
| yfinance + CoinGecko | `polymarket_meme_dashboard.py` | Meme 币现货 OHLCV |

## 已文档化、未嵌入仓库（需单独部署）

| GitHub | PDF 用途 | 建议 |
|--------|----------|------|
| [Brunofancy/polymarket-copy-trading-bot-agent](https://github.com/Brunofancy/polymarket-copy-trading-bot-agent) | AI 跟单 | 需 Polymarket 钱包/API |
| [texsellix/polymarket-trading-bot](https://github.com/texsellix/polymarket-trading-bot) | 鲸鱼镜像 | 独立 CLI |
| [quiknode-labs/qn-guide-examples](https://github.com/quiknode-labs/qn-guide-examples) | copy-bot 教程 | `defi/polymarket-copy-bot` |
| [harish-garg/Awesome-Polymarket-Tools](https://github.com/harish-garg/Awesome-Polymarket-Tools) | 工具索引 | Phase 2 套利扫描 |
| [shiyu-coder/Kronos](https://github.com/shiyu-coder/Kronos) | K 线基础模型 | Phase 2 信号 |
| [microsoft/qlib](https://github.com/microsoft/qlib) | `qlib_bridge.py`, `polymarket_walkforward_qlib.py` | CSV 导出 + LGBModel（可选）/ sklearn 回退 |
| [ChangeYourself0613/Solana-Arbitrage-Bot](https://github.com/ChangeYourself0613/Solana-Arbitrage-Bot) | `integrations/solana_arbitrage`, `solana_arb_bridge.py` | PDF 三选一：**Rust/Jito**（#3） |

完整字典见：`tradingagents/dataflows/polymarket_discovery.py` → `GITHUB_RESOURCES`。

## Dashboard 产出图表

运行 `python scripts/polymarket_meme_run.py dashboard` 后：

| 文件 | 内容 |
|------|------|
| `polymarket_meme_dashboard.png` | 主面板：EMA 信号、组合净值、回撤、情景、Monte Carlo、宏观相关 |
| `polymarket_meme_charts_meme.png` | Meme：归一化指数、实现波动、Sharpe 柱、相关性、分资产 P&L |
| `polymarket_meme_charts_polymarket.png` | Polymarket：隐含概率 (Yes %) 时间序列 |
| `polymarket_meme_charts_cross.png` | POLY×DOGE 滚动相关、组合权重、underwater、超额收益 |
| `polymarket_meme_charts_performance.png` | CAGR vs 回撤散点、胜率柱 |
| `polymarket_active_markets.png` | Gamma API 活跃市场成交量/概率 |
| `polymarket_meme_metrics.csv` | 指标表 + meme 相关矩阵 + GitHub 映射 |
