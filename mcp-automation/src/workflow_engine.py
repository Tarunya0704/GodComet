"""
Smart Workflow Engine - Handles multi-step command execution
"""
import logging
from typing import List, Dict, Any
import asyncio

logger = logging.getLogger(__name__)

class WorkflowStep:
    def __init__(self, tool_name: str, args: dict, description: str):
        self.tool_name = tool_name
        self.args = args
        self.description = description
        self.result = None
        self.status = "pending"  # pending, running, completed, failed
        self.error = None

class WorkflowEngine:
    """Orchestrates complex multi-step workflows"""
    
    def __init__(self, mcp_server):
        self.mcp = mcp_server
        self.workflows = {}  # Store workflow templates
        
        # Register default workflows
        self._register_default_workflows()
    
    def _register_default_workflows(self):
        """Register common workflow patterns"""
        
        # Figma to Production Workflow
        self.workflows['figma_to_production'] = {
            'name': 'Figma Design to Live Website',
            'description': 'Convert Figma design to deployed website',
            'steps': [
                {
                    'tool': 'figma_to_website',
                    'description': 'Convert Figma design to code',
                    'required_params': ['figma_url', 'project_name']
                },
                {
                    'tool': 'github_create_repo',
                    'description': 'Create GitHub repository',
                    'use_result_from': 0,
                    'param_mapping': {'repo_name': 'project_name'}
                },
                {
                    'tool': 'github_push_code',
                    'description': 'Push code to GitHub',
                    'use_result_from': 0,
                    'param_mapping': {'local_path': 'local_path'}
                },
                {
                    'tool': 'vercel_deploy',
                    'description': 'Deploy to Vercel',
                    'use_result_from': 0,
                    'param_mapping': {'local_path': 'local_path'}
                }
            ]
        }
        
        # Code Documentation Workflow
        self.workflows['document_code'] = {
            'name': 'Generate Code Documentation',
            'description': 'Create comprehensive documentation from code',
            'steps': [
                {
                    'tool': 'file_read',
                    'description': 'Read source code',
                    'required_params': ['path']
                },
                {
                    'tool': 'create_document_and_presentation',
                    'description': 'Generate documentation',
                    'use_result_from': 0,
                    'param_mapping': {'request': lambda r: f"Document this code: {r['content']}"}
                }
            ]
        }
        
        # Project Setup Workflow
        self.workflows['setup_project'] = {
            'name': 'Complete Project Setup',
            'description': 'Create repo, setup structure, deploy',
            'steps': [
                {
                    'tool': 'github_create_repo',
                    'description': 'Create GitHub repository',
                    'required_params': ['repo_name', 'description']
                },
                {
                    'tool': 'file_write',
                    'description': 'Create README',
                    'params': {
                        'path': 'README.md',
                        'content': lambda r: f"# {r['repo_name']}\n\n{r['description']}"
                    }
                },
                {
                    'tool': 'github_push_code',
                    'description': 'Push initial commit',
                    'use_result_from': 0
                }
            ]
        }
    
    async def execute_workflow(self, workflow_name: str, initial_params: dict, progress_callback=None):
        """
        Execute a named workflow with progress tracking
        
        Args:
            workflow_name: Name of workflow to execute
            initial_params: Initial parameters
            progress_callback: Function to call with progress updates
        """
        if workflow_name not in self.workflows:
            return {
                'success': False,
                'error': f'Unknown workflow: {workflow_name}'
            }
        
        workflow = self.workflows[workflow_name]
        logger.info(f"🔄 Starting workflow: {workflow['name']}")
        
        steps = []
        results = []
        
        try:
            for idx, step_config in enumerate(workflow['steps']):
                # Create step
                step_args = self._build_step_args(
                    step_config,
                    initial_params,
                    results
                )
                
                step = WorkflowStep(
                    tool_name=step_config['tool'],
                    args=step_args,
                    description=step_config['description']
                )
                steps.append(step)
                
                # Report progress
                if progress_callback:
                    await progress_callback({
                        'step': idx + 1,
                        'total': len(workflow['steps']),
                        'description': step.description,
                        'status': 'running'
                    })
                
                # Execute step
                logger.info(f"  Step {idx + 1}/{len(workflow['steps'])}: {step.description}")
                step.status = "running"
                
                result = await self.mcp.execute_tool(
                    step.tool_name,
                    step.args
                )
                
                if not result.get('success'):
                    step.status = "failed"
                    step.error = result.get('error')
                    logger.error(f"  ❌ Step failed: {step.error}")
                    
                    return {
                        'success': False,
                        'error': f'Workflow failed at step {idx + 1}: {step.error}',
                        'completed_steps': idx,
                        'total_steps': len(workflow['steps']),
                        'steps': [self._step_to_dict(s) for s in steps]
                    }
                
                step.status = "completed"
                step.result = result.get('data', {})
                results.append(result)
                
                logger.info(f"  ✅ Step completed")
                
                # Report progress
                if progress_callback:
                    await progress_callback({
                        'step': idx + 1,
                        'total': len(workflow['steps']),
                        'description': step.description,
                        'status': 'completed'
                    })
            
            # All steps completed
            logger.info(f"✅ Workflow completed: {workflow['name']}")
            
            return {
                'success': True,
                'completed': True,
                'message': f"Workflow '{workflow['name']}' completed successfully",
                'data': {
                    'workflow': workflow_name,
                    'steps_completed': len(steps),
                    'final_result': results[-1].get('data', {}) if results else {},
                    'steps': [self._step_to_dict(s) for s in steps]
                }
            }
            
        except Exception as e:
            logger.error(f"Workflow error: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e),
                'steps': [self._step_to_dict(s) for s in steps]
            }
    
    def _build_step_args(self, step_config: dict, initial_params: dict, previous_results: list) -> dict:
        """Build arguments for a workflow step"""
        args = {}
        
        # Start with required params from initial params
        for param in step_config.get('required_params', []):
            if param in initial_params:
                args[param] = initial_params[param]
        
        # Add any fixed params
        if 'params' in step_config:
            for key, value in step_config['params'].items():
                if callable(value):
                    args[key] = value(initial_params)
                else:
                    args[key] = value
        
        # Map params from previous results
        if 'use_result_from' in step_config:
            result_idx = step_config['use_result_from']
            if result_idx < len(previous_results):
                prev_result = previous_results[result_idx].get('data', {})
                
                if 'param_mapping' in step_config:
                    for dest_param, source_param in step_config['param_mapping'].items():
                        if callable(source_param):
                            args[dest_param] = source_param(prev_result)
                        elif source_param in prev_result:
                            args[dest_param] = prev_result[source_param]
        
        return args
    
    def _step_to_dict(self, step: WorkflowStep) -> dict:
        """Convert step to dictionary"""
        return {
            'tool': step.tool_name,
            'description': step.description,
            'status': step.status,
            'error': step.error
        }
    
    def get_available_workflows(self) -> List[Dict[str, Any]]:
        """Get list of available workflows"""
        return [
            {
                'name': name,
                'description': config['description'],
                'steps': len(config['steps'])
            }
            for name, config in self.workflows.items()
        ]