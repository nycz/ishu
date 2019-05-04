#!/usr/bin/env python3
from datetime import datetime
from itertools import chain
from pathlib import Path
import sys
from typing import List, Optional, Set, Tuple

from .common import (C_RED, C_RESET, Config, format_table,
                     IncompleteConfigException,
                     InvalidConfigException, ROOT, user_path, user_paths)
from .models import Comment, Issue, IssueID, IssueStatus


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


def error(message: str) -> None:
    sys.exit(f'{C_RED}Error:{C_RESET} {message}')


# == Command parsing helpers ==

def _arg_issue_id(args: List[str], config: Config,
                  specify_id: bool = False,
                  restrict_to_own: bool = False) -> IssueID:
    try:
        raw_issue_id = args.pop(0)
    except IndexError:
        error('issue ID required')
    try:
        issue_id = IssueID.load(config, raw_issue_id,
                                restrict_to_own=restrict_to_own)
    except Exception as e:
        if specify_id:
            error(f'failed to parse issue ID {raw_issue_id}: {e}')
        else:
            error(str(e))
    return issue_id


def _arg_tags(args: List[str], option_name: str) -> Set[str]:
    tags = set()
    while args and not args[0].startswith('-'):
        tags.add(args.pop(0))
    if not tags:
        error(f'no tags specified for {option_name}')
    return tags


def _arg_positional(args: List[str], option_name: str,
                    position: int = 0) -> str:
    if not args:
        error(f'no {option_name} provided')
    return args.pop(position)


def _arg_disallow_trailing(args: List[str]) -> None:
    if args:
        error(f'unknown trailing arguments: {", ".join(map(repr, args))}')


def _arg_disallow_positional(arg: str) -> None:
    if not arg.startswith('-'):
        error(f'unknown positional argument: {arg}')


def _arg_unknown_optional(arg: str) -> None:
    error(f'unknown argument: {arg}')


# == Commands ==

CommandHelp = Tuple[str, str, List[Tuple[str, str]]]


help_init: CommandHelp = (
    'initialize an ishu directory',
    '',
    []
)


def cmd_init(config: Config, args: List[str]) -> None:
    _arg_disallow_trailing(args)
    if ROOT.exists():
        print(f'There is already an ishu project in {ROOT}')
    else:
        ROOT.mkdir(exist_ok=True)
        print(f'Created ishu project in {ROOT}')


help_configure: CommandHelp = (
    'view and edit settings',
    '(-l | -g <key> | -s <key> <value> )',
    [
        ('-l/--list', 'list settings'),
        ('-g/--get <key>', 'show the value of a setting'),
        ('-s/--set <key> <value>', 'set the value of a setting')
    ]
)


def cmd_configure(config: Optional[Config], args: List[str]) -> None:
    no_conf_help = (f'{C_RED}No valid config found, '
                    f'please set your username{C_RESET}')
    # Args
    list_settings = False
    get_setting: Optional[str] = None
    set_setting: Optional[Tuple[str, str]] = None
    # Parse args
    if not args:
        list_settings = True
    else:
        arg = args.pop(0)
        _arg_disallow_positional(arg)
        if arg in {'-l', '--list'}:
            list_settings = True
        elif arg in {'-g', '--get'}:
            try:
                get_setting = args.pop(0)
            except IndexError:
                error('--get needs an argument')
        elif arg in {'-s', '--set'}:
            try:
                set_setting = (args.pop(0), args.pop(0))
            except IndexError:
                error('--set needs two arguments')
        else:
            _arg_unknown_optional(arg)
    _arg_disallow_trailing(args)
    # List settings
    if list_settings:
        if config is None:
            print(no_conf_help)
        print('Settings:')
        for key in sorted(Config.settings):
            print(f'  {key} = {config[key] if config else ""}')
    # Get settings
    elif get_setting:
        if config is None:
            print(no_conf_help)
            error("can't get setting when there is no config")
        elif get_setting not in Config.settings:
            error(f'unknown setting: {get_setting}')
        else:
            print(f'{get_setting} = {config[get_setting]}')
    # Set settings
    elif set_setting:
        key, value = set_setting
        if key not in Config.settings:
            error(f'unknown setting: {key}')
        try:
            updated_config: Config
            if config is None:
                updated_config = Config(**{key: value})
            else:
                config[key] = value
                updated_config = config
        except InvalidConfigException as e:
            print(f'error in config value: {e!r}')
        else:
            print(f'{key} -> {value}')
            updated_config.save()
            print('Config saved')


