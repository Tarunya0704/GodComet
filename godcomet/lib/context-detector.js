const { exec } = require('child_process');
const util = require('util');
const execAsync = util.promisify(exec);
const { screen, clipboard } = require('electron');

class UniversalContextDetector {
  constructor() {
    this.lastClipboard = '';
    this.contextHistory = [];
  }

  /**
   * Get complete context from all sources
   */
  async getFullContext() {
    const context = {
      timestamp: Date.now(),
      app: 'Unknown',
      window: '',
      file: null,
      url: null,
      selectedText: null,
      clipboard: null,
      mousePosition: null,
      screenResolution: null,
      focusedElement: null
    };

    try {
      // 1. Active Window Detection
      const windowInfo = await this.getActiveWindow();
      context.app = windowInfo.app;
      context.window = windowInfo.title;

      // 2. Mouse Position
      context.mousePosition = screen.getCursorScreenPoint();
      context.screenResolution = screen.getPrimaryDisplay().size;

      // 3. Clipboard Content
      //context.clipboard = clipboard.readText();

      // 4. App-Specific Context
      const appContext = await this.getAppSpecificContext(context.app, context.window);
      Object.assign(context, appContext);

      // Store in history
      this.contextHistory.push(context);
      if (this.contextHistory.length > 100) {
        this.contextHistory.shift();
      }

      return context;
    } catch (error) {
      console.error('Context detection error:', error);
      return context;
    }
  }

  /**
   * Get active window info (Windows) - FIXED VERSION
   */
  async getActiveWindow() {
    if (process.platform !== 'win32') {
      return { app: 'Unknown', title: '' };
    }

    try {
      // ✅ FIXED: Use proper PowerShell escaping with -EncodedCommand
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
$process = Get-Process -Id $processId -ErrorAction SilentlyContinue
if ($process) {
  Write-Output "$($process.Name)|$($title.ToString())"
} else {
  Write-Output "Unknown|"
}
`.trim();

      // Use -NoProfile and -NonInteractive for better reliability
      const { stdout } = await execAsync(
        `powershell -NoProfile -NonInteractive -Command "${script.replace(/"/g, '\\"')}"`,
        { 
          timeout: 5000,
          windowsHide: true 
        }
      );
      
      const [app, title] = stdout.trim().split('|');
      
      return {
        app: this.normalizeAppName(app || 'Unknown'),
        title: title || ''
      };
    } catch (error) {
      // Silent fail - return Unknown instead of crashing
      console.log('Window detection skipped (optional feature)');
      return { app: 'Unknown', title: '' };
    }
  }

  /**
   * Get app-specific context
   */
  async getAppSpecificContext(appName, windowTitle) {
    const context = {};

    switch (appName) {
      case 'Code':
      case 'VSCode':
        // VS Code - file path from window title
        context.file = this.extractFilePathFromTitle(windowTitle);
        context.language = this.detectLanguage(context.file);
        break;

      case 'Chrome':
      case 'Firefox':
      case 'Edge':
      case 'Safari':
        // Browser - URL from window title
        context.url = this.extractUrlFromTitle(windowTitle);
        context.browserTab = windowTitle;
        break;

      case 'Figma':
        context.designFile = windowTitle;
        context.tool = 'Figma';
        break;

      case 'Slack':
        context.channel = this.extractSlackChannel(windowTitle);
        break;

      case 'Notion':
        context.page = windowTitle;
        break;

      case 'Excel':
      case 'Word':
      case 'PowerPoint':
        context.document = windowTitle;
        context.officeApp = appName;
        break;

      default:
        break;
    }

    return context;
  }

  /**
   * Normalize app names
   */
  normalizeAppName(rawName) {
    const appMap = {
      'Code': 'VSCode',
      'chrome': 'Chrome',
      'firefox': 'Firefox',
      'msedge': 'Edge',
      'Figma': 'Figma',
      'slack': 'Slack',
      'notion': 'Notion',
      'EXCEL': 'Excel',
      'WINWORD': 'Word',
      'POWERPNT': 'PowerPoint',
      'explorer': 'FileExplorer',
      'WindowsTerminal': 'Terminal',
      'cmd': 'CommandPrompt',
      'powershell': 'PowerShell'
    };

    const normalized = rawName.toLowerCase();
    for (const [key, value] of Object.entries(appMap)) {
      if (normalized.includes(key.toLowerCase())) {
        return value;
      }
    }

    return rawName;
  }

  /**
   * Extract file path from window title
   */
  extractFilePathFromTitle(title) {
    // VS Code format: "filename - path - Visual Studio Code"
    const match = title.match(/^(.+?)\s*-\s*(.+?)\s*-\s*Visual Studio Code/);
    if (match) {
      const filename = match[1];
      const path = match[2];
      return `${path}\\${filename}`;
    }
    return null;
  }

  /**
   * Extract URL from browser title
   */
  extractUrlFromTitle(title) {
    // Try to extract URL patterns
    const urlMatch = title.match(/(https?:\/\/[^\s]+)/);
    if (urlMatch) {
      return urlMatch[1];
    }
    return null;
  }

  /**
   * Extract Slack channel
   */
  extractSlackChannel(title) {
    const match = title.match(/^#([^\s]+)/);
    return match ? match[1] : null;
  }

  /**
   * Detect programming language from file extension
   */
  detectLanguage(filePath) {
    if (!filePath) return null;

    const ext = filePath.split('.').pop().toLowerCase();
    const langMap = {
      'js': 'javascript',
      'ts': 'typescript',
      'jsx': 'react',
      'tsx': 'react',
      'py': 'python',
      'java': 'java',
      'cpp': 'cpp',
      'c': 'c',
      'cs': 'csharp',
      'go': 'go',
      'rs': 'rust',
      'php': 'php',
      'rb': 'ruby',
      'swift': 'swift',
      'kt': 'kotlin',
      'html': 'html',
      'css': 'css',
      'json': 'json',
      'md': 'markdown'
    };

    return langMap[ext] || ext;
  }

  /**
   * Get context history
   */
  getHistory(limit = 10) {
    return this.contextHistory.slice(-limit);
  }
}

module.exports = UniversalContextDetector;