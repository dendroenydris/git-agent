from backend.app.services.tool_registry import list_tool_catalog


class MCPToolManager:
    def __init__(self) -> None:
        self.available_tools = list_tool_catalog()

    async def get_available_tools(self):
        return self.available_tools

    async def invoke_tool(self, tool_name: str, parameters: dict):
        return {"success": True, "tool": tool_name, "parameters": parameters}


mcp_manager = MCPToolManager()


async def get_available_tools():
    return await mcp_manager.get_available_tools()