help_info: CommandHelp = (
    'show info about an issue',
    '<id>',
    []
)


def cmd_info(config: Config, args: List[str]) -> None:
    # Args
    issue_id: IssueID
    # Parse args
    issue_id = _arg_issue_id(args, config)
    _arg_disallow_trailing(args)
    # Run command
    issue = Issue.load_from_id(issue_id)
    print(issue.info(config))


help_open: CommandHelp = (
    'open a new issue',
    '[-t <tag>...] [-b <id>...] <description>',
    [
        ('-t/--tags <tag>...', 'add tags to the issue'),
        ('-b/--blocked-by <id>...',
         'mark the new issue as blocked by other issues')
    ]
)


def cmd_open(config: Config, args: List[str]) -> None:
    # Args
    tags: Optional[Set[str]] = None
    blocked_by: Optional[Set[IssueID]] = None
    description: str

    # Parse args
    description = _arg_positional(args, 'description', position=-1)
    while args:
        arg = args.pop(0)
        _arg_disallow_positional(arg)
        if arg in {'-t', '--tags'}:
            tags = _arg_tags(args, '--tags')
        elif arg in {'-b', '--blocked-by'}:
            blocked_by = set()
            while args and not arg[0].startswith('-'):
                blocked_by.add(_arg_issue_id(args, config, specify_id=True))
        else:
            _arg_unknown_optional(arg)

    # Run command
    issues = load_issues(user=config.user)
    new_id_num = max(chain((i.id_.num for i in issues), [0]))
    now = datetime.utcnow()
    issue = Issue(id_=IssueID(num=new_id_num + 1, user=config.user),
                  created=now,
                  updated=now,
                  description=description,
                  tags=(tags or set()),
                  blocked_by=(blocked_by or set()),
                  comments=[],
                  status=IssueStatus.OPEN)
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


help_reopen: CommandHelp = (
    'reopen a closed issue',
    '<id>',
    []
)


def cmd_reopen(config: Config, args: List[str]) -> None:
    # Args
    issue_id: IssueID
    # Parse args
    issue_id = _arg_issue_id(args, config)
    # Run command
    _change_status(config.user, issue_id, IssueStatus.OPEN,
                   'open', 'reopened')


help_edit: CommandHelp = (
    'edit an issue',
    '<id> [-d <description>] [-t <tag>...] [-T <tag>...]',
    [
        ('-d/--description <description>', 'set the description'),
        ('-t/--add-tags <tag>...', 'add tags to the issue'),
        ('-T/--remove-tags <tag>...', 'remove tags from the issue')
    ]
)


def cmd_edit(config: Config, args: List[str]) -> None:
    # Args
    issue_id: IssueID
    description: Optional[str] = None
    add_tags: Optional[Set[str]] = None
    remove_tags: Optional[Set[str]] = None
    # Parse args
    issue_id = _arg_issue_id(args, config)
    while args:
        arg = args.pop(0)
        if not arg.startswith('-'):
            error(f'unknown positional argument: {arg}')
        elif arg in {'-d', '--description'}:
            try:
                description = args.pop(0)
            except IndexError:
                error('no description provided')
        elif arg in {'-t', '--add-tags'}:
            add_tags = _arg_tags(args, '--add-tags')
        elif arg in {'-T', '--remove-tags'}:
            remove_tags = _arg_tags(args, '--remove-tags')
        else:
            error(f'unknown argument: {arg}')
    # Run command
    issue = Issue.load_from_id(issue_id)
    changed = False
    if description and description != issue.description:
        issue = issue._replace(description=description)
        changed = True
    if add_tags and not add_tags.issubset(issue.tags):
        issue.tags.update(add_tags)
        changed = True
    if remove_tags and remove_tags.intersection(issue.tags):
        issue.tags.difference_update(remove_tags)
        changed = True
    if changed:
        issue.save()
        print('Issue edited')
    else:
        print('Nothing to update')


help_fixed: CommandHelp = (
    'close an issue and mark it as fixed',
    '<id> [<comment>]',
    []
)


