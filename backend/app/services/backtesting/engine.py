"""Backtesting engine for strategy validation."""
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from enum import Enum

@dataclass
class Trade:
    entry_date: datetime
    exit_date: Optional[datetime]
    entry_price: float
    exit_price: Optional[float]
    quantity: int
    side: str  # 'long' or 'short'
    pnl: float = 0
    pnl_pct: float = 0
    is_open: bool = True
    
@dataclass
class BacktestResult:
    strategy_name: str
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_capital: float
    total_return: float
    total_return_pct: float
    annualized_return: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    max_drawdown_pct: float
    win_rate: float
    profit_factor: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_win: float
    avg_loss: float
    best_trade: float
    worst_trade: float
    avg_holding_period: timedelta
    trades: List[Trade]
    equity_curve: List[float]
    benchmark_return: float
    alpha: float
    beta: float
    
class OptimizationType(Enum):
    GRID_SEARCH = "grid_search"
    RANDOM_SEARCH = "random_search"
    WALK_FORWARD = "walk_forward"
    MONTE_CARLO = "monte_carlo"
    
class BacktestingEngine:
    """Comprehensive backtesting engine with optimization and analysis."""
    
    def __init__(self, initial_capital: float = 100000):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.trades: List[Trade] = []
        self.equity_curve: List[float] = [initial_capital]
        self.positions: Dict[str, Trade] = {}
        
    async def backtest(
        self,
        strategy: Callable,
        data: pd.DataFrame,
        params: Dict[str, Any] = None,
        commission: float = 0.001,  # 0.1%
        slippage: float = 0.0005    # 0.05%
    ) -> BacktestResult:
        """Run backtest on historical data."""
        
        self.reset()
        params = params or {}
        
        # Process each bar
        for i in range(len(data)):
            current_bar = data.iloc[i]
            historical_data = data.iloc[:i+1]
            
            # Generate signals
            signals = await strategy(historical_data, **params)
            
            # Process signals
            await self._process_signals(
                signals,
                current_bar,
                commission,
                slippage
            )
            
            # Update equity curve
            self._update_equity(current_bar)
            
        # Close any open positions
        if len(data) > 0:
            self._close_all_positions(data.iloc[-1])
        
        # Calculate metrics
        return self._calculate_metrics(
            strategy.__name__ if hasattr(strategy, '__name__') else 'Strategy',
            data
        )
        
    async def optimize(
        self,
        strategy: Callable,
        data: pd.DataFrame,
        param_grid: Dict[str, List[Any]],
        optimization_type: OptimizationType = OptimizationType.GRID_SEARCH,
        metric: str = 'sharpe_ratio',
        n_splits: int = 5
    ) -> Dict[str, Any]:
        """Optimize strategy parameters."""
        
        if optimization_type == OptimizationType.GRID_SEARCH:
            return await self._grid_search(strategy, data, param_grid, metric)
        elif optimization_type == OptimizationType.WALK_FORWARD:
            return await self._walk_forward(strategy, data, param_grid, metric, n_splits)
        elif optimization_type == OptimizationType.MONTE_CARLO:
            return await self._monte_carlo(strategy, data, param_grid, metric)
        else:
            return await self._random_search(strategy, data, param_grid, metric)
            
    async def _grid_search(
        self,
        strategy: Callable,
        data: pd.DataFrame,
        param_grid: Dict[str, List[Any]],
        metric: str
    ) -> Dict[str, Any]:
        """Grid search optimization."""
        
        best_params = None
        best_score = -float('inf')
        all_results = []
        
        # Generate all parameter combinations
        param_combinations = self._generate_param_combinations(param_grid)
        
        for params in param_combinations:
            result = await self.backtest(strategy, data, params)
            score = getattr(result, metric, 0)
            
            all_results.append({
                'params': params,
                'score': score,
                'result': result
            })
            
            if score > best_score:
                best_score = score
                best_params = params
                
        return {
            'best_params': best_params,
            'best_score': best_score,
            'all_results': all_results
        }
        
    async def _walk_forward(
        self,
        strategy: Callable,
        data: pd.DataFrame,
        param_grid: Dict[str, List[Any]],
        metric: str,
        n_splits: int
    ) -> Dict[str, Any]:
        """Walk-forward optimization."""
        
        results = []
        split_size = len(data) // n_splits
        
        for i in range(n_splits - 1):
            # Training data
            train_start = i * split_size
            train_end = (i + 2) * split_size
            train_data = data.iloc[train_start:train_end]
            
            # Test data
            test_start = train_end
            test_end = min(test_start + split_size, len(data))
            test_data = data.iloc[test_start:test_end]
            
            # Optimize on training data
            opt_result = await self._grid_search(strategy, train_data, param_grid, metric)
            
            # Test on out-of-sample data
            test_result = await self.backtest(strategy, test_data, opt_result['best_params'])
            
            results.append({
                'train_period': (train_start, train_end),
                'test_period': (test_start, test_end),
                'best_params': opt_result['best_params'],
                'train_score': opt_result['best_score'],
                'test_score': getattr(test_result, metric, 0),
                'test_result': test_result
            })
            
        return {
            'results': results,
            'avg_test_score': np.mean([r['test_score'] for r in results]),
            'stability': np.std([r['test_score'] for r in results])
        }
        
    async def _monte_carlo(
        self,
        strategy: Callable,
        data: pd.DataFrame,
        param_grid: Dict[str, List[Any]],
        metric: str,
        n_simulations: int = 100
    ) -> Dict[str, Any]:
        """Monte Carlo simulation."""
        
        results = []
        
        for _ in range(n_simulations):
            # Randomly sample parameters
            params = {k: np.random.choice(v) for k, v in param_grid.items()}
            
            # Add random noise to data
            noisy_data = self._add_noise_to_data(data)
            
            # Run backtest
            result = await self.backtest(strategy, noisy_data, params)
            
            results.append({
                'params': params,
                'score': getattr(result, metric, 0),
                'result': result
            })
            
        # Calculate statistics
        scores = [r['score'] for r in results]
        
        return {
            'mean_score': np.mean(scores),
            'std_score': np.std(scores),
            'best_score': max(scores),
            'worst_score': min(scores),
            'percentiles': {
                '5%': np.percentile(scores, 5),
                '25%': np.percentile(scores, 25),
                '50%': np.percentile(scores, 50),
                '75%': np.percentile(scores, 75),
                '95%': np.percentile(scores, 95)
            },
            'results': results
        }
        
    async def _process_signals(
        self,
        signals: Dict[str, Any],
        current_bar: pd.Series,
        commission: float,
        slippage: float
    ):
        """Process trading signals."""
        
        symbol = signals.get('symbol', 'DEFAULT')
        action = signals.get('action', 'hold')
        quantity = signals.get('quantity', 0)
        
        if action == 'buy' and symbol not in self.positions:
            self._open_position(
                symbol,
                current_bar,
                quantity,
                'long',
                commission,
                slippage
            )
        elif action == 'sell' and symbol in self.positions:
            self._close_position(
                symbol,
                current_bar,
                commission,
                slippage
            )
        elif action == 'short' and symbol not in self.positions:
            self._open_position(
                symbol,
                current_bar,
                quantity,
                'short',
                commission,
                slippage
            )
        elif action == 'cover' and symbol in self.positions:
            self._close_position(
                symbol,
                current_bar,
                commission,
                slippage
            )
            
    def _open_position(
        self,
        symbol: str,
        bar: pd.Series,
        quantity: int,
        side: str,
        commission: float,
        slippage: float
    ):
        """Open a new position."""
        
        price = bar.get('close', bar.get('price', 0))
        
        # Apply slippage
        if side == 'long':
            price *= (1 + slippage)
        else:
            price *= (1 - slippage)
            
        # Calculate commission
        cost = quantity * price * (1 + commission)
        
        if cost <= self.capital:
            trade = Trade(
                entry_date=bar.name if hasattr(bar, 'name') else datetime.now(),
                exit_date=None,
                entry_price=price,
                exit_price=None,
                quantity=quantity,
                side=side,
                is_open=True
            )
            
            self.positions[symbol] = trade
            self.capital -= cost
            
    def _close_position(
        self,
        symbol: str,
        bar: pd.Series,
        commission: float,
        slippage: float
    ):
        """Close an existing position."""
        
        if symbol not in self.positions:
            return
            
        trade = self.positions[symbol]
        price = bar.get('close', bar.get('price', 0))
        
        # Apply slippage
        if trade.side == 'long':
            price *= (1 - slippage)
        else:
            price *= (1 + slippage)
            
        trade.exit_date = bar.name if hasattr(bar, 'name') else datetime.now()
        trade.exit_price = price
        trade.is_open = False
        
        # Calculate P&L
        if trade.side == 'long':
            trade.pnl = (price - trade.entry_price) * trade.quantity
        else:
            trade.pnl = (trade.entry_price - price) * trade.quantity
            
        # Apply commission
        trade.pnl -= trade.quantity * price * commission
        trade.pnl_pct = trade.pnl / (trade.entry_price * trade.quantity) * 100
        
        self.capital += trade.quantity * price * (1 - commission)
        self.trades.append(trade)
        del self.positions[symbol]
        
    def _close_all_positions(self, bar: pd.Series):
        """Close all open positions."""
        
        for symbol in list(self.positions.keys()):
            self._close_position(symbol, bar, 0, 0)
            
    def _update_equity(self, bar: pd.Series):
        """Update equity curve."""
        
        total_equity = self.capital
        
        # Add unrealized P&L
        for symbol, trade in self.positions.items():
            price = bar.get('close', bar.get('price', trade.entry_price))
            
            if trade.side == 'long':
                unrealized_pnl = (price - trade.entry_price) * trade.quantity
            else:
                unrealized_pnl = (trade.entry_price - price) * trade.quantity
                
            total_equity += unrealized_pnl
            
        self.equity_curve.append(total_equity)
        
    def _calculate_metrics(self, strategy_name: str, data: pd.DataFrame) -> BacktestResult:
        """Calculate backtest metrics."""
        
        equity_array = np.array(self.equity_curve)
        returns = np.diff(equity_array) / equity_array[:-1]
        
        # Basic metrics
        total_return = self.equity_curve[-1] - self.initial_capital
        total_return_pct = total_return / self.initial_capital * 100
        
        # Annualized return
        n_days = len(data)
        n_years = n_days / 252
        annualized_return = (self.equity_curve[-1] / self.initial_capital) ** (1/n_years) - 1 if n_years > 0 else 0
        
        # Sharpe ratio (assuming 0% risk-free rate)
        sharpe_ratio = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0
        
        # Sortino ratio
        downside_returns = returns[returns < 0]
        downside_std = np.std(downside_returns) if len(downside_returns) > 0 else 1
        sortino_ratio = np.mean(returns) / downside_std * np.sqrt(252) if downside_std > 0 else 0
        
        # Maximum drawdown
        running_max = np.maximum.accumulate(equity_array)
        drawdown = (equity_array - running_max) / running_max
        max_drawdown_pct = np.min(drawdown) * 100
        max_drawdown = np.min(equity_array - running_max)
        
        # Trade statistics
        winning_trades = [t for t in self.trades if t.pnl > 0]
        losing_trades = [t for t in self.trades if t.pnl <= 0]
        
        win_rate = len(winning_trades) / len(self.trades) * 100 if self.trades else 0
        
        avg_win = np.mean([t.pnl for t in winning_trades]) if winning_trades else 0
        avg_loss = np.mean([t.pnl for t in losing_trades]) if losing_trades else 0
        
        profit_factor = abs(sum(t.pnl for t in winning_trades) / sum(t.pnl for t in losing_trades)) if losing_trades and sum(t.pnl for t in losing_trades) != 0 else 0
        
        best_trade = max([t.pnl for t in self.trades]) if self.trades else 0
        worst_trade = min([t.pnl for t in self.trades]) if self.trades else 0
        
        # Average holding period
        holding_periods = []
        for trade in self.trades:
            if trade.exit_date and trade.entry_date:
                holding_periods.append(trade.exit_date - trade.entry_date)
        avg_holding = sum(holding_periods, timedelta()) / len(holding_periods) if holding_periods else timedelta()
        
        # Benchmark comparison (buy and hold)
        benchmark_return = (data.iloc[-1]['close'] - data.iloc[0]['close']) / data.iloc[0]['close'] * 100 if len(data) > 0 else 0
        
        # Alpha and beta (simplified)
        alpha = total_return_pct - benchmark_return
        beta = np.cov(returns, np.diff(data['close'].values))[0, 1] / np.var(np.diff(data['close'].values)) if len(data) > 1 else 1
        
        return BacktestResult(
            strategy_name=strategy_name,
            start_date=data.index[0] if len(data) > 0 else datetime.now(),
            end_date=data.index[-1] if len(data) > 0 else datetime.now(),
            initial_capital=self.initial_capital,
            final_capital=self.equity_curve[-1],
            total_return=total_return,
            total_return_pct=total_return_pct,
            annualized_return=annualized_return * 100,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            max_drawdown=max_drawdown,
            max_drawdown_pct=max_drawdown_pct,
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_trades=len(self.trades),
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            avg_win=avg_win,
            avg_loss=avg_loss,
            best_trade=best_trade,
            worst_trade=worst_trade,
            avg_holding_period=avg_holding,
            trades=self.trades,
            equity_curve=self.equity_curve,
            benchmark_return=benchmark_return,
            alpha=alpha,
            beta=beta
        )
        
    def reset(self):
        """Reset backtesting engine."""
        self.capital = self.initial_capital
        self.trades = []
        self.equity_curve = [self.initial_capital]
        self.positions = {}
        
    def _generate_param_combinations(self, param_grid: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
        """Generate all parameter combinations."""
        import itertools
        
        keys = param_grid.keys()
        values = param_grid.values()
        
        combinations = []
        for combo in itertools.product(*values):
            combinations.append(dict(zip(keys, combo)))
            
        return combinations
        
    def _add_noise_to_data(self, data: pd.DataFrame, noise_level: float = 0.01) -> pd.DataFrame:
        """Add random noise to data for Monte Carlo simulation."""
        noisy_data = data.copy()
        
        for col in ['open', 'high', 'low', 'close']:
            if col in noisy_data.columns:
                noise = np.random.normal(0, noise_level, len(noisy_data))
                noisy_data[col] *= (1 + noise)
                
        return noisy_data