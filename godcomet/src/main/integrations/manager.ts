// // Manages all app integrations
// import { SlackIntegration } from './slack'
// import { GitHubIntegration } from './github'
// import { JiraIntegration } from './jira'
// import { VSCodeIntegration } from './vscode'
// import { ChromeIntegration } from './chrome'
// import { FigmaIntegration } from './figma'

// export class IntegrationManager {
//   private integrations: Map<string, any>
  
//   constructor() {
//     this.integrations = new Map()
//   }
  
//   async initialize() {
//     // Initialize all integrations
//     this.integrations.set('slack', new SlackIntegration())
//     this.integrations.set('github', new GitHubIntegration())
//     this.integrations.set('jira', new JiraIntegration())
//     this.integrations.set('vscode', new VSCodeIntegration())
//     this.integrations.set('chrome', new ChromeIntegration())
//     this.integrations.set('figma', new FigmaIntegration())
    
//     // Initialize each
//     for (const [name, integration] of this.integrations) {
//       try {
//         await integration.initialize()
//         console.log(`✅ ${name} initialized`)
//       } catch (error) {
//         console.log(`⚠️  ${name} not configured`)
//       }
//     }
//   }
  
//   async executeAction(action: any) {
//     const integration = this.integrations.get(action.integration)
//     if (!integration) {
//       throw new Error(`Integration not found: ${action.integration}`)
//     }
    
//     return await integration.execute(action)
//   }
  
//   getStatus() {
//     const status: any = {}
//     for (const [name, integration] of this.integrations) {
//       status[name] = integration.isConfigured()
//     }
//     return status
//   }
  
//   async configure(name: string, config: any) {
//     const integration = this.integrations.get(name)
//     if (!integration) {
//       throw new Error(`Integration not found: ${name}`)
//     }
    
//     return await integration.configure(config)
//   }
// }

// Integration Manager - Manages all app integrations
import { SlackIntegration } from './slack'
import { GitHubIntegration } from './github'
import { JiraIntegration } from './jira'
import { VSCodeIntegration } from './vscode'
import { ChromeIntegration } from './chrome'
import { FigmaIntegration } from './figma'

export interface Integration {
  name: string
  enabled: boolean
  configured: boolean
  initialize(): Promise<void>
  isConfigured(): boolean
  configure(config: any): Promise<void>
  execute(action: any): Promise<any>
}

export class IntegrationManager {
  private integrations: Map<string, Integration>

  constructor() {
    this.integrations = new Map()
  }

  async initialize() {
    console.log('🔌 Initializing integrations...')

    // Register all integrations
    this.integrations.set('slack', new SlackIntegration())
    this.integrations.set('github', new GitHubIntegration())
    this.integrations.set('jira', new JiraIntegration())
    this.integrations.set('vscode', new VSCodeIntegration())
    this.integrations.set('chrome', new ChromeIntegration())
    this.integrations.set('figma', new FigmaIntegration())

    // Initialize each
    for (const [name, integration] of this.integrations) {
      try {
        await integration.initialize()
        if (integration.isConfigured()) {
          console.log(`✅ ${name} initialized`)
        } else {
          console.log(`⚠️  ${name} not configured`)
        }
      } catch (error) {
        console.log(`❌ ${name} initialization failed:`, error)
      }
    }
  }

  getIntegration(name: string): Integration | undefined {
    return this.integrations.get(name)
  }

  getAllIntegrations(): Map<string, Integration> {
    return this.integrations
  }

  async executeAction(integration: string, action: any): Promise<any> {
    const int = this.integrations.get(integration)
    if (!int) {
      throw new Error(`Integration not found: ${integration}`)
    }

    if (!int.isConfigured()) {
      throw new Error(`Integration not configured: ${integration}`)
    }

    return await int.execute(action)
  }

  getStatus() {
    const status: any = {}
    for (const [name, integration] of this.integrations) {
      status[name] = {
        enabled: integration.enabled,
        configured: integration.isConfigured()
      }
    }
    return status
  }

  async configure(name: string, config: any) {
    const integration = this.integrations.get(name)
    if (!integration) {
      throw new Error(`Integration not found: ${name}`)
    }

    await integration.configure(config)
    console.log(`✅ ${name} configured`)
  }
}