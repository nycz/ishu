import json
import os
from pathlib import Path
import re
from typing import Any, Dict, Iterable, Sized, Tuple


def _get_root() -> Tuple[bool, Path]:
    env_root = os.environ.get('ISHUROOT')
    if env_root:
        env_path = Path(env_root).expanduser().resolve()
        if env_path.exists():
            return True, (env_path / '.ishu')
    return False, (Path().resolve() / '.ishu')


ROOT_OVERRIDE, ROOT = _get_root()

# Don't call this 'tags' to avoid conflicts with ctags
TAGS_PATH = ROOT / 'registered_tags'
ISSUE_FNAME = 'issue'
TIMESTAMP_FMT = '%Y-%m-%dT%H:%M:%SZ'
CONFIG_PATH = Path.home() / '.config' / 'ishu.conf'


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
    settings = frozenset(['user', 'aliases'])

    def __init__(self, user: str) -> None:
        self.user = user
        self.aliases: Dict[str, str] = {}

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
        cfg = Config(user=data['user'])
        if 'aliases' in data:
            cfg.aliases = data['aliases']
        return cfg

    def save(self) -> None:
        if not CONFIG_PATH.parent.exists():
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        data: Dict[str, Any] = {
            'user': self.user,
            'aliases': self.aliases,
        }
        CONFIG_PATH.write_text(json.dumps(data, indent=2))
