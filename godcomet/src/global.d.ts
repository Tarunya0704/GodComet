// Global type declarations for Electron IPC

interface Window {
  electron: {
    executeCommand: (command: string) => Promise<any>
    hideWindow: () => Promise<void>
    getSettings: () => Promise<any>
    getIntegrationStatus: () => Promise<any>
    saveSettings: (settings: any) => Promise<void>
    configureIntegration: (name: string, config: any) => Promise<void>
    onContext: (callback: (context: any) => void) => void
  }
}