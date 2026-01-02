"""System operations tool"""
import os
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

class SystemTool:
    """File system operations"""
    
    async def read_file(self, path: str) -> Dict[str, Any]:
        """Read file"""
        try:
            with open(path, 'r') as f:
                content = f.read()
            return {"success": True, "content": content, "path": path}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def write_file(self, path: str, content: str) -> Dict[str, Any]:
        """Write file"""
        try:
            with open(path, 'w') as f:
                f.write(content)
            return {"success": True, "message": f"Written to {path}", "path": path}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def list_directory(self, path: str = ".") -> Dict[str, Any]:
        """List directory"""
        try:
            items = os.listdir(path)
            files = [i for i in items if os.path.isfile(os.path.join(path, i))]
            dirs = [i for i in items if os.path.isdir(os.path.join(path, i))]
            
            return {
                "success": True,
                "files": files,
                "directories": dirs,
                "path": path
            }
        except Exception as e:
            return {"success": False, "error": str(e)}