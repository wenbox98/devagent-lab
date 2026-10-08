"""Local task-owned clarification. No persistence, write dispatcher or NLP parser."""
from copy import deepcopy
from dataclasses import dataclass, field
from uuid import uuid4

from .clarification import Clarification, TaskGoal, _text, decide, merge_answer
from ..agent.citations import CitationError
from ..agent.loop import AgentState, run_agent
from ..agent.workflow import ReadPlan, WorkflowResult, run_readonly_workflow
from ..tools.registry import ToolRegistry


@dataclass
class TaskState:
    task_id: str
    original_task: str
    goal: TaskGoal
    status: str = 'new'
    reason: str | None = None
    pending: Clarification | None = None
    question_id: str | None = None
    answers: list[str] = field(default_factory=list)
    investigation: AgentState | WorkflowResult | None = None
    plan: ReadPlan | None = None


class TaskSession:
    """Host owns this object/registry. Public snapshots are copies, not authority."""

    def __init__(self, original_task: str, goal: TaskGoal, registry: ToolRegistry):
        _text(original_task, 'original_task')
        if not isinstance(goal, TaskGoal):
            raise ValueError('goal must be user-confirmed structured conditions')
        self._state = TaskState(uuid4().hex, original_task, goal)
        self._registry = registry
        self._next_action = None

    @property
    def state(self):
        return deepcopy(self._state)

    def assess(self, next_action: str) -> TaskState:
        state = self._state
        if state.status in {'failed', 'rejected'}:
            return self.state
        if state.status == 'waiting_input':
            if next_action != self._next_action:
                raise ValueError('resolve the pending question before changing the action')
            return self.state
        decision = decide(state.goal, next_action)
        self._next_action = next_action
        state.status, state.reason = decision.status, decision.reason
        state.pending = decision.clarification
        state.question_id = uuid4().hex if state.pending else None
        return self.state

    def investigate(self, plan: ReadPlan, *, strategy='workflow', client=None) -> TaskState:
        state = self._state
        # Waiting is a returnable state, not a loop or a reason to repeat tools.
        if state.status in {'waiting_input', 'failed', 'rejected'}:
            return self.state
        if state.investigation is not None:
            if plan != state.plan:
                raise ValueError('completed read plan cannot be silently replaced')
            return self.state
        if not isinstance(plan, ReadPlan) or strategy not in {'workflow', 'agent'} or (strategy == 'agent' and client is None):
            raise ValueError('a read plan and supported strategy/client are required')
        self.assess('read_file')
        state.plan = plan
        if strategy == 'agent':
            result = run_agent(plan.task, client, self._registry, max_rounds=5, max_tool_calls=6)
        else:
            result = run_readonly_workflow(plan, self._registry)
        state.investigation = result
        if result.status == 'answered':
            state.status = 'evidence_collected' if result.evidence else 'failed'
            state.reason = None if result.evidence else 'no_read_evidence'
        else:
            state.status = 'failed'
            state.reason = result.termination_reason if isinstance(result, AgentState) else result.error_code
        return self.state

    def resume(self, task_id: str, question_id: str, answer: str, updates: dict) -> TaskState:
        state = self._state
        if state.status != 'waiting_input' or task_id != state.task_id or question_id != state.question_id:
            raise ValueError('answer must address this task and its current pending question')
        _text(answer, 'answer')
        updated = merge_answer(state.goal, state.pending, updates)
        # Preserve evidence, but do not bless stale evidence after a human delay.
        try:
            if state.investigation:
                for citation in state.investigation.evidence:
                    self._registry.validate_citation(citation)
        except CitationError as exc:
            state.status, state.reason = 'failed', exc.code
            return self.state
        state.goal = updated
        state.answers.append(answer)
        state.pending, state.question_id = None, None
        state.status = 'running'
        return self.assess(self._next_action)
