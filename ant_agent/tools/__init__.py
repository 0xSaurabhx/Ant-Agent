class BaseTool:
    name: str = ""
    description: str = ""

    def __init__(self, agent_context=None):
        self.context = agent_context

    def execute(self, parameter: str) -> str:
        raise NotImplementedError("Tool must implement execute.")

_registry = {}

def register_tool(tool_cls):
    instance = tool_cls()
    _registry[instance.name] = tool_cls
    return tool_cls

def get_tool(name: str, agent_context=None) -> BaseTool:
    tool_cls = _registry.get(name)
    if not tool_cls:
        raise ValueError(f"Tool {name} is not registered.")
    return tool_cls(agent_context)

def get_all_tools():
    return list(_registry.keys())

def get_tool_descriptions():
    return {name: cls().description for name, cls in _registry.items()}
