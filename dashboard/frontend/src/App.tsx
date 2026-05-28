import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Layout    from './components/Layout'
import Dashboard  from './pages/Dashboard'
import Chart      from './pages/Chart'
import Positions  from './pages/Positions'
import Trades     from './pages/Trades'
import Strategies from './pages/Strategies'
import Backtest   from './pages/Backtest'
import DailyPnL   from './pages/DailyPnL'

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
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
