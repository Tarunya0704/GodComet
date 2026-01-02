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

// Context Detection - Detects what user is doing
import { exec } from 'child_process'
import { promisify } from 'util'
import * as fs from 'fs'
import * as path from 'path'

const execAsync = promisify(exec)

export interface Context {
  app: string
  window: string
  file?: string
  url?: string
  selectedText?: string
  clipboardContent?: string
  timestamp: number
}

export class ContextDetector {
  private lastContext: Context | null = null

  async getCurrentContext(): Promise<Context> {
    const timestamp = Date.now()
    
    try {
      // Get active window info (platform-specific)
      const windowInfo = await this.getActiveWindow()
      
      // Get clipboard content
      const clipboard = await this.getClipboard()
      
      const context: Context = {
        app: windowInfo.app,
        window: windowInfo.title,
        clipboardContent: clipboard,
        timestamp
      }

      // Detect specific app contexts
      if (this.isChrome(context.app)) {
        context.url = await this.getChromeUrl()
      } else if (this.isVSCode(context.app)) {
        context.file = await this.getVSCodeFile()
      } else if (this.isTerminal(context.app)) {
        context.file = await this.getTerminalCwd()
      }

      this.lastContext = context
      return context

    } catch (error) {
      console.error('Context detection failed:', error)
      return {
        app: 'Unknown',
        window: '',
        timestamp
      }
    }
  }

  private async getActiveWindow(): Promise<{ app: string; title: string }> {
    try {
      if (process.platform === 'darwin') {
        // macOS
        const script = `
          tell application "System Events"
            set frontApp to first application process whose frontmost is true
            set appName to name of frontApp
            set windowTitle to name of front window of frontApp
            return appName & "|" & windowTitle
          end tell
        `
        const { stdout } = await execAsync(`osascript -e '${script}'`)
        const [app, title] = stdout.trim().split('|')
        return { app: app || 'Unknown', title: title || '' }

      } else if (process.platform === 'win32') {
        // Windows - using PowerShell
        const script = `
          Add-Type @"
            using System;
            using System.Runtime.InteropServices;
            using System.Text;
            public class Window {
              [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
              [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
              [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
            }
"@
          $hwnd = [Window]::GetForegroundWindow()
          $title = New-Object System.Text.StringBuilder 256
          [void][Window]::GetWindowText($hwnd, $title, 256)
          $processId = 0
          [void][Window]::GetWindowThreadProcessId($hwnd, [ref]$processId)
          $process = Get-Process -Id $processId
          Write-Output "$($process.Name)|$($title.ToString())"
        `
        const { stdout } = await execAsync(`powershell -Command "${script}"`)
        const [app, title] = stdout.trim().split('|')
        return { app: app || 'Unknown', title: title || '' }

      } else {
        // Linux - using xdotool
        const { stdout: windowId } = await execAsync('xdotool getactivewindow')
        const { stdout: windowName } = await execAsync(`xdotool getwindowname ${windowId.trim()}`)
        const { stdout: pid } = await execAsync(`xdotool getwindowpid ${windowId.trim()}`)
        const { stdout: appName } = await execAsync(`ps -p ${pid.trim()} -o comm=`)
        
        return {
          app: appName.trim() || 'Unknown',
          title: windowName.trim() || ''
        }
      }
    } catch (error) {
      return { app: 'Unknown', title: '' }
    }
  }

  private async getClipboard(): Promise<string | undefined> {
    try {
      if (process.platform === 'darwin') {
        const { stdout } = await execAsync('pbpaste')
        return stdout
      } else if (process.platform === 'win32') {
        const { stdout } = await execAsync('powershell Get-Clipboard')
        return stdout
      } else {
        const { stdout } = await execAsync('xclip -selection clipboard -o')
        return stdout
      }
    } catch {
      return undefined
    }
  }

  private isChrome(app: string): boolean {
    return /chrome|chromium|brave|edge/i.test(app)
  }

  private isVSCode(app: string): boolean {
    return /code|vscode|visual studio code/i.test(app)
  }

  private isTerminal(app: string): boolean {
    return /terminal|iterm|konsole|gnome-terminal|cmd|powershell/i.test(app)
  }

  private async getChromeUrl(): Promise<string | undefined> {
    // This requires Chrome extension to be installed
    // For now, return undefined
    // TODO: Implement Chrome extension communication
    return undefined
  }

  private async getVSCodeFile(): Promise<string | undefined> {
    // This requires VS Code extension to be installed
    // For now, try to get from window title
    if (this.lastContext?.window) {
      const match = this.lastContext.window.match(/([^/\\]+\.[a-z]+)/i)
      return match ? match[1] : undefined
    }
    return undefined
  }

  private async getTerminalCwd(): Promise<string | undefined> {
    try {
      // Try to get current directory from terminal
      if (process.platform === 'darwin') {
        const { stdout } = await execAsync('lsof -a -p $(pgrep -n Terminal) -d cwd -Fn | tail -1')
        return stdout.replace('n', '').trim()
      }
    } catch {
      return undefined
    }
  }

  getLastContext(): Context | null {
    return this.lastContext
  }
}