"""Universal Jira Automation Tool - FIXED VERSION"""
from jira import JIRA
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
import yaml

logger = logging.getLogger(__name__)

class UniversalJiraAutomation:
    """Universal Jira automation that works with JSON/YAML config"""
    
    def __init__(self, jira_url: str, email: str, api_token: str):
        """Initialize Jira client"""
        try:
            self.jira = JIRA(
                server=jira_url,
                basic_auth=(email, api_token)
            )
            self.created_issues = {}  # Track created issues for dependencies
            logger.info("✅ Jira client initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Jira: {e}")
            raise
    
    async def create_from_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create Jira structure from configuration
        
        Config format:
        {
            "projects": [...],
            "epics": [...],
            "stories": [...],
            "subtasks": [...],
            "sprints": [...]
        }
        """
        try:
            results = {
                "success": True,
                "projects": [],
                "epics": [],
                "stories": [],
                "subtasks": [],
                "errors": []
            }
            
            # CRITICAL FIX: If no projects defined, extract from stories
            if not config.get("projects") and config.get("stories"):
                logger.info("No projects defined, extracting from stories...")
                project_keys = set()
                for story in config["stories"]:
                    if "project" in story:
                        project_keys.add(story["project"])
                    elif "id" in story and "-" in story["id"]:
                        project_keys.add(story["id"].split("-")[0])
                
                for key in project_keys:
                    config.setdefault("projects", []).append({
                        "key": key,
                        "name": f"{key} Project",
                        "template": "scrum"
                    })
                logger.info(f"Auto-detected {len(project_keys)} projects: {project_keys}")
            
            # CRITICAL FIX: Update epic and story project references
            if config.get("projects"):
                project_keys = [p["key"] for p in config["projects"]]
                
                # Fix epics with PROJ -> actual project
                for epic in config.get("epics", []):
                    if epic.get("project") == "PROJ" and project_keys:
                        epic["project"] = project_keys[0]
                        logger.info(f"Fixed epic project: PROJ -> {project_keys[0]}")
                
                # Fix stories with PROJ -> actual project
                for story in config.get("stories", []):
                    if story.get("project") == "PROJ" and project_keys:
                        story["project"] = project_keys[0]
            
            # Step 1: Create Projects
            if "projects" in config:
                for project in config["projects"]:
                    try:
                        result = await self.create_project(project)
                        results["projects"].append(result)
                    except Exception as e:
                        results["errors"].append(f"Project {project.get('key')}: {str(e)}")
            
            # Step 2: Create Epics
            if "epics" in config:
                for epic in config["epics"]:
                    try:
                        result = await self.create_epic(epic)
                        results["epics"].append(result)
                    except Exception as e:
                        results["errors"].append(f"Epic {epic.get('name')}: {str(e)}")
            
            # Step 3: Create Stories/Tasks
            if "stories" in config:
                for story in config["stories"]:
                    try:
                        result = await self.create_story(story)
                        results["stories"].append(result)
                    except Exception as e:
                        results["errors"].append(f"Story {story.get('summary')}: {str(e)}")
            
            # Step 4: Create Subtasks
            if "subtasks" in config:
                for subtask in config["subtasks"]:
                    try:
                        result = await self.create_subtask(subtask)
                        results["subtasks"].append(result)
                    except Exception as e:
                        results["errors"].append(f"Subtask {subtask.get('summary')}: {str(e)}")
            
            # Summary
            total_created = (
                len(results["projects"]) + 
                len(results["epics"]) + 
                len(results["stories"]) + 
                len(results["subtasks"])
            )
            
            return {
                "success": len(results["errors"]) == 0,
                "message": f"Created {total_created} items ({len(results['errors'])} errors)",
                "data": results
            }
            
        except Exception as e:
            logger.error(f"Failed to create from config: {e}")
            return {"success": False, "error": str(e)}
    
    async def create_project(self, project_config: Dict) -> str:
        """
        Create a project from config
        
        Config:
        {
            "key": "PROJ",
            "name": "Project Name",
            "description": "Description",
            "template": "scrum" | "kanban" | "basic"
        }
        """
        try:
            # First check if project exists
            try:
                existing = self.jira.project(project_config["key"])
                logger.info(f"✅ Project already exists: {existing.key}")
                return existing.key
            except:
                # Project doesn't exist, create it
                pass
            
            template_map = {
                "scrum": "com.pyxis.greenhopper.jira:gh-scrum-template",
                "kanban": "com.pyxis.greenhopper.jira:gh-kanban-template",
                "basic": "com.atlassian.jira-core-project-templates:jira-core-simplified-project-management"
            }
            
            project = self.jira.create_project(
                key=project_config["key"],
                name=project_config["name"],
                assignee=self.jira.current_user(),
                type="software",
                template_name=template_map.get(project_config.get("template", "scrum"))
            )
            
            logger.info(f"✅ Created project: {project.key}")
            return project.key
            
        except Exception as e:
            # Project might exist but API failed to confirm
            logger.warning(f"Project {project_config['key']} error: {e}, assuming it exists")
            return project_config["key"]
    
    async def create_epic(self, epic_config: Dict) -> str:
        """
        Create an epic from config
        
        Config:
        {
            "id": "epic_1",
            "project": "PROJ",
            "name": "Epic Name",
            "description": "Epic description",
            "start_date": "2025-11-04",
            "end_date": "2025-11-22"
        }
        """
        try:
            # Verify project exists first
            try:
                self.jira.project(epic_config["project"])
            except Exception as e:
                logger.error(f"Project {epic_config['project']} not found!")
                raise Exception(f"Project {epic_config['project']} does not exist. Create project first.")
            
            epic = self.jira.create_issue(
                project=epic_config["project"],
                summary=epic_config["name"],
                description=epic_config.get("description", ""),
                issuetype={'name': 'Epic'},
            )
            
            # Try to set epic name (field varies by Jira instance)
            try:
                epic.update(fields={'customfield_10011': epic_config["name"]})
            except:
                pass
            
            # Set due date
            if "end_date" in epic_config:
                try:
                    epic.update(fields={'duedate': epic_config["end_date"]})
                except:
                    pass
            
            # Store for later reference
            self.created_issues[epic_config.get("id", epic.key)] = epic.key
            
            logger.info(f"✅ Created epic: {epic.key} - {epic_config['name']}")
            return epic.key
            
        except Exception as e:
            logger.error(f"Failed to create epic: {e}")
            raise
    
    async def create_story(self, story_config: Dict) -> str:
        """
        Create a story/task from config
        
        Config:
        {
            "id": "story_1",
            "project": "PROJ",
            "epic_id": "epic_1",
            "summary": "Story summary",
            "description": "Story description",
            "type": "Story" | "Task" | "Bug",
            "story_points": 5,
            "assignee": "username",
            "labels": ["DEV", "BACKEND"],
            "priority": "High" | "Medium" | "Low",
            "start_date": "2025-11-04",
            "end_date": "2025-11-14",
            "depends_on": ["story_2", "story_3"]
        }
        """
        try:
            # Build issue dict
            issue_dict = {
                'project': story_config["project"],
                'summary': story_config["summary"],
                'description': story_config.get("description", ""),
                'issuetype': {'name': story_config.get("type", "Story")},
            }
            
            # Add labels
            if "labels" in story_config:
                issue_dict['labels'] = story_config["labels"]
            
            # Add story points (field varies)
            if "story_points" in story_config:
                try:
                    issue_dict['customfield_10016'] = story_config["story_points"]
                except:
                    pass
            
            # Add priority
            if "priority" in story_config:
                issue_dict['priority'] = {'name': story_config["priority"]}
            
            # Create issue
            issue = self.jira.create_issue(fields=issue_dict)
            
            # Link to epic
            if "epic_id" in story_config:
                epic_key = self.created_issues.get(story_config["epic_id"])
                if epic_key:
                    try:
                        issue.update(fields={'customfield_10014': epic_key})
                    except:
                        pass
            
            # Set due date
            if "end_date" in story_config:
                try:
                    issue.update(fields={'duedate': story_config["end_date"]})
                except:
                    pass
            
            # Create dependencies
            if "depends_on" in story_config:
                for dep_id in story_config["depends_on"]:
                    dep_key = self.created_issues.get(dep_id)
                    if dep_key:
                        try:
                            self.jira.create_issue_link(
                                type="Blocks",
                                inwardIssue=dep_key,
                                outwardIssue=issue.key
                            )
                        except:
                            pass
            
            # Store for later reference
            self.created_issues[story_config.get("id", issue.key)] = issue.key
            
            logger.info(f"✅ Created {story_config.get('type', 'Story')}: {issue.key}")
            return issue.key
            
        except Exception as e:
            logger.error(f"Failed to create story: {e}")
            raise
    
    async def create_subtask(self, subtask_config: Dict) -> str:
        """
        Create a subtask from config
        
        Config:
        {
            "parent_id": "story_1",
            "summary": "Subtask summary",
            "description": "Description",
            "assignee": "username"
        }
        """
        try:
            parent_key = self.created_issues.get(subtask_config["parent_id"])
            if not parent_key:
                raise ValueError(f"Parent {subtask_config['parent_id']} not found")
            
            subtask = self.jira.create_issue(
                project=parent_key.split('-')[0],
                summary=subtask_config["summary"],
                description=subtask_config.get("description", ""),
                issuetype={'name': 'Sub-task'},
                parent={'key': parent_key}
            )
            
            logger.info(f"✅ Created subtask: {subtask.key}")
            return subtask.key
            
        except Exception as e:
            logger.error(f"Failed to create subtask: {e}")
            raise
    
    async def create_from_json_file(self, file_path: str) -> Dict[str, Any]:
        """Load config from JSON file and create structure"""
        try:
            with open(file_path, 'r') as f:
                config = json.load(f)
            return await self.create_from_config(config)
        except Exception as e:
            return {"success": False, "error": f"Failed to load JSON: {str(e)}"}
    
    async def create_from_yaml_file(self, file_path: str) -> Dict[str, Any]:
        """Load config from YAML file and create structure"""
        try:
            with open(file_path, 'r') as f:
                config = yaml.safe_load(f)
            return await self.create_from_config(config)
        except Exception as e:
            return {"success": False, "error": f"Failed to load YAML: {str(e)}"}
    
    async def create_from_natural_language(self, description: str, ai_client) -> Dict[str, Any]:
        """
        Use AI to convert natural language to Jira structure
        
        Example: "Create a project called WebApp with 2 epics: Frontend and Backend. 
                 Frontend has 3 stories for login, dashboard, and settings."
        """
        try:
            # Ask AI to convert to JSON config
            prompt = f"""Convert this Jira project description into a JSON configuration:

