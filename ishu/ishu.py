import argparse
from contextlib import contextmanager
from datetime import datetime
from itertools import chain
import sys
from typing import (Callable, Dict, Iterable, Iterator,
                    List, NamedTuple, Optional, Set, Union)

from .common import (C_RED, C_RESET, Config, format_table,
                     IncompleteConfigException,
                     InvalidConfigException, ROOT, user_path, user_paths)
from .models import Comment, Issue, IssueID, IssueStatus

# TODO: unify output better, cause right now we've got:
#   - argparse messages/errors
#   - regular print info
#   - regular print but as errors
# maybe use stderr for errors, or dump everything in argparse?
# prolly not logging tho since that isn't really meant for a cli


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


# == Data structures ==

# == Commands ==

def cmd_init(config: Config, args: argparse.Namespace) -> None:
    if ROOT.exists():
        print(f'There is already an ishu project in {ROOT}')
    else:
        ROOT.mkdir(exist_ok=True)
        print(f'Created ishu project in {ROOT}')


def cmd_configure(config: Optional[Config], args: argparse.Namespace) -> None:
    no_conf_help = ('No valid config found, please '
                    'run `ishu conf --set user USER`')
    # List settings
    if args.list_settings:
        if config is None:
            print(no_conf_help)
            return
        for key in sorted(Config.settings):
            print(f'{key} = {config[key]}')
    # Get settings
    elif args.get_setting:
        if config is None:
            print(no_conf_help)
            return
        key = args.get_setting
        print(f'{key} = {config.user}')
    # Set settings
    elif args.set_setting:
        key, value = args.set_setting
        if key not in Config.settings:
            print(f'Invalid config key: {key!r}')
            return
        try:
            updated_config: Config
            if config is None:
                updated_config = Config(**{key: value})
            else:
                config[key] = value
                updated_config = config
        except InvalidConfigException as e:
            print('Error in config value: {e}')
        else:
            print(f'{key} -> {value}')
            updated_config.save()
            print('Config saved')
    else:
        print('Nothing to do, run with --help to see available options')


def cmd_info(config: Config, args: argparse.Namespace) -> None:
    issue = Issue.load_from_id(args.issue_id)
    print(issue.info(config))


def cmd_open(config: Config, args: argparse.Namespace) -> None:
    issues = load_issues(user=config.user)
    new_id_num = max(chain((i.id_.num for i in issues), [0]))
    now = datetime.utcnow()
    issue = Issue(id_=IssueID(num=new_id_num + 1, user=config.user),
                  created=now,
                  updated=now,
                  description=args.description,
                  tags=(args.tags or set()),
                  blocked_by=(args.blocked_by or set()),
                  comments=[],
                  status=IssueStatus.OPEN)
    print(repr(issue.blocked_by))
    issue.save()
    print(f'Issue #{issue.id_.num} opened')


def _change_status(user: str, issue_id: IssueID,
                   target_status: IssueStatus,
                   status_text: str, result_text: str,
                   comment_text: Optional[str] = None) -> None:
    issue = Issue.load_from_id(issue_id)
    if issue.status == target_status:
        print(f'Issue is already {status_text}')
    else:
        issue._replace(status=target_status).save()
        if comment_text:
            Comment(issue_id=issue_id, user=user, created=datetime.now(),
                    message=comment_text).save()
        print(f'Issue {issue_id.num} {result_text}')


def cmd_reopen(config: Config, args: argparse.Namespace) -> None:
    _change_status(config.user, args.issue_id, IssueStatus.OPEN,
                   'open', 'reopened')


def cmd_edit(config: Config, args: argparse.Namespace) -> None:
    issue = Issue.load_from_id(args.issue_id)
    changed = False
    if args.desc and args.desc != issue.description:
        issue = issue._replace(description=args.desc)
        changed = True
    if args.add_tags and not args.add_tags.issubset(issue.tags):
        issue.tags.update(args.add_tags)
        changed = True
    if args.remove_tags and args.remove_tags.intersection(issue.tags):
        issue.tags.difference_update(args.remove_tags)
        changed = True
    if changed:
        issue.save()
        print('Issue edited')
    else:
        print('Nothing to update')


