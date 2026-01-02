// // Detects what app user is in and what they're doing
// import { exec } from 'child_process'
// import { promisify } from 'util'
// import activeWin from 'active-win'
// import clipboardy from 'clipboardy'
// import screenshot from 'node-screenshot'

// const execAsync = promisify(exec)

// export interface Context {
//   app: string                    // Active app name
//   window: string                 // Window title
//   file?: string                  // Current file (if applicable)
//   selectedText?: string          // Selected text
//   clipboardContent?: string      // Clipboard
//   screenshot?: Buffer            // Screenshot
//   url?: string                   // Current URL (if browser)
// }

// export class ContextDetector {
//   async getCurrentContext(): Promise<Context> {
//     try {
//       // Get active window
//       const window = await activeWin()
      
//       // Get clipboard
//       const clipboard = await clipboardy.read()
      
//       // Get selected text (platform-specific)
//       const selectedText = await this.getSelectedText()
      
//       // Take screenshot
//       const screenshotBuffer = await this.takeScreenshot()
      
//       const context: Context = {
//         app: window?.owner?.name || 'Unknown',
//         window: window?.title || '',
//         clipboardContent: clipboard,
//         selectedText,
//         screenshot: screenshotBuffer
//       }
      
//       // App-specific context
//       if (context.app.includes('Chrome') || context.app.includes('Firefox')) {
//         context.url = await this.getBrowserURL()
//       }
      
//       if (context.app.includes('Code') || context.app.includes('VSCode')) {
//         context.file = await this.getVSCodeCurrentFile()
//       }
      
//       return context
//     } catch (error) {
//       console.error('Context detection failed:', error)
//       return {
//         app: 'Unknown',
//         window: ''
//       }
//     }
//   }
  
//   private async getSelectedText(): Promise<string | undefined> {
//     try {
//       // Simulate Cmd+C to copy selection
//       // Then read clipboard
//       // Platform-specific implementation needed
//       return undefined
//     } catch {
//       return undefined
//     }
//   }
  
//   private async takeScreenshot(): Promise<Buffer | undefined> {
//     return new Promise((resolve) => {
//       screenshot.saveScreenshot((err, img) => {
//         if (err) resolve(undefined)
//         else resolve(img)
//       })
//     })
//   }
  
//   private async getBrowserURL(): Promise<string | undefined> {
//     // Connect to Chrome extension to get current URL
//     // Implementation depends on extension setup
//     return undefined
//   }
  
//   private async getVSCodeCurrentFile(): Promise<string | undefined> {
//     // Connect to VS Code extension
//     return undefined
//   }
// }

// AI Brain - Connects to Python backend
import axios from 'axios'
import { Context } from './context'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8001'

export interface CommandResult {
  success: boolean
  message: string
  data?: any
  error?: string
  actions?: Array<{
    type: string
    description: string
    status: string
    result?: any
  }>
  executionTime?: number
}

export class AIBrain {
  private backendUrl: string

  constructor(backendUrl: string = BACKEND_URL) {
    this.backendUrl = backendUrl
    console.log(`🤖 AI Brain initialized - Backend: ${this.backendUrl}`)
  }

  async executeCommand(command: string, context: Context): Promise<CommandResult> {
    try {
      console.log(`🧠 Processing command: "${command}"`)
      console.log(`📍 Context: ${context.app} - ${context.window}`)

      // Check backend health
      const isHealthy = await this.checkHealth()
      if (!isHealthy) {
        return {
          success: false,
          message: 'Backend server not available',
          error: 'Cannot connect to backend. Make sure Python server is running on port 8001'
        }
      }

      // Send to backend
      const response = await axios.post(
        `${this.backendUrl}/execute`,
        {
          command,
          context: {
            app: context.app,
            window: context.window,
            file: context.file,
            url: context.url,
            selectedText: context.selectedText,
            clipboard: context.clipboardContent
          }
        },
        {
          timeout: 120000 // 2 minutes timeout
        }
      )

      return response.data

    } catch (error: any) {
      console.error('AI execution failed:', error)
      
      if (error.code === 'ECONNREFUSED') {
        return {
          success: false,
          message: 'Backend server not running',
          error: 'Please start the Python backend: cd backend && python brain.py'
        }
      }

      return {
        success: false,
        message: 'Command execution failed',
        error: error.message
      }
    }
  }

  async checkHealth(): Promise<boolean> {
    try {
      const response = await axios.get(`${this.backendUrl}/health`, { timeout: 5000 })
      return response.data.status === 'ok'
    } catch {
      return false
    }
  }

  async getAvailableTools(): Promise<string[]> {
    try {
      const response = await axios.get(`${this.backendUrl}/tools`)
      return response.data.tools || []
    } catch {
      return []
    }
  }
}