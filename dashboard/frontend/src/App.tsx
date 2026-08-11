import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Layout    from './components/Layout'
import Dashboard  from './pages/Dashboard'
import Chart      from './pages/Chart'
import Positions  from './pages/Positions'
import Trades     from './pages/Trades'
import Strategies from './pages/Strategies'
import Backtest   from './pages/Backtest'
import DailyPnL   from './pages/DailyPnL'
import News       from './pages/News'
import Signals    from './pages/Signals'
import Copilot    from './pages/Copilot'
import Watchlists from './pages/Watchlists'
import Alerts     from './pages/Alerts'
import PortfolioRisk from './pages/PortfolioRisk'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index               element={<Dashboard />} />
          <Route path="chart"        element={<Chart />} />
          <Route path="positions"    element={<Positions />} />
          <Route path="trades"       element={<Trades />} />
          <Route path="strategies"   element={<Strategies />} />
          <Route path="backtest"     element={<Backtest />} />
          <Route path="daily"        element={<DailyPnL />} />
          <Route path="news"         element={<News />} />
          <Route path="signals"      element={<Signals />} />
          <Route path="copilot"      element={<Copilot />} />
          <Route path="watchlists"   element={<Watchlists />} />
          <Route path="alerts"       element={<Alerts />} />
          <Route path="risk"         element={<PortfolioRisk />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
