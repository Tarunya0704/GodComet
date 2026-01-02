"""Code Analysis Tool - Analyzes and improves code"""
import logging
from pathlib import Path
import re

logger = logging.getLogger(__name__)

class CodeAnalysisTool:
    """Tool for analyzing and improving code"""
    
    def __init__(self, ai_client=None):
        self.ai_client = ai_client
        logger.info("Code Analysis Tool initialized")
    
    async def analyze_code(self, file_path: str) -> dict:
        """Analyze code for bugs, improvements, and suggestions"""
        try:
            # Read file
            path = Path(file_path)
            if not path.exists():
                return {"success": False, "error": f"File not found: {file_path}", "fatal": True}
            
            if not path.is_file():
                return {"success": False, "error": f"Not a file: {file_path}", "fatal": True}
            
            # Try to read with multiple encodings
            content = None
            used_encoding = None
            for encoding in ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252', 'iso-8859-1']:
                try:
                    with open(path, 'r', encoding=encoding, errors='ignore') as f:
                        content = f.read()
                        used_encoding = encoding
                    break
                except:
                    continue
            
            if not content:
                return {"success": False, "error": "Could not read file with any encoding", "fatal": True}
            
            # Detect language
            ext = path.suffix.lower()
            language_map = {
                '.py': 'Python', '.js': 'JavaScript', '.ts': 'TypeScript',
                '.jsx': 'React', '.tsx': 'React', '.java': 'Java',
                '.cpp': 'C++', '.c': 'C', '.cs': 'C#', '.go': 'Go',
                '.rs': 'Rust', '.php': 'PHP', '.rb': 'Ruby'
            }
            language = language_map.get(ext, 'Unknown')
            
            # Use AI to analyze if available
            if self.ai_client:
                analysis_prompt = f"""Analyze this {language} code and provide:
1. Potential bugs or errors
2. Code quality issues
3. Performance improvements
4. Security concerns
5. Best practice violations

Code:
```{language.lower()}
{content[:3000]}
```

Provide a concise analysis with specific line references where possible."""

                ai_result = await self.ai_client.chat(analysis_prompt)
                
                if ai_result.get('success'):
                    return {
                        "success": True,
                        "completed": True,
                        "message": "Code analysis completed",
                        "data": {
                            "file": str(path),
                            "language": language,
                            "lines": len(content.splitlines()),
                            "analysis": ai_result['reply']
                        }
                    }
            
            # Fallback: Basic static analysis
            lines = content.splitlines()
            issues = []
            
            # Check for common issues
            if language == 'Python':
                for i, line in enumerate(lines, 1):
                    if 'print(' in line and 'debug' not in line.lower():
                        issues.append(f"Line {i}: Debug print statement found")
                    if 'import *' in line:
                        issues.append(f"Line {i}: Avoid wildcard imports")
                    if re.search(r'except\s*:', line):
                        issues.append(f"Line {i}: Bare except clause (catch specific exceptions)")
            
            elif language in ['JavaScript', 'TypeScript']:
                for i, line in enumerate(lines, 1):
                    if 'console.log' in line:
                        issues.append(f"Line {i}: Console log statement found")
                    if 'var ' in line:
                        issues.append(f"Line {i}: Use 'let' or 'const' instead of 'var'")
                    if '==' in line and '===' not in line:
                        issues.append(f"Line {i}: Use '===' instead of '=='")
            
            return {
                "success": True,
                "completed": True,
                "message": f"Basic analysis completed for {language} code",
                "data": {
                    "file": str(path),
                    "language": language,
                    "lines": len(lines),
                    "issues": issues if issues else ["No obvious issues found"],
                    "note": "For detailed AI analysis, ensure AI client is configured"
                }
            }
            
        except Exception as e:
            logger.error(f"Code analysis failed: {e}")
            return {"success": False, "error": str(e), "fatal": True}
    
    async def fix_bugs(self, file_path: str, context: str = None) -> dict:
        """Suggest bug fixes for code"""
        try:
            if not self.ai_client:
                return {"success": False, "error": "AI client not available for bug fixing", "fatal": True}
            
            # Read file
            path = Path(file_path)
            if not path.exists():
                return {"success": False, "error": f"File not found: {file_path}", "fatal": True}
            
            content = None
            for encoding in ['utf-8', 'utf-8-sig', 'latin-1']:
                try:
                    with open(path, 'r', encoding=encoding, errors='ignore') as f:
                        content = f.read()
                    break
                except:
                    continue
            
            if not content:
                return {"success": False, "error": "Could not read file", "fatal": True}
            
            ext = path.suffix.lower()
            language_map = {'.py': 'Python', '.js': 'JavaScript', '.ts': 'TypeScript'}
            language = language_map.get(ext, 'Unknown')
            
            prompt = f"""Fix bugs in this {language} code.

{f'Context: {context}' if context else ''}

Code:
```{language.lower()}
{content[:2000]}
```

Provide:
1. Identified bugs
2. Fixed code
3. Explanation of fixes"""

            ai_result = await self.ai_client.chat(prompt)
            
            if ai_result.get('success'):
                return {
                    "success": True,
                    "completed": True,
                    "message": "Bug fix suggestions generated",
                    "data": {
                        "file": str(path),
                        "suggestions": ai_result['reply']
                    }
                }
            
            return {"success": False, "error": "AI analysis failed", "fatal": True}
            
        except Exception as e:
            logger.error(f"Bug fix failed: {e}")
            return {"success": False, "error": str(e), "fatal": True}
    
    async def generate_tests(self, file_path: str) -> dict:
        """Generate unit tests for code"""
        try:
            if not self.ai_client:
                return {"success": False, "error": "AI client not available", "fatal": True}
            
            path = Path(file_path)
            if not path.exists():
                return {"success": False, "error": f"File not found: {file_path}", "fatal": True}
            
            content = None
            for encoding in ['utf-8', 'utf-8-sig', 'latin-1']:
                try:
                    with open(path, 'r', encoding=encoding, errors='ignore') as f:
                        content = f.read()
                    break
                except:
                    continue
            
            if not content:
                return {"success": False, "error": "Could not read file", "fatal": True}
            
            ext = path.suffix.lower()
            language = 'Python' if ext == '.py' else 'JavaScript'
            
            prompt = f"""Generate comprehensive unit tests for this {language} code.

Code:
```{language.lower()}
{content[:2000]}
```

Generate tests using {'pytest' if language == 'Python' else 'Jest'}.
Include edge cases and error handling tests."""

            ai_result = await self.ai_client.chat(prompt)
            
            if ai_result.get('success'):
                return {
                    "success": True,
                    "completed": True,
                    "message": f"Tests generated for {path.name}",
                    "data": {
                        "file": str(path),
                        "tests": ai_result['reply']
                    }
                }
            
            return {"success": False, "error": "Test generation failed", "fatal": True}
            
        except Exception as e:
            logger.error(f"Test generation failed: {e}")
            return {"success": False, "error": str(e), "fatal": True}
    
    async def refactor_code(self, file_path: str) -> dict:
        """Refactor code for better quality"""
        try:
            if not self.ai_client:
                return {"success": False, "error": "AI client not available", "fatal": True}
            
            path = Path(file_path)
            if not path.exists():
                return {"success": False, "error": f"File not found: {file_path}", "fatal": True}
            
            content = None
            for encoding in ['utf-8', 'utf-8-sig', 'latin-1']:
                try:
                    with open(path, 'r', encoding=encoding, errors='ignore') as f:
                        content = f.read()
                    break
                except:
                    continue
            
            if not content:
                return {"success": False, "error": "Could not read file", "fatal": True}
            
            ext = path.suffix.lower()
            language_map = {'.py': 'Python', '.js': 'JavaScript', '.ts': 'TypeScript'}
            language = language_map.get(ext, 'Unknown')
            
            prompt = f"""Refactor this {language} code to improve:
1. Code readability
2. Performance
3. Maintainability
4. Follow best practices

Code:
```{language.lower()}
{content[:2000]}
```

Provide the refactored code with explanations."""

            ai_result = await self.ai_client.chat(prompt)
            
            if ai_result.get('success'):
                return {
                    "success": True,
                    "completed": True,
                    "message": "Code refactoring suggestions generated",
                    "data": {
                        "file": str(path),
                        "refactored": ai_result['reply']
                    }
                }
            
            return {"success": False, "error": "Refactoring failed", "fatal": True}
            
        except Exception as e:
            logger.error(f"Refactoring failed: {e}")
            return {"success": False, "error": str(e), "fatal": True}
    
    async def document_code(self, file_path: str) -> dict:
        """Generate documentation for code"""
        try:
            if not self.ai_client:
                return {"success": False, "error": "AI client not available", "fatal": True}
            
            path = Path(file_path)
            if not path.exists():
                return {"success": False, "error": f"File not found: {file_path}", "fatal": True}
            
            content = None
            for encoding in ['utf-8', 'utf-8-sig', 'latin-1']:
                try:
                    with open(path, 'r', encoding=encoding, errors='ignore') as f:
                        content = f.read()
                    break
                except:
                    continue
            
            if not content:
                return {"success": False, "error": "Could not read file", "fatal": True}
            
            ext = path.suffix.lower()
            language_map = {'.py': 'Python', '.js': 'JavaScript', '.ts': 'TypeScript'}
            language = language_map.get(ext, 'Unknown')
            
            prompt = f"""Generate comprehensive documentation for this {language} code.

Include:
1. Module/file overview
2. Function/class documentation
3. Parameter descriptions
4. Return value descriptions
5. Usage examples

Code:
```{language.lower()}
{content[:2500]}
```

Use proper docstring format for {language}."""

            ai_result = await self.ai_client.chat(prompt)
            
            if ai_result.get('success'):
                return {
                    "success": True,
                    "completed": True,
                    "message": "Documentation generated",
                    "data": {
                        "file": str(path),
                        "documentation": ai_result['reply']
                    }
                }
            
            return {"success": False, "error": "Documentation generation failed", "fatal": True}
            
        except Exception as e:
            logger.error(f"Documentation generation failed: {e}")
            return {"success": False, "error": str(e), "fatal": True}