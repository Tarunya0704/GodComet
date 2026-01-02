// Main Electron Process - SIMPLIFIED VERSION
import { app, BrowserWindow, globalShortcut, ipcMain } from 'electron'
import path from 'path'
import axios from 'axios'

const BACKEND_URL = 'http://localhost:8001'

class GodCometApp {
  private commandWindow: BrowserWindow | null = null

  async initialize() {
    await app.whenReady()
    
    // Register Cmd+Space hotkey
    const hotkey = process.platform === 'darwin' ? 'Command+Space' : 'Control+Space'
    globalShortcut.register(hotkey, () => {
      console.log('Hotkey pressed!')
      this.showCommandWindow()
    })
    
    console.log(`✅ GodComet ready! Press ${hotkey}`)
    
    // Setup IPC handlers
    this.setupIPC()
  }

  private showCommandWindow() {
    if (this.commandWindow) {
      this.commandWindow.show()
      this.commandWindow.focus()
      return
    }

    // Create floating window
    this.commandWindow = new BrowserWindow({
      width: 700,
      height: 400,
      frame: false,
      transparent: true,
      alwaysOnTop: true,
      webPreferences: {
        nodeIntegration: false,
        contextIsolation: true,
        preload: path.join(__dirname, '../preload/index.js')
      }
    })

    // Load UI
    this.commandWindow.loadFile(path.join(__dirname, '../renderer/index.html'))

    // Hide on blur
    this.commandWindow.on('blur', () => {
      this.commandWindow?.hide()
    })
  }

  private setupIPC() {
    // Execute command
    ipcMain.handle('execute-command', async (event, command: string) => {
      try {
        // Get context (simplified)
        const context = {
          app: 'Unknown',
          window: ''
        }

        // Send to backend
        const response = await axios.post(`${BACKEND_URL}/execute`, {
          command,
          context
        })

        return response.data
      } catch (error: any) {
        return {
          success: false,
          error: error.message
        }
      }
    })

    // Hide window
    ipcMain.handle('hide-window', () => {
      this.commandWindow?.hide()
    })
  }
}

// Start app
const godcomet = new GodCometApp()
app.on('ready', () => godcomet.initialize())

// Cleanup
app.on('will-quit', () => {
  globalShortcut.unregisterAll()
})