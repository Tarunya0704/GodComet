// GitHub Integration
import axios from 'axios'
import { Integration } from './manager'

export class GitHubIntegration implements Integration {
  name = 'github'
  enabled = true
  configured = false
  private token: string | null = null
  private baseUrl = 'https://api.github.com'

  async initialize() {
    this.token = process.env.GITHUB_TOKEN || null
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
      throw new Error('GitHub not configured')
    }

    switch (action.type) {
      case 'create_repo':
        return await this.createRepo(action.name, action.description, action.private)
      
      case 'create_pr':
        return await this.createPR(action.repo, action.title, action.body, action.head, action.base)
      
      case 'search_code':
        return await this.searchCode(action.query)
      
      case 'get_repos':
        return await this.getRepos()
      
      case 'create_issue':
        return await this.createIssue(action.repo, action.title, action.body)
      
      default:
        throw new Error(`Unknown action: ${action.type}`)
    }
  }

  private async testConnection() {
    const response = await axios.get(`${this.baseUrl}/user`, {
      headers: { Authorization: `token ${this.token}` }
    })
    if (response.status !== 200) {
      throw new Error('GitHub authentication failed')
    }
  }

  private async createRepo(name: string, description: string = '', isPrivate: boolean = false) {
    const response = await axios.post(
      `${this.baseUrl}/user/repos`,
      {
        name,
        description,
        private: isPrivate,
        auto_init: true
      },
      {
        headers: { Authorization: `token ${this.token}` }
      }
    )
    return response.data
  }

  private async createPR(repo: string, title: string, body: string, head: string, base: string = 'main') {
    const response = await axios.post(
      `${this.baseUrl}/repos/${repo}/pulls`,
      { title, body, head, base },
      {
        headers: { Authorization: `token ${this.token}` }
      }
    )
    return response.data
  }

  private async searchCode(query: string) {
    const response = await axios.get(`${this.baseUrl}/search/code`, {
      headers: { Authorization: `token ${this.token}` },
      params: { q: query }
    })
    return response.data.items
  }

  private async getRepos() {
    const response = await axios.get(`${this.baseUrl}/user/repos`, {
      headers: { Authorization: `token ${this.token}` },
      params: { sort: 'updated', per_page: 10 }
    })
    return response.data
  }

  private async createIssue(repo: string, title: string, body: string) {
    const response = await axios.post(
      `${this.baseUrl}/repos/${repo}/issues`,
      { title, body },
      {
        headers: { Authorization: `token ${this.token}` }
      }
    )
    return response.data
  }
}