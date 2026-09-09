from app.agent_platform.models import AgentCapability, AgentDefinition
from app.agent_platform.registry import register_agent

register_agent(
    AgentDefinition(
        key="YOUR_AGENT_KEY",
        name="Your Agent Name",
        description="What this agent owns.",
        brands=["nolix"],
        capabilities=[
            AgentCapability(
                name="example_read",
                description="Read-only capability.",
                mode="read",
            ),
        ],
    )
)
