from tsmom import data, signals, backtest, metrics, config

prices = data.fetch_prices()
r = data.to_returns(prices)
cfg = config.primary_config()

pos = signals.target_positions(prices, r, cfg.lookback, cfg.vol_target,
                               tradeable=data.tradeable_mask(prices))
pos = signals.scale_to_portfolio_vol(pos, r)
pos = signals.apply_rebalance_schedule(pos, cfg.rebalance)
res = backtest.run_backtest(prices, pos)

print("=== PRIMARY CONFIG:", cfg.name, "===")
for k, v in metrics.summary(res.net_returns).items():
    print(f"  {k:16} {v}")
print("\nbreakeven cost:", round(backtest.breakeven_cost_bps(prices, pos), 1), "bp/side")
print("\n=== COST SENSITIVITY ===")
print(backtest.cost_sensitivity(prices, pos).to_string(index=False))
print("\n=== ABLATION (signal vs vol-scaling) ===")
print(backtest.ablation(prices, r, cfg.lookback, cfg.vol_target).to_string(index=False))
