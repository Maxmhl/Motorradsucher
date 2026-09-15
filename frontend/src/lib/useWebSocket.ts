import { useEffect, useRef, useState } from 'react'

import type { LogEntry, StageStat } from './api'

export interface PipelineEvent {
  type: 'hello' | 'run_started' | 'run_progress' | 'run_finished' | 'log'
  ts?: string
  payload: Record<string, unknown>
}

export interface LiveState {
  connected: boolean
  busy: boolean
  runId: number | null
  stage: string | null
  stats: Record<string, StageStat>
  logs: LogEntry[]
  /** Zaehlt bei jedem run_finished hoch - Seiten laden daraufhin neu. */
  finishedCount: number
}

const EMPTY: LiveState = {
  connected: false,
  busy: false,
  runId: null,
  stage: null,
  stats: {},
  logs: [],
  finishedCount: 0,
}

/**
 * Haelt eine WebSocket-Verbindung zum Backend und verbindet sich nach einem
 * Abbruch mit wachsendem Abstand neu.
 */
export function useLiveRun(maxLogs = 200): LiveState {
  const [state, setState] = useState<LiveState>(EMPTY)
  const socketRef = useRef<WebSocket | null>(null)
  const attemptRef = useRef(0)
  const timerRef = useRef<number | undefined>(undefined)

  useEffect(() => {
    let disposed = false

    const connect = () => {
      if (disposed) return
      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const socket = new WebSocket(`${protocol}://${window.location.host}/ws`)
      socketRef.current = socket

      socket.onopen = () => {
        attemptRef.current = 0
        setState((prev) => ({ ...prev, connected: true }))
      }

      socket.onmessage = (event) => {
        const data = JSON.parse(event.data) as PipelineEvent
        setState((prev) => {
          switch (data.type) {
            case 'hello':
              return {
                ...prev,
                busy: Boolean(data.payload.busy),
                runId: (data.payload.run_id as number) ?? null,
                stage: (data.payload.stage as string) ?? null,
                stats: (data.payload.stats as Record<string, StageStat>) ?? {},
              }
            case 'run_started':
              return {
                ...prev,
                busy: true,
                runId: data.payload.run_id as number,
                stats: {},
                logs: [],
              }
            case 'run_progress':
              return {
                ...prev,
                busy: true,
                runId: data.payload.run_id as number,
                stage: data.payload.stage as string,
                stats: data.payload.stats as Record<string, StageStat>,
              }
            case 'run_finished':
              return {
                ...prev,
                busy: false,
                stats: (data.payload.stats as Record<string, StageStat>) ?? prev.stats,
                finishedCount: prev.finishedCount + 1,
              }
            case 'log': {
              const entry = {
                id: Date.now() + Math.random(),
                run_id: (data.payload.run_id as number) ?? null,
                ts: data.ts ?? new Date().toISOString(),
                level: (data.payload.level as string) ?? 'info',
                stage: (data.payload.stage as string) ?? null,
                message: (data.payload.message as string) ?? '',
              }
              return { ...prev, logs: [...prev.logs, entry].slice(-maxLogs) }
            }
            default:
              return prev
          }
        })
      }

      const scheduleReconnect = () => {
        if (disposed) return
        setState((prev) => ({ ...prev, connected: false }))
        const delay = Math.min(1000 * 2 ** attemptRef.current, 15000)
        attemptRef.current += 1
        timerRef.current = window.setTimeout(connect, delay)
      }

      socket.onclose = scheduleReconnect
      socket.onerror = () => socket.close()
    }

    connect()
    return () => {
      disposed = true
      window.clearTimeout(timerRef.current)
      socketRef.current?.close()
    }
  }, [maxLogs])

  return state
}
