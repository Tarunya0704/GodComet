// Preload script - Bridge between main and renderer
import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('electron', {
  executeCommand: (command: string) => ipcRenderer.invoke('execute-command', command),
  hideWindow: () => ipcRenderer.invoke('hide-window')
})