def cmd_fixed(config: Config, args: List[str]) -> None:
    # Args
    issue_id: IssueID
    comment: Optional[str] = None
    # Parse args
    issue_id = _arg_issue_id(args, config)
    if args:
        comment = args.pop(0)
    _arg_disallow_trailing(args)
    # Run command
    _change_status(config.user, issue_id, IssueStatus.FIXED,
                   'marked as fixed', 'closed and marked as fixed',
                   comment_text=comment)


help_wontfix: CommandHelp = (
    'close an issue and mark it as not going to be fixed',
    '<id> [<comment>]',
    []
)


def cmd_wontfix(config: Config, args: List[str]) -> None:
    # Args
    issue_id: IssueID
    comment: Optional[str] = None
    # Parse args
    issue_id = _arg_issue_id(args, config)
    if args:
        comment = args.pop(0)
    _arg_disallow_trailing(args)
    # Run command
    _change_status(config.user, issue_id, IssueStatus.WONTFIX,
                   'marked as wontfix', 'closed and marked as wontfix',
                   comment_text=comment)


help_blocked_by: CommandHelp = (
    'mark an issue as being blocked by another issue from completion',
    '<blocked-id> <blocking-id>',
    []
)


def cmd_blocked_by(config: Config, args: List[str]) -> None:
    # Args
    blocked_id: IssueID
    blocking_id: IssueID

    # Parse args
    blocked_id = _arg_issue_id(args, config, restrict_to_own=True)
    blocking_id = _arg_issue_id(args, config)
    _arg_disallow_trailing(args)
    if blocked_id == blocking_id:
        error("an issue can't block itself")

    # Run command
    issue = Issue.load_from_id(blocked_id)
    if blocking_id in issue.blocked_by:
        print(f'Issue #{blocked_id.shorten(config)} is already '
              f'blocked by #{blocking_id.shorten(config)}')
    else:
        issue.blocked_by.add(blocking_id)
        issue.save()
        print(f'Issue #{blocked_id.shorten(config)} marked as '
              f'blocked by #{blocking_id.shorten(config)}')


help_unblock: CommandHelp = (
    'mark an issue as not being blocked by another issue from completion',
    '<blocked-id> <blocking-id>',
    []
)


def cmd_unblock(config: Config, args: List[str]) -> None:
    print('TODO')


help_comment: CommandHelp = (
    'add a comment to an issue',
    '<id> <message>',
    []
)


def cmd_comment(config: Config, args: List[str]) -> None:
    # Args
    issue_id: IssueID
    message: str

    # Parse args
    issue_id = _arg_issue_id(args, config)
    message = _arg_positional(args, 'message')
    _arg_disallow_trailing(args)

    # Run command
    comment = Comment(issue_id=issue_id,
                      user=config.user,
                      created=datetime.now(),
                      message=message)
    comment.save()
    print('Comment added')


help_list: CommandHelp = (
    'list all issues or ones matching certain filters',
    '[-s <status>] [-t <tag>...] [-T <tag>] [-Bbn]',
    [
        ('-s/--status <status>', 'only show issues with this status'),
        ('', f'(one of: {", ".join(s.value for s in IssueStatus)})'),
        ('-t/--tags <tag>...', 'only show issues with these tags'),
        ('-T/--without-tags <tag>...', 'only show issues without these tags'),
        ('-B/--blocking', 'only show issues blocking another issue'),
        ('-b/--blocked', 'only show issues blocked by other issues'),
        ('-n/--no-blocks', "don't show blocked or blocking issues")
    ]
)


def cmd_list(config: Config, args: List[str]) -> None:
    # Arguments
    status: Optional[IssueStatus] = None
    tags: Optional[Set[str]] = None
    without_tags: Optional[Set[str]] = None
    blocked = False
    blocking = False
    no_blocks = False

    # Parse the arguments
    while args:
        arg = args.pop(0)
        _arg_disallow_positional(arg)
        if arg in {'-s', '--status'}:
            try:
                raw_status = args.pop(0)
            except IndexError:
                error('--status needs an argument')
            else:
                try:
                    status = IssueStatus(raw_status)
                except ValueError:
                    error('invalid status: {raw_status}')
        elif arg in {'-t', '--tags'}:
            tags = _arg_tags(args, '--tags')
        elif arg in {'-T', '--without-tags'}:
            without_tags = _arg_tags(args, '--without-tags')
        elif arg in {'-b', '--blocked'}:
            blocked = True
        elif arg in {'-B', '--blocking'}:
            blocking = True
        elif arg in {'-n', '--no-blocks'}:
            no_blocks = True
        else:
            _arg_unknown_optional(arg)
    if no_blocks and (blocked or blocking):
        error('--blocked or --blocking can\'t be used with --no-blocks')

    # Run command
    all_issues = load_issues()
    issues: List[Issue] = []
    for issue in all_issues:
        blocking_issues = [i for i in all_issues
                           if i.id_ != issue.id_ and issue.id_ in i.blocked_by]
        if tags and not tags.issubset(issue.tags):
            continue
        if without_tags and without_tags.intersection(issue.tags):
            continue
        if blocking and not any(blocking_issues):
            continue
        if blocked and not issue.blocked_by:
            continue
        if no_blocks and (issue.blocked_by or any(blocking_issues)):
            continue
        if status:
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


