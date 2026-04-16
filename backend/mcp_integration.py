class MCPToolManager:
    def __init__(self) -> None:
        self.available_tools = [
            {
                "name": "shell.execute",
                "server": "builtin",
                "description": "Run an allowlisted shell command in the repository workspace",
                "parameters": {"command": "string"},
                "mock": False,
            },
            {
                "name": "docker.run",
                "server": "builtin",
                "description": "Run a containerized command for verification",
                "parameters": {"image": "string", "command": "string"},
                "mock": False,
            },
            {
                "name": "github.create_issue_comment",
                "server": "builtin",
                "description": "Create a GitHub comment with a PAT",
                "parameters": {"issue_number": "int", "body": "string"},
                "mock": False,
            },
        ]

    async def get_available_tools(self):
        return self.available_tools

    async def invoke_tool(self, tool_name: str, parameters: dict):
        return {"success": True, "tool": tool_name, "parameters": parameters}


mcp_manager = MCPToolManager()


async def get_available_tools():
    return await mcp_manager.get_available_tools()