"""Deterministic conditions, not natural-language authorization or model scoring."""
from dataclasses import dataclass, replace
from datetime import datetime

READ_ACTIONS = frozenset({'list_files', 'read_file', 'search_text'})
CHANGE_ACTIONS = frozenset({'modify_code', 'optimize_code'})


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 5000:
        raise ValueError(f'{name} must be nonempty text of at most 5000 characters')


def _texts(value, name):
    if not isinstance(value, tuple) or len(value) > 32:
        raise ValueError(f'{name} must be a tuple of at most 32 strings')
    for item in value:
        _text(item, name)


@dataclass(frozen=True)
class Constraints:
    # User requirements; these do NOT grant workspace access or write authority.
    allowed_scope: tuple[str, ...] = ()
    preserve_signature: bool | None = None
    preserve_return_structure: bool | None = None
    preferences: tuple[str, ...] = ()

    def __post_init__(self):
        _texts(self.allowed_scope, 'allowed_scope')
        _texts(self.preferences, 'preferences')
        for value in (self.preserve_signature, self.preserve_return_structure):
            if value is not None and type(value) is not bool:
                raise ValueError('preservation requirements must be bool or None')


def _confirmation(confirmed_by, confirmed_at):
    _text(confirmed_by, 'confirmed_by')
    if not isinstance(confirmed_at, datetime) or confirmed_at.utcoffset() is None:
        raise ValueError('confirmed_at must be a timezone-aware datetime')


@dataclass(frozen=True)
class AssumptionRecord:
    """A caller-supplied confirmation, not independent verification of a fact."""
    assumption_id: str
    content: str
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None

    def __post_init__(self):
        _text(self.assumption_id, 'assumption_id')
        _text(self.content, 'content')
        if self.confirmed_by is not None or self.confirmed_at is not None:
            _confirmation(self.confirmed_by, self.confirmed_at)


def _assumption_records(records):
    if not isinstance(records, tuple) or any(not isinstance(r, AssumptionRecord) for r in records):
        raise ValueError('assumption_records must be a tuple of AssumptionRecord')
    if len({r.assumption_id for r in records}) != len(records):
        raise ValueError('assumption_id must be unique within the records')


def confirm_assumption(records: tuple[AssumptionRecord, ...], assumption_id: str,
                       confirmed_by: str, confirmed_at: datetime) -> tuple[AssumptionRecord, ...]:
    """Replace one record immutably. Identity/time come from the trusted caller.

    This helper is not connected to merge_answer or TaskSession.resume.
    """
    _assumption_records(records)
    _text(assumption_id, 'assumption_id')
    _confirmation(confirmed_by, confirmed_at)
    for index, record in enumerate(records):
        if record.assumption_id == assumption_id:
            updated = replace(record, confirmed_by=confirmed_by, confirmed_at=confirmed_at)
            return records[:index] + (updated,) + records[index + 1:]
    raise ValueError('unknown assumption_id')


@dataclass(frozen=True)
class TaskGoal:
    goal: str
    constraints: Constraints = Constraints()
    acceptance: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    optimization_dimension: str | None = None
    # Compatibility extension: legacy strings remain; no unified assumption store.
    assumption_records: tuple[AssumptionRecord, ...] = ()

    def __post_init__(self):
        _text(self.goal, 'goal')
        if not isinstance(self.constraints, Constraints):
            raise ValueError('constraints must be Constraints')
        _texts(self.acceptance, 'acceptance')
        _texts(self.assumptions, 'assumptions')
        if self.optimization_dimension is not None:
            _text(self.optimization_dimension, 'optimization_dimension')
        _assumption_records(self.assumption_records)


@dataclass(frozen=True)
class Clarification:
    question: str
    missing_fields: tuple[str, ...]


@dataclass(frozen=True)
class Decision:
    status: str
    reason: str
    clarification: Clarification | None = None


def decide(goal: TaskGoal, next_action: str) -> Decision:
    """Host classifies actions. A read still needs registry authorization/budgets."""
    if not isinstance(goal, TaskGoal) or not isinstance(next_action, str):
        raise ValueError('expected a structured goal and action name')
    if next_action in READ_ACTIONS:
        return Decision('can_gather_evidence', 'Read proposal; registry must enforce workspace and budgets.')
    if next_action not in CHANGE_ACTIONS:
        return Decision('rejected', 'Unknown action; model claims cannot classify it as safe.')
    missing = []
    if next_action == 'optimize_code' and not goal.optimization_dimension:
        missing.append(('optimization_dimension', '优先优化哪个维度：首屏耗时、吞吐量，还是正确性？'))
    if not goal.constraints.allowed_scope:
        missing.append(('allowed_scope', '这次修改的目标文件范围是什么？'))
    if goal.constraints.preserve_signature is None:
        missing.append(('preserve_signature', '是否必须保持函数签名不变？'))
    if not goal.acceptance:
        missing.append(('acceptance', '用什么可检查的结果判断这次修改成功？'))
    if missing:
        field, question = missing[0]
        return Decision('waiting_input', f'{field} changes the proposed modification; ask before proceeding.',
                        Clarification(question, (field,)))
    return Decision('ready_for_policy_check', 'Conditions collected; NO write permission or execution is granted.')


def merge_answer(goal: TaskGoal, clarification: Clarification, updates: dict) -> TaskGoal:
    """Apply explicit user/form fields atomically, never inferred model permissions.

    Existing hard requirements/acceptance cannot be replaced by a reply. Scope can
    only narrow. Free-text semantic conflict resolution is deliberately unsupported.
    """
    allowed = {'optimization_dimension', 'allowed_scope', 'preserve_signature',
               'preserve_return_structure', 'acceptance'}
    if not isinstance(updates, dict) or set(updates) - allowed or not set(clarification.missing_fields) <= set(updates):
        raise ValueError('answer must fill the pending field using known condition fields')
    constraints = goal.constraints
    changes = {}
    for name, value in updates.items():
        old = getattr(goal, name) if name in {'acceptance', 'optimization_dimension'} else getattr(constraints, name)
        if name in {'allowed_scope', 'acceptance'}:
            _texts(value, name)
            if not value:
                raise ValueError(f'{name} must not be empty')
            if old and ((name == 'allowed_scope' and not set(value) <= set(old))
                        or (name == 'acceptance' and not set(old) <= set(value))):
                raise ValueError('answer conflicts with existing scope or acceptance')
        elif name == 'optimization_dimension':
            _text(value, name)
            if old is not None and old != value:
                raise ValueError('answer conflicts with the existing optimization dimension')
        elif type(value) is not bool or (old is not None and old != value):
            raise ValueError('answer conflicts with a hard preservation requirement')
        changes[name] = value
    constraint_changes = {k: v for k, v in changes.items() if k not in {'acceptance', 'optimization_dimension'}}
    return replace(goal, constraints=replace(constraints, **constraint_changes),
                   **{k: v for k, v in changes.items() if k in {'acceptance', 'optimization_dimension'}})
