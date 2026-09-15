import React from 'react'
import ReactDOM from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'

import App from './App'
import Dashboard from './pages/Dashboard'
import Results from './pages/Results'
import Settings from './pages/Settings'
import Logs from './pages/Logs'
import './index.css'

const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: 'ergebnisse', element: <Results /> },
      { path: 'einstellungen', element: <Settings /> },
      { path: 'logs', element: <Logs /> },
    ],
  },
])

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
)
