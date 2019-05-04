from itertools import zip_longest
import json
from pathlib import Path
import re
import shutil
import textwrap
from typing import (Any, Collection, Dict, Iterable, List,
                    Optional, Sized, Tuple, Union)


C_RED = '\x1b[31m'
C_RESET = '\x1b[0m'


ROOT = Path().resolve() / '.ishu'
# Don't call this 'tags' to avoid conflicts with ctags
TAGS_PATH = ROOT / 'registered_tags'
ISSUE_FNAME = 'issue'
TIMESTAMP_FMT = '%Y-%m-%dT%H:%M:%SZ'
CONFIG_PATH = Path.home() / '.config' / 'ishu.conf'


# == Misc helpers ==

def clean_esc(text: str) -> str:
    return re.sub(r'\x1b\[[0-9;]m', '', text)


def strlen(val: Sized) -> int:
    """Get length of a string without including ANSI escape codes"""
    if isinstance(val, str):
        return len(clean_esc(val))
    else:
        return len(val)


def format_table(items: Iterable[Union[str, Iterable[str]]],
                 column_spacing: int = 2,
                 wrap_columns: Optional[Collection[int]] = None,
                 titles: Optional[Iterable[str]] = None,
                 surround_rows: Optional[Dict[int, Tuple[str, str]]] = None
                 ) -> Iterable[str]:
    term_size = shutil.get_terminal_size()
    wrap_columns = wrap_columns or set()
    surround_rows = surround_rows or dict()
    rows: List[Union[str, List[str]]] = []
    if titles:
        rows.append(list(titles))
    for row in items:
        rows.append(row if isinstance(row, str) else list(row))
    if not rows:
        return
    max_row_length = max(strlen(row) for row in rows
                         if not isinstance(row, str))
    rows = [row if isinstance(row, str)
            else row + ([''] * (max_row_length - strlen(row)))
            for row in rows]
    max_widths = [max(strlen(row[col]) for row in rows
                      if not isinstance(row, str))
                  for col in range(max_row_length)]
    total_spacing = (strlen(max_widths) - 1) * column_spacing
    if sum(max_widths) + total_spacing > term_size.columns and wrap_columns:
        unwrappable_space = sum(w for n, w in enumerate(max_widths)
                                if n not in wrap_columns)
        wrappable_space = (term_size.columns - total_spacing
                           - unwrappable_space) // strlen(wrap_columns)
        for n in wrap_columns:
            max_widths[n] = wrappable_space
    else:
        wrappable_space = -1
    if titles:
        rows.insert(1, '-' * (sum(max_widths) + total_spacing))
    for row_num, row in enumerate(rows, -2 if titles else 0):
        prefix, suffix = surround_rows.get(row_num, ('', ''))
        if isinstance(row, str):
            yield prefix + row + suffix
        else:
            cells = [textwrap.wrap(cell, width=wrappable_space)
                     if wrappable_space > 0 and n in wrap_columns
                     else [cell.ljust(max_widths[n])]
                     for n, cell in enumerate(row)]
            for subrow in zip_longest(*cells):
                subcells = (c or (' ' * max_widths[n])
                            for n, c in enumerate(subrow))
                line = (' ' * column_spacing).join(subcells).rstrip()
                yield prefix + line + suffix


# == Filesystem handlers ==

def user_path(user: str) -> Path:
    return ROOT / f'user-{user}'


def user_paths() -> Iterable[Path]:
    return ROOT.glob('user-*')


def usernames() -> Iterable[str]:
    return [f.name.split('-', 1)[1] for f in user_paths()]


def issue_path(user: str, id_: int) -> Path:
    return user_path(user) / f'issue-{id_}' / ISSUE_FNAME


def comment_paths(user: str, id_: int) -> Iterable[Path]:
    return issue_path(user, id_).parent.glob('comment-*')


# == Config ==

class IncompleteConfigException(Exception):
    pass


class InvalidConfigException(Exception):
    pass


class Config:
    settings = frozenset(['user'])

    def __init__(self, user: str) -> None:
        self.user = user

    def __getitem__(self, key: str) -> Any:
        if key == 'user':
            return self.user
        else:
            raise KeyError('No such setting')

    def __setitem__(self, key: str, value: Any) -> None:
        if key == 'user':
            if not re.fullmatch(r'[a-zA-Z]+', value):
                raise InvalidConfigException('username can only consist '
                                             'of a-z and A-Z')
            self.user = value
        else:
            raise KeyError('No such setting')

    @classmethod
    def load(cls) -> 'Config':
        data: Dict[str, Any] = json.loads(CONFIG_PATH.read_text())
        return Config(user=data['user'])

    def save(self) -> None:
        if not CONFIG_PATH.parent.exists():
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        data: Dict[str, Any] = {
            'user': self.user
        }
        CONFIG_PATH.write_text(json.dumps(data, indent=2))
