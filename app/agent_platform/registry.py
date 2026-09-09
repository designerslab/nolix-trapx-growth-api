from app.agent_platform.models import AgentCapability, AgentDefinition

AGENTS = {
    "growth": AgentDefinition(
        key="growth",
        name="Growth Agent",
        description="SEO, analytics, content, approvals, and controlled publishing.",
        brands=["nolix","trapx"],
        capabilities=[
            AgentCapability(name="seo_analysis",description="Analyze GSC and GA4 growth opportunities.",mode="read"),
            AgentCapability(name="content_generation",description="Generate evidence-grounded content drafts.",mode="write",requires_human_approval=True),
            AgentCapability(name="content_review",description="Store explicit human review decisions.",mode="review",requires_human_approval=True),
            AgentCapability(name="controlled_publish",description="Create unpublished Shopify blog articles after gate checks.",mode="publish",requires_human_approval=True),
        ],
    ),
"seo": AgentDefinition(
    key="seo",
    name="SEO Agent",
    description="Ranks SEO actions and prepares approved execution workflows.",
    brands=["nolix","trapx"],
    capabilities=[
        AgentCapability(
            name="action_queue",
            description="Rank SEO actions from GSC, GA4, technical, GEO, and Product Truth evidence.",
            mode="read",
        ),
        AgentCapability(
            name="prepare_action",
            description="Generate the selected SEO change and submit it for human review.",
            mode="write",
            requires_human_approval=True,
        ),
    ],
),

}

def get_agent(key: str):
    return AGENTS.get(key)

def list_agents():
    return list(AGENTS.values())

def register_agent(definition: AgentDefinition):
    AGENTS[definition.key] = definition
