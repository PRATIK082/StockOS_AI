# Options Desk Basics

When the user asks about options (chain, Greeks, strategies):

- Explain payoffs in terms of max profit, max loss, and breakevens first,
  Greeks second.
- Note the expiry: 0DTE and weekly expiries decay fast — say so explicitly.
- Distinguish exchange-published values (OI, LTP) from model-derived values
  (IV, Greeks); if inputs look degenerate (e.g. expiry today), say the derived
  values are unreliable instead of quoting them.
- For multi-leg strategies, list each leg with action, strike, expiry, and
  approximate premium when available.
