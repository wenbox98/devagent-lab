"""L07 host-only, single-file edits in a trusted workspace.

All WorkspaceEditor instances in this process share a workspace lock. External
editors/processes do not participate: this is not a sandbox or cross-process CAS.
Atomic replacement is neither a multi-file transaction nor a durability promise.
Undo records live only in this editor's memory; operation IDs are not durable
idempotency keys. The model's read-only registry does not expose this API.
"""
from dataclasses import dataclass
from difflib import unified_diff
from hashlib import sha256
import os
from pathlib import Path
import stat
import tempfile
from threading import Lock

from . import files
from .protocol import ToolError

_LOCKS: dict[Path, Lock] = {}
_LOCKS_GUARD = Lock()


@dataclass(frozen=True)
class EditResult:
    operation_id: str
    path: str
    ok: bool
    before_hash: str | None = None
    after_hash: str | None = None
    diff: str = ''
    error: ToolError | None = None


@dataclass(frozen=True)
class _UndoRecord:
    path: str
    before: bytes
    before_hash: str
    after_hash: str


def _operation_id(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError('operation_id must be nonempty text of at most 200 characters')


def _validate_edit(expected_hash, old_text, new_text):
    if (not isinstance(expected_hash, str) or len(expected_hash) != 64
            or any(c not in '0123456789abcdef' for c in expected_hash)):
        raise ValueError('expected_hash must be a lowercase SHA-256 digest')
    if not isinstance(old_text, str) or not old_text:
        raise ValueError('old_text must be nonempty text')
    if not isinstance(new_text, str):
        raise ValueError('new_text must be text')


def _diff(path: str, before: bytes, after: bytes) -> str:
    lines = unified_diff(before.decode('utf-8').splitlines(keepends=True),
                         after.decode('utf-8').splitlines(keepends=True),
                         fromfile=f'a/{path}', tofile=f'b/{path}')
    return ''.join(line if line.endswith('\n') else line + '\n\\ No newline at end of file\n'
                   for line in lines)


def _atomic_replace(target: Path, raw: bytes):
    """Close the fully written same-directory temp file before replacing target.

    Ordinary file mode bits are preserved, not ownership, ACLs or all metadata.
    Failed writes/replacements clean up the temp file without opening target for
    writing. An OS refusal to delete the temp file remains an explicit IO error.
    """
    mode = stat.S_IMODE(target.stat().st_mode)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', dir=target.parent,
                                         prefix='.devagent-edit-', delete=False) as stream:
            temporary = Path(stream.name)
            if stream.write(raw) != len(raw):
                raise OSError('incomplete temporary write')
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class WorkspaceEditor:
    """Trusted host binds root/budget; callers cannot override them per edit.

    Cooperating writers must use this class in the same process. Workspace
    directory topology must remain trusted/stable, as required by L02.
    """

    def __init__(self, root: str | Path, *, max_bytes: int = files.DEFAULT_MAX_BYTES):
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError('max_bytes must be a positive integer')
        with files._filesystem_errors():
            self._root = files._canonical_root(root)
        self._max_bytes = max_bytes
        with _LOCKS_GUARD:
            self._lock = _LOCKS.setdefault(self._root, Lock())
        self._undo: dict[str, _UndoRecord] = {}

    @staticmethod
    def _failure(operation_id, path, code, message, before_hash=None):
        return EditResult(operation_id, path, False, before_hash=before_hash,
                          error=ToolError(code, message))

    def apply_edit(self, path: str | Path, expected_hash: str, old_text: str,
                   new_text: str, operation_id: str) -> EditResult:
        """Authorize/read, compare version, require one match, then replace."""
        _operation_id(operation_id)
        _validate_edit(expected_hash, old_text, new_text)
        canonical_path = ''  # Never echo an unauthorized absolute path in errors.
        current_hash = None
        try:
            with self._lock, files._filesystem_errors():
                snapshot = files._read_snapshot(self._root, path, self._max_bytes)
                canonical_path, current_hash = snapshot.path, snapshot.source_hash
                if operation_id in self._undo:
                    return self._failure(operation_id, canonical_path, 'operation_conflict',
                                         'operation_id already has an undo record', current_hash)
                if current_hash != expected_hash:
                    return self._failure(operation_id, canonical_path, 'stale_version',
                                         'file version changed; read again', current_hash)
                first = snapshot.text.find(old_text)
                if first < 0:
                    return self._failure(operation_id, canonical_path, 'no_match',
                                         'old_text was not found', current_hash)
                # Detect overlapping occurrences as well, unlike str.count().
                if snapshot.text.find(old_text, first + 1) >= 0:
                    return self._failure(operation_id, canonical_path, 'ambiguous_match',
                                         'old_text must match exactly once', current_hash)
                if len(new_text) > self._max_bytes:
                    return self._failure(operation_id, canonical_path, 'unsupported_content',
                                         'replacement exceeds byte policy', current_hash)
                text = snapshot.text[:first] + new_text + snapshot.text[first + len(old_text):]
                try:
                    raw = text.encode('utf-8')
                except UnicodeEncodeError:
                    return self._failure(operation_id, canonical_path, 'unsupported_content',
                                         'replacement must be UTF-8 text', current_hash)
                if len(raw) > self._max_bytes or any(ord(c) < 32 and c not in '\t\n\r' for c in text):
                    return self._failure(operation_id, canonical_path, 'unsupported_content',
                                         'replacement exceeds text or byte policy', current_hash)
                # UTF-8 decoding/encoding preserves all accepted original bytes,
                # including CRLF and BOM; no read_text newline conversion occurs.
                before = snapshot.text.encode('utf-8')
                after_hash = sha256(raw).hexdigest()
                diff = _diff(canonical_path, before, raw)
                _atomic_replace(self._root / canonical_path, raw)
                self._undo[operation_id] = _UndoRecord(canonical_path, before, current_hash, after_hash)
                return EditResult(operation_id, canonical_path, True, current_hash, after_hash, diff)
        except files.FileAccessError as exc:
            return self._failure(operation_id, canonical_path, exc.code, str(exc), current_hash)

    def rollback(self, operation_id: str) -> EditResult:
        """Restore saved bytes only while current version is this edit's after."""
        _operation_id(operation_id)
        canonical_path = ''
        current_hash = None
        try:
            with self._lock, files._filesystem_errors():
                record = self._undo.get(operation_id)
                if record is None:
                    return self._failure(operation_id, '', 'unknown_operation', 'no undo record for operation_id')
                canonical_path = record.path
                snapshot = files._read_snapshot(self._root, canonical_path, self._max_bytes)
                current_hash = snapshot.source_hash
                if current_hash != record.after_hash:
                    return self._failure(operation_id, canonical_path, 'rollback_conflict',
                                         'file changed after edit; rollback refused', current_hash)
                diff = _diff(canonical_path, snapshot.text.encode('utf-8'), record.before)
                _atomic_replace(self._root / canonical_path, record.before)
                del self._undo[operation_id]
                return EditResult(operation_id, canonical_path, True, current_hash, record.before_hash, diff)
        except files.FileAccessError as exc:
            return self._failure(operation_id, canonical_path, exc.code, str(exc), current_hash)
