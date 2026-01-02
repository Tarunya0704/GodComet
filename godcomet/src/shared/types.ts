// Shared TypeScript types

export interface Context {
  app: string
  window: string
  file?: string
  url?: string
  selectedText?: string
  clipboardContent?: string
  timestamp: number
}

export interface CommandResult {
  success: boolean
  message: string
  data?: any
  error?: string
  actions?: Action[]
  executionTime?: number
}

export interface Action {
  type: string
  description: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  result?: any
  error?: string
}

export interface Integration {
  name: string
  enabled: boolean
  configured: boolean
  status: 'connected' | 'disconnected' | 'error'
  config?: any
}

export interface Settings {
  hotkey: string
  theme: 'light' | 'dark' | 'auto'
  autoStart: boolean
  notifications: boolean
  integrations: {
    slack?: { token: string }
    github?: { token: string }
    jira?: { url: string; email: string; token: string }
    vscode?: { enabled: boolean }
    chrome?: { enabled: boolean }
    figma?: { token: string }
  }
}

export interface Tool {
  name: string
  description: string
  category: string
  enabled: boolean
}