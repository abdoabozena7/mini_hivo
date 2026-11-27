"""Provider-neutral role registry. New model-backed roles must be declared here."""
AGENT_ROLES = (
    'coordinator', 'predictor', 'builder', 'challenger', 'falsifier', 'quality',
    'repairer', 'visual', 'specifier', 'mission_compiler', 'clarifier',
    'requirement_extractor', 'recon_agent', 'task_brain_compiler',
    'impact_planner', 'impact_challenger', 'impact_plan_reviser',
)
IMPLEMENTATION_ROLES = frozenset({'builder', 'falsifier', 'repairer'})
