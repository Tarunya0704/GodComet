// Jira Integration
import axios from 'axios'
import { Integration } from './manager'

export class JiraIntegration implements Integration {
  name = 'jira'
  enabled = true
  configured = false
  private url: string | null = null
  private email: string | null = null
  private token: string | null = null

  async initialize() {
    this.url = process.env.JIRA_URL || null
    this.email = process.env.JIRA_EMAIL || null
    this.token = process.env.JIRA_API_TOKEN || null
    this.configured = !!(this.url && this.email && this.token)
  }

  isConfigured(): boolean {
    return this.configured
  }

  async configure(config: { url: string; email: string; token: string }) {
    this.url = config.url
    this.email = config.email
    this.token = config.token
    this.configured = true
    await this.testConnection()
  }

  async execute(action: any): Promise<any> {
    if (!this.configured) {
      throw new Error('Jira not configured')
    }

    switch (action.type) {
      case 'create_issue':
        return await this.createIssue(action.project, action.summary, action.description, action.issueType)
      
      case 'get_issues':
        return await this.getIssues(action.project)
      
      case 'transition_issue':
        return await this.transitionIssue(action.key, action.transitionId)
      
      case 'add_comment':
        return await this.addComment(action.key, action.comment)
      
      case 'search_issues':
        return await this.searchIssues(action.jql)
      
      default:
        throw new Error(`Unknown action: ${action.type}`)
    }
  }

  private async testConnection() {
    const auth = Buffer.from(`${this.email}:${this.token}`).toString('base64')
    const response = await axios.get(`${this.url}/rest/api/3/myself`, {
      headers: { Authorization: `Basic ${auth}` }
    })
    if (response.status !== 200) {
      throw new Error('Jira authentication failed')
    }
  }

  private async createIssue(project: string, summary: string, description: string, issueType: string = 'Task') {
    const auth = Buffer.from(`${this.email}:${this.token}`).toString('base64')
    const response = await axios.post(
      `${this.url}/rest/api/3/issue`,
      {
        fields: {
          project: { key: project },
          summary,
          description: {
            type: 'doc',
            version: 1,
            content: [
              {
                type: 'paragraph',
                content: [{ type: 'text', text: description }]
              }
            ]
          },
          issuetype: { name: issueType }
        }
      },
      {
        headers: {
          Authorization: `Basic ${auth}`,
          'Content-Type': 'application/json'
        }
      }
    )
    return response.data
  }

  private async getIssues(project: string) {
    const auth = Buffer.from(`${this.email}:${this.token}`).toString('base64')
    const response = await axios.get(
      `${this.url}/rest/api/3/search?jql=project=${project}`,
      {
        headers: { Authorization: `Basic ${auth}` }
      }
    )
    return response.data.issues
  }

  private async transitionIssue(key: string, transitionId: string) {
    const auth = Buffer.from(`${this.email}:${this.token}`).toString('base64')
    const response = await axios.post(
      `${this.url}/rest/api/3/issue/${key}/transitions`,
      { transition: { id: transitionId } },
      {
        headers: {
          Authorization: `Basic ${auth}`,
          'Content-Type': 'application/json'
        }
      }
    )
    return response.data
  }

  private async addComment(key: string, comment: string) {
    const auth = Buffer.from(`${this.email}:${this.token}`).toString('base64')
    const response = await axios.post(
      `${this.url}/rest/api/3/issue/${key}/comment`,
      {
        body: {
          type: 'doc',
          version: 1,
          content: [
            {
              type: 'paragraph',
              content: [{ type: 'text', text: comment }]
            }
          ]
        }
      },
      {
        headers: {
          Authorization: `Basic ${auth}`,
          'Content-Type': 'application/json'
        }
      }
    )
    return response.data
  }

  private async searchIssues(jql: string) {
    const auth = Buffer.from(`${this.email}:${this.token}`).toString('base64')
    const response = await axios.get(
      `${this.url}/rest/api/3/search?jql=${encodeURIComponent(jql)}`,
      {
        headers: { Authorization: `Basic ${auth}` }
      }
    )
    return response.data.issues
  }
}