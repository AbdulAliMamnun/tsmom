from tsmom import data

prices = data.fetch_prices()
print("shape:", prices.shape)
print("\nobservations per ticker:")
print(prices.notna().sum().sort_values())
print("\ndate range:", prices.index.min().date(), "to", prices.index.max().date())