def cmd_fixed(config: Config, args: argparse.Namespace) -> None:
    _change_status(config.user, args.issue_id, IssueStatus.FIXED,
                   'marked as fixed', 'closed and marked as fixed',
                   comment_text=args.comment)


def cmd_wontfix(config: Config, args: argparse.Namespace) -> None:
    _change_status(config.user, args.issue_id, IssueStatus.WONTFIX,
                   'marked as wontfix', 'closed and marked as wontfix',
                   comment_text=args.comment)


def cmd_blocked_by(config: Config, args: argparse.Namespace) -> None:
    if args.blocked_id == args.blocking_id:
        print("An issue can't block itself")
        return
    issue = Issue.load_from_id(args.blocked_id)
    if args.blocking_id in issue.blocked_by:
        print(f'Issue #{args.blocked_id.shorten(config)} is already '
              f'blocked by #{args.blocking_id.shorten(config)}')
    else:
        issue.blocked_by.add(args.blocking_id)
        issue.save()
        print(f'Issue #{args.blocked_id.shorten(config)} marked as '
              f'blocked by #{args.blocking_id.shorten(config)}')


def cmd_comment(config: Config, args: argparse.Namespace) -> None:
    comment = Comment(issue_id=args.issue_id,
                      user=config.user,
                      created=datetime.now(),
                      message=args.message)
    comment.save()
    print('Comment added')


def cmd_list(config: Config, args: argparse.Namespace) -> None:
    all_issues = load_issues()
    issues: List[Issue] = []
    for issue in all_issues:
        blocking = [i for i in all_issues
                    if i.id_ != issue.id_ and issue.id_ in i.blocked_by]
        if args.tags and not args.tags.issubset(issue.tags):
            continue
        if args.without_tags and args.without_tags.intersection(issue.tags):
            continue
        if args.blocking and not any(blocking):
            continue
        if args.blocked and not issue.blocked_by:
            continue
        if args.no_blocks and (issue.blocked_by or any(blocking)):
            continue
        if args.status:
            status = IssueStatus(args.status)
            if status == IssueStatus.CLOSED \
                    and issue.status == IssueStatus.OPEN:
                continue
            elif status != IssueStatus.CLOSED and status != issue.status:
                continue
        issues.append(issue)
    titles = ('ID', 'User', 'Status', 'Created', 'Updated', 'Description')
    table = [
        (str(i.id_.num),
         i.id_.user,
         i.status.value.capitalize(),
         i.created.strftime('%Y-%m-%d'),
         (i.updated.strftime('%Y-%m-%d') if i.updated > i.created else ''),
         i.description)
        for i in issues
    ]
    for line in format_table(table, wrap_columns={4}, titles=titles):
        print(line)


def cmd_log(config: Config, args: argparse.Namespace) -> None:
    print('TODO')


def cmd_tag(config: Config, args: argparse.Namespace) -> None:
    print('TODO')


# == Command line parsing ==

def add_conf_parser_options(p: argparse.ArgumentParser) -> None:
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--list', help='list all settings and their values',
                   action='store_true', dest='list_settings')
    g.add_argument('--get', help='print the value of a setting',
                   choices=Config.settings, metavar='KEY', dest='get_setting')
    g.add_argument('--set', help='set the value of a setting',
                   nargs=2, metavar=('KEY', 'VALUE'), dest='set_setting')


class Command(NamedTuple):
    aliases: List[str]
    desc: str


