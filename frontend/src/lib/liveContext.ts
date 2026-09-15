import { createContext, useContext } from 'react'

import type { LiveState } from './useWebSocket'

const EMPTY: LiveState = {
  connected: false,
  busy: false,
  runId: null,
  stage: null,
  stats: {},
  logs: [],
  finishedCount: 0,
}

export const LiveContext = createContext<LiveState>(EMPTY)

export const useLive = () => useContext(LiveContext)
