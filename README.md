# GodComet - Monorepo

This repository contains both the **GodComet Electron application** and the **MCP Automation** backend in a unified monorepo structure.

## Repository Structure

```
GodComet/
├── godcomet/              # Electron application (frontend + backend)
│   ├── backend/          # FastAPI backend
│   │   └── mcp_tools/    # Symlink to mcp-automation/src/tools
│   ├── src/              # TypeScript source files
│   ├── extensions/       # Chrome, VSCode, and Windows extensions
│   └── ...
├── mcp-automation/       # MCP server and automation tools
│   ├── src/
│   │   ├── mcp_server.py
│   │   ├── ai_client.py
│   │   └── tools/        # All MCP tools
│   └── ...
└── setup_symlink.*       # Scripts to recreate symlink after cloning
```

## Connection Between Projects

The `godcomet/backend/brain.py` imports from `mcp-automation/src/mcp_server.py` using a relative path. Additionally, there's a symbolic link:

- **Symlink**: `godcomet/backend/mcp_tools` → `../../mcp-automation/src/tools`

This symlink allows the godcomet backend to directly access MCP tools.

## Setup Instructions

### After Cloning

1. **Recreate the symlink** (required on Windows/Linux):
   
   **Windows (PowerShell):**
   ```powershell
   .\setup_symlink.ps1
   ```
   
   **Linux/Mac:**
   ```bash
   chmod +x setup_symlink.sh
   ./setup_symlink.sh
   ```

   **Manual (if scripts don't work):**
   ```bash
   # Windows (PowerShell as Administrator or with Developer Mode)
   New-Item -ItemType SymbolicLink -Path godcomet\backend\mcp_tools -Target ..\..\mcp-automation\src\tools
   
   # Linux/Mac
   ln -s ../../mcp-automation/src/tools godcomet/backend/mcp_tools
   ```

2. **Install dependencies:**
   
   **GodComet (Node.js):**
   ```bash
   cd godcomet
   npm install
   ```
   
   **MCP Automation (Python):**
   ```bash
   cd mcp-automation
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Set up environment variables:**
   - Copy `.env.example` files if available
   - Configure API keys and tokens as needed

## Development

### Running GodComet
```bash
cd godcomet
npm start
```

### Running MCP Automation
```bash
cd mcp-automation
python app_cli.py
# or
python app_gui.py
```

## Important Notes

- The symlink `godcomet/backend/mcp_tools` is tracked by Git and will be preserved on clone (on systems that support symlinks)
- On Windows, you may need Administrator privileges or Developer Mode enabled to create symlinks
- If the symlink doesn't work after cloning, use the setup scripts provided

## Git Configuration

This repository uses:
- `core.symlinks = true` to properly handle symbolic links
- Monorepo structure with both projects in the same repository

## License

[Add your license here]

