"""Literal, case-sensitive search; candidates are not read evidence."""
from fnmatch import fnmatchcase
from functools import lru_cache
import os
from pathlib import Path

from . import files

MAX_RESULTS = 100
MAX_FILES = 128
MAX_ENTRIES = 2048
MAX_DEPTH = 32


def validate_search_arguments(query, include_globs=None, max_results=20):
    if not isinstance(query, str) or not query.strip() or len(query) > 256:
        raise ValueError('query must be nonempty text of at most 256 characters')
    if type(max_results) is not int or not 1 <= max_results <= MAX_RESULTS:
        raise ValueError(f'max_results must be an integer in 1..{MAX_RESULTS}')
    if include_globs is None:
        return
    if not isinstance(include_globs, (list, tuple)) or not 1 <= len(include_globs) <= 16:
        raise ValueError('include_globs must contain 1..16 relative patterns')
    for pattern in include_globs:
        if (not isinstance(pattern, str) or not pattern or len(pattern) > 256
                or '\\' in pattern or ':' in pattern or '\x00' in pattern
                or any(part in {'', '.', '..'} for part in pattern.split('/'))):
            raise ValueError('include_globs must be relative workspace patterns')


def _matches(path: str, pattern: str) -> bool:
    """Basename-only globs match at any depth; ** matches zero or more dirs."""
    parts, patterns = path.split('/'), pattern.split('/')
    if len(patterns) == 1:
        return fnmatchcase(parts[-1], pattern)

    @lru_cache(None)
    def match(i, j):
        if j == len(patterns):
            return i == len(parts)
        if patterns[j] == '**':
            return match(i, j + 1) or (i < len(parts) and match(i + 1, j))
        return i < len(parts) and fnmatchcase(parts[i], patterns[j]) and match(i + 1, j + 1)

    return match(0, 0)


def search_text(root: str | Path, query: str, include_globs=None, max_results: int = 20) -> dict:
    """Host fixes root and caps; at most MAX_FILES*(64KiB+1) bytes are read.

    Reaching a result or traversal cap conservatively marks incomplete coverage.
    Enumeration uses filesystem order (no ranking); all links/junctions are skipped.
    Unsupported text is excluded; access/I/O failures remain failures, not no-match.
    """
    validate_search_arguments(query, include_globs, max_results)
    patterns = include_globs or ('**/*',)
    matches = []
    entries = scanned = 0
    truncated = False
    with files._filesystem_errors():
        workspace = files._canonical_root(root)

        def visit(directory, depth=0):
            nonlocal entries, scanned, truncated
            with os.scandir(directory) as listing:
                for entry in listing:
                    if entries >= MAX_ENTRIES:
                        truncated = True
                        return
                    entries += 1
                    path = Path(entry.path)
                    if entry.name.startswith('.') or entry.is_symlink() or path.is_junction():
                        continue
                    target = files._authorize(workspace, path)
                    if entry.is_dir(follow_symlinks=False):
                        if depth >= MAX_DEPTH:
                            truncated = True
                            continue
                        yield from visit(target, depth + 1)
                    elif (entry.is_file(follow_symlinks=False) and target.suffix.lower() in files.TEXT_SUFFIXES
                          and any(_matches(target.relative_to(workspace).as_posix(), p) for p in patterns)):
                        if scanned >= MAX_FILES:
                            truncated = True
                            return
                        scanned += 1
                        yield target
                    if entries >= MAX_ENTRIES or scanned >= MAX_FILES:
                        truncated = True
                        return

        paths = visit(workspace)
        try:
            for path in paths:
                try:
                    snapshot = files._read_snapshot(workspace, path)
                except files.FileAccessError as exc:
                    if exc.code == 'unsupported_content':
                        continue
                    raise
                for line, text in enumerate(snapshot.text.splitlines(), 1):
                    if query in text:
                        matches.append({'path': snapshot.path, 'line': line, 'snippet': text})
                        if len(matches) >= max_results:
                            return {'matches': matches, 'truncated': True, 'scanned_files': scanned}
        finally:
            paths.close()
    return {'matches': matches, 'truncated': truncated, 'scanned_files': scanned}