help_log: CommandHelp = (
    'show a log of the latest actions (open/close/etc)',
    '',
    []
)


def cmd_log(config: Config, args: List[str]) -> None:
    print('TODO')


help_tag: CommandHelp = (
    'handle registered tags in this ishu project',
    '',
    []
)


def cmd_tag(config: Config, args: List[str]) -> None:
    print('TODO')


# == Command line parsing ==

def parse_commands_new() -> None:
    help_aliases = {'-h', '--help'}
    commands = {
        # Init
        'init': (None, cmd_init, help_init),
        # Configure
        'conf': ('cfg', cmd_configure, help_configure),
        # Show info
        'show': ('s', cmd_info, help_info),
        # Open issue
        'open': ('o', cmd_open, help_open),
        # Reopen issue
        'reopen': ('r', cmd_reopen, help_reopen),
        # Edit issue
        'edit': ('e', cmd_edit, help_edit),
        # Close and fix issue
        'fixed': ('f', cmd_fixed, help_fixed),
        # Close and mark an issue as wontfix
        'wontfix': ('w', cmd_wontfix, help_wontfix),
        # Mark an issue as blocked
        'blocked': ('b', cmd_blocked_by, help_blocked_by),
        # Mark an issue as not blocked
        'unblock': ('ub', cmd_unblock, help_unblock),
        # Add comment
        'comment': ('c', cmd_comment, help_comment),
        # List issues
        'list': ('ls', cmd_list, help_list),
        # Show action log
        'log': ('l', cmd_log, help_log),
        # Handle tags
        'tag': ('t', cmd_tag, help_tag),
    }
    sys_cmd = Path(sys.argv[0]).name
    show_help = False
    args = sys.argv[1:]
    if not args or len(args) == 1 and args[0] in help_aliases:
        print(f'Usage: {sys_cmd} [-h | --help] <command> [<arguments>]')
        print('\nCommands:')
        command_table = [
            ('  help', 'show help for a command')
        ]
        command_table.extend((f'  {cmd}, {abbr or ""}'.rstrip(', '), desc)
                             for cmd, (abbr, _, (desc, _, _))
                             in commands.items())
        print('\n'.join(format_table(command_table, column_spacing=2,
                                     wrap_columns={1})))
        return
    if args[0] in help_aliases.union({'help'}):
        show_help = True
        args.pop(0)
    abbrevs = {abbr: key for key, (abbr, *_) in commands.items() if abbr}
    cmd_text = args.pop(0)
    if cmd_text in abbrevs:
        cmd_text = abbrevs[cmd_text]
    if cmd_text not in commands:
        error(f'unknown command: {cmd_text}')
    else:
        _, func, (help_desc, help_usage, help_lines) = commands[cmd_text]
        if show_help or (args and args[0] in help_aliases):
            print(f'Usage: {sys_cmd} {cmd_text} {help_usage}'.rstrip())
            print()
            print('\n'.join(format_table([('Description:', help_desc)],
                                         column_spacing=1, wrap_columns={1})))
            if help_lines:
                print('\nOptions:')
                print('\n'.join(format_table((('  ' + arg, desc)
                                              for arg, desc in help_lines),
                                             column_spacing=3,
                                             wrap_columns={1})))
        else:
            try:
                config = Config.load()
            except (FileNotFoundError, IncompleteConfigException):
                if func != cmd_configure:
                    error('you need to set your username before using ishu! '
                          'Please use the conf command to set it.')
                else:
                    cmd_configure(None, args)
            else:
                func(config, args)


def main() -> None:
    parse_commands_new()


if __name__ == '__main__':
    main()
