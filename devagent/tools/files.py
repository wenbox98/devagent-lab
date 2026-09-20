"""L02: bounded UTF-8 reads in a trusted, non-concurrently-mutated workspace.

The host supplies root and max_bytes; never bind these from model arguments.
Canonical containment is not an OS sandbox or protection against path-swap races.
Only visible regular files with the suffixes below are exposed.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import stat

DEFAULT_MAX_BYTES = 64 * 1024
TEXT_SUFFIXES = frozenset({'.py', '.md', '.txt', '.json', '.toml', '.yaml', '.yml',
                           '.java', '.js', '.ts', '.css', '.html', '.csv'})


class FileAccessError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@contextmanager
def _filesystem_errors():
    try:
        yield
    except PermissionError as exc:
        raise FileAccessError('permission_denied', 'filesystem access denied') from exc
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise FileAccessError('not_found', 'workspace or file not found') from exc
    except OSError as exc:
        raise FileAccessError('io_error', 'filesystem operation failed') from exc


def _canonical_root(root: str | Path) -> Path:
    canonical = Path(root).resolve(strict=True)
    if not canonical.is_dir():
        raise FileAccessError('unsupported_content', 'workspace root must be a directory')
    return canonical


def _authorize(root: Path, path: str | Path) -> Path:
    supplied = Path(path)
    # Disallow Windows alternate data streams even on other platforms.
    components = supplied.parts[1:] if supplied.anchor else supplied.parts
    if '\x00' in str(path) or any(':' in part for part in components):
        raise FileAccessError('permission_denied', 'invalid file path')
    candidate = supplied if supplied.is_absolute() else root / supplied
    target = candidate.resolve()
    if not target.is_relative_to(root):
        raise FileAccessError('permission_denied', 'path escapes workspace')
    relative = target.relative_to(root)
    if any(part.startswith('.') for part in relative.parts):
        raise FileAccessError('permission_denied', 'hidden workspace paths are not exposed')
    return target


@dataclass(frozen=True)
class FileReadResult:
    path: str
    start_line: int
    end_line: int
    content: str
    truncated: bool
    next_start_line: int | None


def read_file(root: str | Path, path: str | Path, start_line: int = 1,
              end_line: int | None = None, max_bytes: int = DEFAULT_MAX_BYTES) -> FileReadResult:
    """Reject whole files above the byte budget; line endpoints are inclusive.

    Empty/after-EOF selections have end_line=start_line-1. A range ending before
    EOF has truncated=True and next_start_line=end_line+1. No max-lines policy.
    """
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError('max_bytes must be a positive integer')
    if type(start_line) is not int or start_line < 1 or (
        end_line is not None and (type(end_line) is not int or end_line < start_line)
    ):
        raise ValueError('line range must be 1-based and ordered')
    with _filesystem_errors():
        workspace = _canonical_root(root)
        target = _authorize(workspace, path)
        info = target.stat()
        if not stat.S_ISREG(info.st_mode) or target.suffix.lower() not in TEXT_SUFFIXES:
            raise FileAccessError('unsupported_content', 'only allowlisted regular text files are supported')
        if info.st_size > max_bytes:
            raise FileAccessError('unsupported_content', 'file exceeds max_bytes')
        with target.open('rb', buffering=0) as stream:
            # Check the opened object too; the size can change after stat().
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise FileAccessError('unsupported_content', 'opened object is not a regular file')
            raw = stream.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise FileAccessError('unsupported_content', 'file exceeds max_bytes')
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise FileAccessError('unsupported_content', 'file is not UTF-8 text') from exc
    if any(ord(char) < 32 and char not in '\t\n\r' for char in text):
        raise FileAccessError('unsupported_content', 'file contains binary control characters')
    lines = text.splitlines(keepends=True)
    selected = lines[start_line - 1:end_line]
    last = start_line + len(selected) - 1
    more = bool(selected) and last < len(lines)
    return FileReadResult(target.relative_to(workspace).as_posix(), start_line, last,
                          ''.join(selected), more, last + 1 if more else None)


def list_files(root: str | Path) -> list[dict]:
    """List only readable files allowed by read_file's default byte/type policy.

    Directory links are never traversed. There is no directory-count budget yet.
    """
    result = []
    with _filesystem_errors():
        workspace = _canonical_root(root)

        def walk_error(error):
            raise error

        for directory, dirs, names in os.walk(workspace, followlinks=False, onerror=walk_error):
            dirs[:] = sorted(name for name in dirs if not name.startswith('.')
                             and not (Path(directory) / name).is_symlink()
                             and not (Path(directory) / name).is_junction())
            for name in sorted(names):
                if name.startswith('.'):
                    continue
                try:
                    read = read_file(workspace, Path(directory) / name)
                except FileAccessError as exc:
                    if exc.code in {'permission_denied', 'not_found', 'unsupported_content'}:
                        continue
                    raise
                result.append({'path': read.path, 'size_bytes': len(read.content.encode('utf-8'))})
    return sorted({item['path']: item for item in result}.values(), key=lambda item: item['path'])