{description}

Return ONLY valid JSON in this format:
{{
  "projects": [{{"key": "PROJ", "name": "Project Name", "template": "scrum"}}],
  "epics": [{{"id": "epic_1", "project": "PROJ", "name": "Epic Name"}}],
  "stories": [{{
    "id": "story_1",
    "project": "PROJ",
    "epic_id": "epic_1",
    "summary": "Story summary",
    "type": "Story",
    "story_points": 5,
    "labels": ["DEV"]
  }}]
}}

Generate appropriate IDs, dates, story points, and labels based on the description.
Today's date is {datetime.now().strftime('%Y-%m-%d')}.
Return ONLY the JSON, no explanation."""

            # This would use your AI client
            # For now, return error asking user to provide structured input
            return {
                "success": False,
                "error": "AI parsing not implemented yet. Please use JSON/YAML config file."
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}


# Example usage function
async def example_usage():
    """Example of how to use the universal tool"""
    
    # Initialize
    jira = UniversalJiraAutomation(
        jira_url="https://your-company.atlassian.net",
        email="your-email@example.com",
        api_token="your-api-token"
    )
    
    # Example config
    config = {
        "projects": [
            {
                "key": "DEMO",
                "name": "Demo Project",
                "description": "Demo project for testing",
                "template": "scrum"
            }
        ],
        "epics": [
            {
                "id": "epic_1",
                "project": "DEMO",
                "name": "User Authentication",
                "description": "All auth-related features",
                "end_date": "2025-12-31"
            }
        ],
        "stories": [
            {
                "id": "story_1",
                "project": "DEMO",
                "epic_id": "epic_1",
                "summary": "Implement login page",
                "description": "Create UI and backend for login",
                "type": "Story",
                "story_points": 5,
                "labels": ["FRONTEND", "DEV"],
                "priority": "High",
                "end_date": "2025-11-30"
            },
            {
                "id": "story_2",
                "project": "DEMO",
                "epic_id": "epic_1",
                "summary": "Add password reset",
                "type": "Story",
                "story_points": 3,
                "labels": ["BACKEND", "DEV"],
                "depends_on": ["story_1"]
            }
        ],
        "subtasks": [
            {
                "parent_id": "story_1",
                "summary": "Design login mockups",
                "description": "Create Figma designs"
            }
        ]
    }
    
    # Create from config
    result = await jira.create_from_config(config)
    
    if result["success"]:
        print(f"✅ {result['message']}")
    else:
        print(f"❌ Error: {result['error']}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(example_usage())