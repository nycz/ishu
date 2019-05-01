from datetime import datetime
import enum
import json
from pathlib import Path
import re
import textwrap
from typing import Any, Dict, List, NamedTuple, Set

from .common import (Config, format_table, issue_path, ISSUE_FNAME,
                     TIMESTAMP_FMT, usernames)


class IssueID(NamedTuple):
    user: str
    num: int

    def shorten(self, config: Config) -> str:
        if self.user == config.user:
            prefix = ''
        else:
            users = usernames()
            for i in range(1, len(self.user) - 1):
                prefix = self.user[:i]
                matches = [u for u in users if u.startswith(prefix)]
                if len(matches) == 1:
                    break
            else:
                prefix = self.user
        return f'{prefix}{self.num}'

    @classmethod
    def load(cls, config: Config, abbr_id: str,
             restrict_to_own: bool = False) -> 'IssueID':
        if not restrict_to_own:
            match = re.fullmatch(r'(?P<user>[a-zA-Z]+)?(?P<num>\d+)', abbr_id)
            if match is None:
                raise ValueError('Invalid issue ID format')
            user_match = match['user']
            users = usernames()
            user: str
            if user_match is None:
                user = config.user
            elif user_match in users:
                user = user_match
            else:
                candidates = [u for u in users if u.startswith(user_match)]
                if not candidates:
                    raise KeyError('Unknown user')
                elif len(candidates) > 1:
                    raise KeyError(f'Ambiguous user (can be one of '
                                   f'{", ".join(candidates)})')
                else:
                    user = candidates[0]
            num = int(match['num'])
        else:
            user = config.user
            num = int(abbr_id)
        if not issue_path(user, num).exists():
            raise KeyError("Issue doesn't exist")
        return cls(user, num)


class Comment(NamedTuple):
    issue_id: IssueID
    user: str
    created: datetime
    message: str

    def __str__(self) -> str:
        subject_line = (f'[{self.user} - '
                        f'{self.created.strftime("%Y-%m-%d %H:%M:%S")}]')
        return '\n'.join([subject_line] + textwrap.wrap(self.message))

    @classmethod
    def load(cls, file_path: Path) -> 'Comment':
        data: Dict[str, Any] = json.loads(file_path.read_text())
        return cls(issue_id=IssueID(user=data['issue_id']['user'],
                                    num=data['issue_id']['num']),
                   user=data['user'],
                   created=datetime.strptime(data['created'], TIMESTAMP_FMT),
                   message=data['message'])

    def save(self) -> None:
        path = issue_path(self.issue_id.user, self.issue_id.num).parent
        now = self.created.strftime('%Y-%m-%dT%H-%M-%S')
        suffix = 0
        while True:
            fname = f'comment-{now}{"-" + str(suffix) if suffix else ""}'
            if not (path / fname).exists():
                break
            suffix += 1
        (path / fname).write_text(json.dumps({
            'issue_id': {'user': self.issue_id.user,
                         'num': str(self.issue_id.num)},
            'user': self.user,
            'created': self.created.strftime(TIMESTAMP_FMT),
            'message': self.message
        }, indent=2))


@enum.unique
class IssueStatus(enum.Enum):
    OPEN = 'open'
    CLOSED = 'closed'
    FIXED = 'fixed'
    WONTFIX = 'wontfix'

    def __str__(self) -> str:
        v: str = self.value
        return v


class Issue(NamedTuple):
    id_: IssueID
    created: datetime
    updated: datetime
    description: str
    tags: Set[str]
    blocked_by: Set[IssueID]
    comments: List[Comment]
    status: IssueStatus

    def info(self, config: Config) -> str:
        table = [
            ('ID', str(self.id_.num)),
            ('User', self.id_.user),
            ('Status', str(self.status)),
            ('Created', self.created.strftime('%Y-%m-%d')),
            ('Updated', (self.updated.strftime('%Y-%m-%d')
                         if self.updated else '')),
            ('Tags', ', '.join(self.tags)),
            ('Blocked by', ', '.join(i.shorten(config)
                                     for i in self.blocked_by)),
            ('Description', self.description),
        ]
        info = '\n'.join(format_table(table, wrap_columns={1},
                                      column_spacing=3))
        if self.comments:
            comments = '\n\n'.join(map(str, self.comments))
            info += '\nComments:\n\n' + comments
        return info

    @classmethod
    def load_from_id(cls, id_: IssueID) -> 'Issue':
        return cls.load(issue_path(*id_).parent)

    @classmethod
    def load(cls, path: Path) -> 'Issue':
        if path.name == ISSUE_FNAME:
            path = path.parent
        data: Dict[str, Any] = json.loads((path / ISSUE_FNAME).read_text())
        comments = sorted((Comment.load(p) for p in path.glob('comment-*')),
                          key=lambda x: x.created)
        return cls(id_=IssueID(num=data['id'], user=data['user']),
                   created=datetime.strptime(data['created'], TIMESTAMP_FMT),
                   updated=datetime.strptime(data['updated'], TIMESTAMP_FMT),
                   description=data['description'],
                   tags=set(data['tags']),
                   blocked_by={IssueID(num=i['id'], user=i['user'])
                               for i in data['blocked_by']},
                   comments=comments,
                   status=IssueStatus(data['status']))

    def save(self) -> None:
        path = issue_path(*self.id_)
        if not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            'id': self.id_.num,
            'user': self.id_.user,
            'created': self.created.strftime(TIMESTAMP_FMT),
            'updated': self.updated.strftime(TIMESTAMP_FMT),
            'description': self.description,
            'tags': sorted(self.tags),
            'blocked_by': sorted(({'id': b.num, 'user': b.user}
                                  for b in self.blocked_by),
                                 key=lambda x: x['id']),
            'status': self.status.value
        }, indent=2))
