from datetime import datetime
import enum
import json
from pathlib import Path
import re
import textwrap
from typing import (Any, FrozenSet, Dict, Iterable, List, NamedTuple,
                    Optional, Set, Tuple)

from .common import (C_BOLD, C_RESET, Config, format_table, issue_path,
                     ISSUE_FNAME,
                     TIMESTAMP_FMT, user_path, user_paths, usernames)


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
    log: List[Dict[str, Any]]
    original_description: str
    original_tags: FrozenSet[str]
    original_blocked_by: FrozenSet[IssueID]
    original_status: IssueStatus

    def info(self, config: Config) -> str:
        blocking_issues = [issue.id_ for issue in load_issues()
                           if self.id_ in issue.blocked_by]
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
            ('Blocking', ', '.join(i.shorten(config)
                                   for i in blocking_issues)),
            ('Description', self.description),
        ]
        table = [(C_BOLD + n + C_RESET, d) for n, d in table]
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
        blocked_by = {IssueID(num=i['id'], user=i['user'])
                      for i in data['blocked_by']}
        return cls(id_=IssueID(num=data['id'], user=data['user']),
                   created=datetime.strptime(data['created'], TIMESTAMP_FMT),
                   updated=datetime.strptime(data['updated'], TIMESTAMP_FMT),
                   description=data['description'],
                   tags=set(data['tags']),
                   blocked_by=blocked_by,
                   comments=comments,
                   status=IssueStatus(data['status']),
                   # Backups for log diffs
                   log=data.get('log', []),
                   original_description=data['description'],
                   original_tags=frozenset(data['tags']),
                   original_blocked_by=frozenset(blocked_by),
                   original_status=IssueStatus(data['status']))

    def save(self) -> None:
        def encode_blocks(blocks: Iterable[IssueID]
                          ) -> List[Dict[str, Any]]:
            return sorted(({'id': b.num, 'user': b.user} for b in blocks),
                          key=lambda x: x['id'])
        now = datetime.now().strftime(TIMESTAMP_FMT)
        log_diff: Dict[str, Any] = {}
        if self.description != self.original_description:
            log_diff['description'] = self.original_description
        if self.tags != self.original_tags:
            log_diff['tags'] = sorted(self.original_tags)
        if self.blocked_by != self.original_blocked_by:
            log_diff['blocked_by'] = encode_blocks(self.original_blocked_by)
        if self.status != self.original_status:
            log_diff['status'] = self.original_status.value
        if log_diff:
            log_diff['timestamp'] = now
            self.log.append(log_diff)
        path = issue_path(*self.id_)
        if not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            'id': self.id_.num,
            'user': self.id_.user,
            'created': self.created.strftime(TIMESTAMP_FMT),
            'updated': now,
            'description': self.description,
            'tags': sorted(self.tags),
            'blocked_by': encode_blocks(self.blocked_by),
            'status': self.status.value,
            'log': self.log
        }, indent=2))


def load_issues(user: Optional[str] = None) -> List['Issue']:
    issues: List['Issue'] = []
    if user:
        try:
            issues = [Issue.load(p) for p
                      in sorted(user_path(user).iterdir())]
        except FileNotFoundError:
            # TODO: maybe do something special for a user that doesn't exist?
            pass
    else:
        for userdir in user_paths():
            issues.extend(Issue.load(p) for p in sorted(userdir.iterdir()))
    return issues