def parse_commands(config: Config) -> None:
    parser = argparse.ArgumentParser(usage='%(prog)s [-h | --help] [COMMAND]',
                                     add_help=False)
    parser.set_defaults(func=None)
    subparsers = parser.add_subparsers()

    commands: Dict[str, 'Command'] = {}

    parser.add_argument('--help', '-h', help='show this help message and exit',
                        action='store_true')

    def show_help() -> None:
        parser.print_usage()
        table: List[Union[str, Iterable[str]]] = ['\ncommands:']
        for cmd_name, cmd in commands.items():
            name = ', '.join([cmd_name] + cmd.aliases)
            table.append((f'  {name}', cmd.desc))
        table.extend(
            ['\noptional arguments:',
             ('  -h, --help', 'show this help message and exit')]
        )
        for line in format_table(table, column_spacing=4, wrap_columns={1}):
            print(line)

    def tag_list_type(text: str) -> Set[str]:
        return {t for t in text.split(',') if t}

    def issue_id_type(restrict_to_own: bool = False
                      ) -> Callable[[str], IssueID]:
        def _id_type(text: str) -> IssueID:
            try:
                issue_id = IssueID.load(config, text,
                                        restrict_to_own=restrict_to_own)
            except Exception as e:
                raise argparse.ArgumentTypeError(str(e))
            else:
                return issue_id
        return _id_type

    def issue_id_list_type(text: str) -> List[IssueID]:
        out = []
        for item in text.split(','):
            out.append(issue_id_type()(item))
        return out

    @contextmanager
    def add_cmd(cmd_name: str, aliases: List[str],
                callback: Callable[[Config, argparse.Namespace], None],
                description: str, add_help: bool = True
                ) -> Iterator[argparse.ArgumentParser]:
        p = subparsers.add_parser(cmd_name, aliases=aliases, add_help=add_help)
        commands[cmd_name] = Command(aliases, description)
        yield p
        p.set_defaults(func=callback)

    def add_id_argument(p: argparse.ArgumentParser) -> None:
        p.add_argument('issue_id', type=issue_id_type(),
                       help='the id of any issue')

    def add_own_id_argument(p: argparse.ArgumentParser) -> None:
        p.add_argument('issue_id', type=issue_id_type(restrict_to_own=True),
                       help='the id of one of your own issues')

    # Init
    with add_cmd('init', [], cmd_init, 'initialize an ishu directory') as c:
        pass

    # Configure
    with add_cmd('conf', ['cfg'], cmd_configure,
                 'view and edit settings', add_help=True) as c:
        add_conf_parser_options(c)

    # Show info
    with add_cmd('show', ['s'], cmd_info, 'show info about an issue') as c:
        add_id_argument(c)

    # Open
    with add_cmd('open', ['o'], cmd_open, 'open a new issue') as c:
        c.add_argument('--tags', '-t', type=tag_list_type)
        c.add_argument('--blocked-by', '-b', type=issue_id_list_type,
                       metavar='ISSUE')
        c.add_argument('description')

    # Reopen
    with add_cmd('reopen', ['r'], cmd_reopen, 'reopen a closed issue') as c:
        add_own_id_argument(c)

    # Edit
    with add_cmd('edit', ['e'], cmd_edit, 'edit an issue') as c:
        add_id_argument(c)
        c.add_argument('--desc', '-d')
        c.add_argument('--add-tags', '-t', type=tag_list_type)
        c.add_argument('--remove-tags', '-T', type=tag_list_type)

    # Fixed
    with add_cmd('fixed', ['f'], cmd_fixed,
                 'close an issue and mark it as fixed') as c:
        add_id_argument(c)
        c.add_argument('comment', nargs='?')

    # Wontfix
    with add_cmd('wontfix', ['w'], cmd_wontfix,
                 'close an issue and mark it as not going to be fixed') as c:
        add_id_argument(c)
        c.add_argument('comment', nargs='?')

    # Blocking
    with add_cmd('blocked', ['b'], cmd_blocked_by,
                 ('mark an issue as being blocked by another '
                  'issue from completion')) as c:
        c.add_argument('blocked-id', type=issue_id_type(restrict_to_own=True),
                       metavar='ISSUE')
        c.add_argument('blocking-id', type=issue_id_type(),
                       metavar='ISSUE')

    # Unblock
    with add_cmd('unblock', ['ub'], cmd_blocked_by,
                 ('mark an issue as not being blocked by another '
                  'issue from completion')) as c:
        c.add_argument('blocked-id', type=issue_id_type(restrict_to_own=True),
                       metavar='ISSUE')
        c.add_argument('blocking-id', type=issue_id_type(),
                       metavar='ISSUE')

    # Comment
    with add_cmd('comment', ['c'], cmd_comment,
                 'add a comment to an issue') as c:
        add_id_argument(c)
        c.add_argument('message')

    # List
    with add_cmd('list', ['ls'], cmd_list,
                 'list all issues or ones matching certain filters') as c:
        c.add_argument('--status', '-s',
                       choices=[s.value for s in IssueStatus])
        c.add_argument('--tags', '-t', type=tag_list_type)
        c.add_argument('--without-tags', '-T', type=tag_list_type,
                       metavar='TAGS')
        block_group = c.add_mutually_exclusive_group()
        block_group.add_argument('--blocked', '-b', action='store_true',
                                 help='show only blocked issues')
        block_group.add_argument('--blocking', '-B', action='store_true',
                                 help='show only blocking issues')
        block_group.add_argument('--no-blocks', '-n', action='store_true',
                                 help='don\'t show any blocked '
                                      'or blocking issues')

    # Log
    with add_cmd('log', ['l'], cmd_log,
                 'show a log of the latest actions (open/close/etc)') as c:
        c.add_argument('max-count', type=int, nargs='?')

    # Tag
    with add_cmd('tag', ['t'], cmd_tag, 'edit the tags of an issue') as c:
        c.add_argument('--new', '-n', type=tag_list_type)
        c.add_argument('--remove', '-r', type=tag_list_type)
        c.add_argument('--edit', '-e', nargs=2, help='rename tag')
        c.add_argument('--list', '-l')

    # Fiddle with sys.argv a litte to get better error messages
    valid_subcommands: Set[str] = {c for cmd_name, cmd in commands.items()
                                   for c in [cmd_name] + cmd.aliases}
    sysargs = sys.argv[1:]
    if sysargs and sysargs[0] in {'-h', '--help'}:
        sysargs = sysargs[:1]
    elif sysargs and sysargs[0] not in valid_subcommands:
        parser.error(f'{sysargs[0]} is not a valid command')
    else:
        args = parser.parse_args(args=sysargs)
        if args.func is None:
            show_help()
        else:
            if not ROOT.exists() and args.func != cmd_init:
                print(f'{C_RED}No ishu directory found! '
                      f'Run `ishu init` to create one.{C_RESET}')
            else:
                args.func(config, args)


def parse_commands_not_initialized() -> None:
    desc = (f'{C_RED}You have not set you username in the config, '
            f'which you need before you can use the rest of the program.'
            f'Run `ishu conf --user USER` to set it.{C_RESET}')
    parser = argparse.ArgumentParser(description=desc)
    parser.set_defaults(func=None)
    subparsers = parser.add_subparsers(dest='cmd')
    # Conf parser
    conf_parser = subparsers.add_parser('conf', aliases=['cfg'],
                                        add_help=True)
    conf_parser.set_defaults(func=cmd_configure)
    add_conf_parser_options(conf_parser)
    # Parser everything
    args = parser.parse_args()
    if args.help or args.func is None:
        parser.print_help()
    else:
        args.func(None, args)


if __name__ == '__main__':
    try:
        config = Config.load()
    except (FileNotFoundError, IncompleteConfigException):
        parse_commands_not_initialized()
    else:
        parse_commands(config)
