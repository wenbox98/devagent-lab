"""Read evidence and current-version validation; search hits do not qualify."""
from dataclasses import dataclass

from ..tools import files


@dataclass(frozen=True)
class Citation:
    source_path: str
    start_line: int
    end_line: int
    content: str
    source_hash: str


class CitationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def citation_from_read(read: files.FileReadResult) -> Citation:
    if not read.source_hash or read.end_line < read.start_line:
        raise CitationError('invalid_citation', 'read must contain versioned lines')
    return Citation(read.path, read.start_line, read.end_line, read.content, read.source_hash)


def validate_citation(root, citation: Citation) -> None:
    """Validate current file/range/content. Provenance is separately checked by loop."""
    if (not isinstance(citation, Citation) or not isinstance(citation.source_path, str)
            or not citation.source_path or not isinstance(citation.content, str)
            or type(citation.start_line) is not int or type(citation.end_line) is not int
            or not 1 <= citation.start_line <= citation.end_line
            or not isinstance(citation.source_hash, str) or len(citation.source_hash) != 64
            or any(c not in '0123456789abcdef' for c in citation.source_hash)):
        raise CitationError('invalid_citation', 'invalid citation fields')
    try:
        current = files._read_snapshot(root, citation.source_path)
    except files.FileAccessError as exc:
        raise CitationError(exc.code, str(exc)) from exc
    if current.path != citation.source_path:
        raise CitationError('invalid_citation', 'citation path must be canonical workspace-relative')
    if current.source_hash != citation.source_hash:
        raise CitationError('stale_evidence', 'file version changed; read again')
    lines = current.text.splitlines(keepends=True)
    if citation.end_line > len(lines) or ''.join(lines[citation.start_line - 1:citation.end_line]) != citation.content:
        raise CitationError('invalid_citation', 'citation lines or content do not match')
