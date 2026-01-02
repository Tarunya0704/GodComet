// Chrome Integration
import { Integration } from './manager'
import WebSocket, { WebSocketServer } from 'ws'

export class ChromeIntegration implements Integration {
  name = 'chrome'
  enabled = true
  configured = false
  private ws: WebSocket | null = null
  private port = 8766

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
      throw new Error('Chrome not connected')
    }

    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        reject(new Error('Chrome action timeout'))
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
      console.log('✅ Chrome extension connected')
      this.ws = ws
      this.configured = true

      ws.on('close', () => {
        console.log('⚠️  Chrome extension disconnected')
        this.configured = false
        this.ws = null
      })
    })

    console.log(`🔌 Waiting for Chrome extension on port ${this.port}`)
  }

  async getCurrentTab(): Promise<any> {
    const result = await this.execute({ type: 'getCurrentTab' })
    return result.tab
  }

  async executeScript(code: string) {
    return await this.execute({ type: 'executeScript', code })
  }

  async createTab(url: string) {
    return await this.execute({ type: 'createTab', url })
  }

  async getPageContent(): Promise<string> {
    const result = await this.execute({ type: 'getPageContent' })
    return result.content
  }
}