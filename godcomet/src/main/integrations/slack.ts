// Slack Integration
import axios from 'axios'
import { Integration } from './manager'

export class SlackIntegration implements Integration {
  name = 'slack'
  enabled = true
  configured = false
  private token: string | null = null
  private baseUrl = 'https://slack.com/api'

  async initialize() {
    // Load token from config/env
    this.token = process.env.SLACK_TOKEN || null
    this.configured = !!this.token
  }

  isConfigured(): boolean {
    return this.configured
  }

  async configure(config: { token: string }) {
    this.token = config.token
    this.configured = !!this.token
    
    // Test connection
    await this.testConnection()
  }

  async execute(action: any): Promise<any> {
    if (!this.token) {
      throw new Error('Slack not configured')
    }

    switch (action.type) {
      case 'send_message':
        return await this.sendMessage(action.channel, action.message)
      
      case 'get_channels':
        return await this.getChannels()
      
      case 'upload_file':
        return await this.uploadFile(action.file, action.channel)
      
      case 'get_messages':
        return await this.getMessages(action.channel, action.limit)
      
      default:
        throw new Error(`Unknown action: ${action.type}`)
    }
  }

  private async testConnection() {
    const response = await axios.get(`${this.baseUrl}/auth.test`, {
      headers: { Authorization: `Bearer ${this.token}` }
    })
    if (!response.data.ok) {
      throw new Error('Slack authentication failed')
    }
  }

  private async sendMessage(channel: string, text: string) {
    const response = await axios.post(
      `${this.baseUrl}/chat.postMessage`,
      { channel, text },
      { headers: { Authorization: `Bearer ${this.token}` } }
    )
    return response.data
  }

  private async getChannels() {
    const response = await axios.get(`${this.baseUrl}/conversations.list`, {
      headers: { Authorization: `Bearer ${this.token}` }
    })
    return response.data.channels
  }

  private async uploadFile(file: string, channel: string) {
    const FormData = require('form-data')
    const fs = require('fs')
    
    const form = new FormData()
    form.append('file', fs.createReadStream(file))
    form.append('channels', channel)

    const response = await axios.post(`${this.baseUrl}/files.upload`, form, {
      headers: {
        ...form.getHeaders(),
        Authorization: `Bearer ${this.token}`
      }
    })
    return response.data
  }

  private async getMessages(channel: string, limit: number = 10) {
    const response = await axios.get(`${this.baseUrl}/conversations.history`, {
      headers: { Authorization: `Bearer ${this.token}` },
      params: { channel, limit }
    })
    return response.data.messages
  }
}