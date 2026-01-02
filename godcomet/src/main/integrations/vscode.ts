// VS Code Integration
import { Integration } from './manager'
import WebSocket, { WebSocketServer } from 'ws'

export class VSCodeIntegration implements Integration {
  name = 'vscode'
  enabled = true
  configured = false
  private ws: WebSocket | null = null
  private port = 8765

  async initialize() {
    this.configured = false
  }

  isConfigured(): boolean {
    return this.configured
  }

  async configure(config: { enabled: boolean }) {
    this.enabled = config.enabled
    if (this.enabled) {
      await this.startServer()
    }
  }

  async execute(action: any): Promise<any> {
    if (!this.configured || !this.ws) {
      throw new Error('VS Code not connected')
    }

    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        reject(new Error('VS Code action timeout'))
      }, 10000)

      this.ws!.once('message', (data: Buffer) => {
        clearTimeout(timeout)
        resolve(JSON.parse(data.toString()))
      })

      this.ws!.send(JSON.stringify(action))
    })
  }

  private async startServer() {
    const wss = new WebSocketServer({ port: this.port })
    
    wss.on('connection', (ws: WebSocket) => {
      console.log('✅ VS Code extension connected')
      this.ws = ws
      this.configured = true

      ws.on('close', () => {
        console.log('⚠️  VS Code extension disconnected')
        this.configured = false
        this.ws = null
      })
    })

    console.log(`🔌 Waiting for VS Code extension on port ${this.port}`)
  }

  async getCurrentFile(): Promise<string | null> {
    const result = await this.execute({ type: 'getCurrentFile' })
    return result.file
  }

  async getSelection(): Promise<string | null> {
    const result = await this.execute({ type: 'getSelection' })
    return result.text
  }

  async runCommand(command: string, args?: any) {
    return await this.execute({ type: 'runCommand', command, args })
  }

  async insertText(text: string) {
    return await this.execute({ type: 'insertText', text })
  }
}