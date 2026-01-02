// Figma Integration
import axios from 'axios'
import { Integration } from './manager'

export class FigmaIntegration implements Integration {
  name = 'figma'
  enabled = true
  configured = false
  private token: string | null = null
  private baseUrl = 'https://api.figma.com/v1'

  async initialize() {
    this.token = process.env.FIGMA_TOKEN || null
    this.configured = !!this.token
  }

  isConfigured(): boolean {
    return this.configured
  }

  async configure(config: { token: string }) {
    this.token = config.token
    this.configured = !!this.token
    await this.testConnection()
  }

  async execute(action: any): Promise<any> {
    if (!this.token) {
      throw new Error('Figma not configured')
    }

    switch (action.type) {
      case 'get_file':
        return await this.getFile(action.fileKey)
      
      case 'get_comments':
        return await this.getComments(action.fileKey)
      
      case 'export_node':
        return await this.exportNode(action.fileKey, action.nodeId, action.format)
      
      default:
        throw new Error(`Unknown action: ${action.type}`)
    }
  }

  private async testConnection() {
    const response = await axios.get(`${this.baseUrl}/me`, {
      headers: { 'X-Figma-Token': this.token! }
    })
    if (response.status !== 200) {
      throw new Error('Figma authentication failed')
    }
  }

  private async getFile(fileKey: string) {
    const response = await axios.get(`${this.baseUrl}/files/${fileKey}`, {
      headers: { 'X-Figma-Token': this.token! }
    })
    return response.data
  }

  private async getComments(fileKey: string) {
    const response = await axios.get(`${this.baseUrl}/files/${fileKey}/comments`, {
      headers: { 'X-Figma-Token': this.token! }
    })
    return response.data.comments
  }

  private async exportNode(fileKey: string, nodeId: string, format: string = 'png') {
    const response = await axios.get(
      `${this.baseUrl}/images/${fileKey}?ids=${nodeId}&format=${format}`,
      {
        headers: { 'X-Figma-Token': this.token! }
      }
    )
    return response.data.images
  }
}