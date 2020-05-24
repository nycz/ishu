#!/usr/bin/env python3
from collections import Counter
from datetime import datetime, timedelta, timezone
from itertools import chain
import json
from operator import itemgetter
import os
from typing import Any, Callable, Iterable, List, Optional, Set, Tuple

from dateutil.tz import gettz

from libwui import cli
from libwui.cli import (CommandDef, CommandHelp, error, format_table,
                        OptionHelp, parse_cmds)
from libwui.colors import CYAN, GREEN, RED, RESET, YELLOW

from .common import (Config, IncompleteConfigException,
                     InvalidConfigException, ROOT, ROOT_OVERRIDE, TAGS_PATH)
from .models import Comment, Issue, IssueID, IssueStatus, load_issues


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


# == Commands ==

help_init = CommandHelp(
    description='initialize an ishu directory',
    usage='',
    options=[]
)


def cmd_init(config: Config, args: List[str]) -> None:
    cli.arg_disallow_trailing(args)
    if ROOT.exists():
        print(f'There is already an ishu project in {ROOT}')
    else:
        ROOT.mkdir(exist_ok=True)
        print(f'Created ishu project in {ROOT}')


help_alias = CommandHelp(
    description='manage command aliases',
    usage='(-l | -g <alias> | -s <alias> <value> | -r <alias>)',
    options=[
        OptionHelp(spec='-l/--list',
                   description='list aliases'),
        OptionHelp(spec='-g/--get <alias>',
                   description='show the value of an alias'),
        OptionHelp(spec='-s/--set <alias> <value>',
                   description='set the value of an alias'),
        OptionHelp(spec='-r/--remove <alias>',
                   description='remove an alias'),
    ]
)


def cmd_alias(config: Config, args: List[str]) -> None:
    # Args
    list_aliases = False
    get_alias: Optional[str] = None
    set_alias: Optional[Tuple[str, str]] = None
    remove_alias: Optional[str] = None
    # Parse args
    if not args:
        list_aliases = True
    else:
        arg = args.pop(0)
        cli.arg_disallow_positional(arg)
        if arg in {'-l', '--list'}:
            list_aliases = True
        elif arg in {'-g', '--get'}:
            try:
                get_alias = args.pop(0)
            except IndexError:
                error('--get needs an argument')
        elif arg in {'-r', '--remove'}:
            try:
                remove_alias = args.pop(0)
            except IndexError:
                error('--remove needs an argument')
        elif arg in {'-s', '--set'}:
            try:
                set_alias = (args.pop(0), args.pop(0))
            except IndexError:
                error('--set needs two arguments')
        else:
            cli.arg_unknown_optional(arg)
    cli.arg_disallow_trailing(args)
    # List aliases
    if list_aliases:
        if config.aliases:
            print('Aliases:')
            for key, value in sorted(config.aliases.items()):
                print(f'  {key} = {value}')
        else:
            print('No aliases')
    # Get aliases
    elif get_alias:
        if get_alias not in config.aliases:
            error(f'unknown alias: {get_alias}')
        else:
            print(f'{get_alias} = {config.aliases[get_alias]}')
    # Remove alias
    elif remove_alias:
        if remove_alias not in config.aliases:
            error(f'unknown alias: {remove_alias}')
        else:
            del config.aliases[remove_alias]
            config.save()
            print(f'Alias {remove_alias} removed')
    # Set alias
    elif set_alias:
        key, value = set_alias
        is_new = key not in config.aliases
        config.aliases[key] = value
        print(f'{key} -> {value}')
        config.save()
        if is_new:
            print('Alias created')
        else:
            print('Alias updated')


help_configure = CommandHelp(
    description='view and edit settings',
    usage='(-l | -g <key> | -s <key> <value> )',
    options=[
        OptionHelp(spec='-l/--list',
                   description='list settings'),
        OptionHelp(spec='-g/--get <key>',
                   description='show the value of a setting'),
        OptionHelp(spec='-s/--set <key> <value>',
                   description='set the value of a setting')
    ]
)


def cmd_configure(config: Optional[Config], args: List[str]) -> None:
    no_conf_help = (f'{RED}No valid config found, '
                    f'please set your username{RESET}')
    # Args
    list_settings = False
    get_setting: Optional[str] = None
    set_setting: Optional[Tuple[str, str]] = None
    # Parse args
    if not args:
        list_settings = True
    else:
        arg = args.pop(0)
        cli.arg_disallow_positional(arg)
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
            cli.arg_unknown_optional(arg)
    cli.arg_disallow_trailing(args)
    # List settings
    if list_settings:
        if config is None:
            print(no_conf_help)
        print('Settings:')
        for key in sorted(Config.editable_settings):
            print(f'  {key} = {config[key] if config else ""}')
    # Get settings
    elif get_setting:
        if config is None:
            print(no_conf_help)
            error("can't get setting when there is no config")
        elif get_setting not in Config.editable_settings:
            error(f'unknown setting: {get_setting}')
        else:
            print(f'{get_setting} = {config[get_setting]}')
    # Set settings
    elif set_setting:
        key, value = set_setting
        if key not in Config.editable_settings:
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


help_info = CommandHelp(
    description='show info about an issue',
    usage='<id>',
    options=[]
)


def cmd_info(config: Config, args: List[str]) -> None:
    # Args
    issue_id: IssueID
    # Parse args
    issue_id = _arg_issue_id(args, config)
    cli.arg_disallow_trailing(args)
    # Run command
    issue = Issue.load_from_id(issue_id)
    print(issue.info(config))


help_open = CommandHelp(
    description='open a new issue',
    usage='[-t <tag>...] [-b <id>...] <description>',
    options=[
        OptionHelp(spec='-t/--tags <tag>...',
                   description='add tags to the issue'),
        OptionHelp(spec='-b/--blocked-by <id>...',
                   description='mark the new issue as blocked by other issues')
    ]
)


def cmd_open(config: Config, args: List[str]) -> None:
    # Args
    tags: Optional[Set[str]] = None
    blocked_by: Optional[Set[IssueID]] = None
    description: str

    # Parse args
    description = cli.arg_positional(args, 'description', position=-1)
    while args:
        arg = args.pop(0)
        cli.arg_disallow_positional(arg)
        if arg in {'-t', '--tags'}:
            tags = cli.arg_tags(args, '--tags')
        elif arg in {'-b', '--blocked-by'}:
            blocked_by = set()
            while args and not args[0].startswith('-'):
                blocked_by.add(_arg_issue_id(args, config, specify_id=True))
        else:
            cli.arg_unknown_optional(arg)

    # Run command
    issues = load_issues(user=config.user)
    new_id_num = max(chain((i.id_.num for i in issues), [0]))
    now = datetime.now(timezone.utc)
    issue = Issue(id_=IssueID(num=new_id_num + 1, user=config.user),
                  created=now,
                  updated=now,
                  description=description,
                  tags=(tags or set()),
                  blocked_by=(blocked_by or set()),
                  comments=[],
                  status=IssueStatus.OPEN,
                  log=[],
                  original_description=description,
                  original_tags=frozenset(tags or set()),
                  original_blocked_by=frozenset(blocked_by or set()),
                  original_status=IssueStatus.OPEN)
    issue.save()
    print(f'Issue #{issue.id_.num} opened')


help_edit = CommandHelp(
    description='edit an issue',
    usage='<id> [-d <description>] [-t <tag>...] [-T <tag>...]',
    options=[
        OptionHelp(spec='-d/--description <description>',
                   description='set the description'),
        OptionHelp(spec='-t/--add-tags <tag>...',
                   description='add tags to the issue'),
        OptionHelp(spec='-T/--remove-tags <tag>...',
                   description='remove tags from the issue')
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
            add_tags = cli.arg_tags(args, '--add-tags')
        elif arg in {'-T', '--remove-tags'}:
            remove_tags = cli.arg_tags(args, '--remove-tags')
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
            Comment(issue_id=issue_id, user=user,
                    created=datetime.now(timezone.utc),
                    message=comment_text).save()
        print(f'Issue {issue_id.num} {result_text}')


help_reopen = CommandHelp(
    description='reopen a closed issue',
    usage='<id>',
    options=[]
)


def cmd_reopen(config: Config, args: List[str]) -> None:
    # Args
    issue_id: IssueID
    # Parse args
    issue_id = _arg_issue_id(args, config)
    # Run command
    _change_status(config.user, issue_id, IssueStatus.OPEN,
                   'open', 'reopened')


help_fixed = CommandHelp(
    description='close an issue and mark it as fixed',
    usage='<id> [<comment>]',
    options=[]
)


def cmd_fixed(config: Config, args: List[str]) -> None:
    # Args
    issue_id: IssueID
    comment: Optional[str] = None
    # Parse args
    issue_id = _arg_issue_id(args, config)
    if args:
        comment = args.pop(0)
    cli.arg_disallow_trailing(args)
    # Run command
    _change_status(config.user, issue_id, IssueStatus.FIXED,
                   'marked as fixed', 'closed and marked as fixed',
                   comment_text=comment)


help_wontfix = CommandHelp(
    description='close an issue and mark it as not going to be fixed',
    usage='<id> [<comment>]',
    options=[]
)


def cmd_wontfix(config: Config, args: List[str]) -> None:
    # Args
    issue_id: IssueID
    comment: Optional[str] = None
    # Parse args
    issue_id = _arg_issue_id(args, config)
    if args:
        comment = args.pop(0)
    cli.arg_disallow_trailing(args)
    # Run command
    _change_status(config.user, issue_id, IssueStatus.WONTFIX,
                   'marked as wontfix', 'closed and marked as wontfix',
                   comment_text=comment)


help_blocked_by = CommandHelp(
    description='mark an issue as being blocked '
                'by another issue from completion',
    usage='<blocked-id> <blocking-id>',
    options=[]
)


def cmd_blocked_by(config: Config, args: List[str]) -> None:
    # Args
    blocked_id: IssueID
    blocking_id: IssueID

    # Parse args
    blocked_id = _arg_issue_id(args, config, restrict_to_own=True)
    blocking_id = _arg_issue_id(args, config)
    cli.arg_disallow_trailing(args)
    if blocked_id == blocking_id:
        error("an issue can't block itself")

    # Run command
    issue = Issue.load_from_id(blocked_id)
    other_issue = Issue.load_from_id(blocking_id)
    s_blocked_id = f'#{blocked_id.shorten(config)}'
    s_blocking_id = f'#{blocking_id.shorten(config)}'
    if blocking_id in issue.blocked_by:
        print(f'Issue {s_blocked_id} is already blocked by {s_blocking_id}, '
              f'no changes were made.')
    elif blocked_id in other_issue.blocked_by:
        error(f'blocking loop detected! Issue {s_blocking_id} is already '
              f'blocked by {s_blocked_id}!')
    else:
        issue.blocked_by.add(blocking_id)
        issue.save()
        print(f'Issue {s_blocked_id} marked as blocked by {s_blocking_id}.')


help_unblock = CommandHelp(
    description='mark an issue as not being blocked '
                'by another issue from completion',
    usage='<blocked-id> <blocking-id>',
    options=[]
)


def cmd_unblock(config: Config, args: List[str]) -> None:
    # Args
    blocked_id: IssueID
    blocking_id: IssueID

    # Parse args
    blocked_id = _arg_issue_id(args, config, restrict_to_own=True)
    blocking_id = _arg_issue_id(args, config)
    cli.arg_disallow_trailing(args)
    if blocked_id == blocking_id:
        error("an issue can't block itself")

    # Run command
    issue = Issue.load_from_id(blocked_id)
    s_blocked_id = f'#{blocked_id.shorten(config)}'
    s_blocking_id = f'#{blocking_id.shorten(config)}'
    if blocking_id not in issue.blocked_by:
        print(f'Issue {s_blocked_id} is not blocked by {s_blocking_id}, '
              f'no changes were made.')
    else:
        issue.blocked_by.remove(blocking_id)
        issue.save()
        print(f'Issue #{blocked_id.shorten(config)} no longer marked as '
              f'blocked by #{blocking_id.shorten(config)}.')


help_comment = CommandHelp(
    description='add a comment to an issue',
    usage='<id> <message>',
    options=[]
)


def cmd_comment(config: Config, args: List[str]) -> None:
    # Args
    issue_id: IssueID
    message: str

    # Parse args
    issue_id = _arg_issue_id(args, config)
    message = cli.arg_positional(args, 'message')
    cli.arg_disallow_trailing(args)

    # Run command
    comment = Comment(issue_id=issue_id,
                      user=config.user,
                      created=datetime.now(timezone.utc),
                      message=message)
    comment.save()
    print('Comment added')


help_list = CommandHelp(
    description='list all issues or ones matching certain filters',
    usage='[-s <status>] [-t <tag>...] [-T <tag>] [-BbnID]',
    options=[
        OptionHelp(spec='-s/--status <status>',
                   description='only show issues with this status'),
        OptionHelp(
            spec='',
            description=f'(one of: {", ".join(s.value for s in IssueStatus)})'
        ),
        OptionHelp(spec='-t/--tags <tag>...',
                   description='only show issues with these tags'),
        OptionHelp(spec='-T/--without-tags <tag>...',
                   description='only show issues without these tags'),
        OptionHelp(spec='-B/--blocking',
                   description='only show issues blocking another issue'),
        OptionHelp(spec='-b/--blocked',
                   description='only show issues blocked by other issues'),
        OptionHelp(spec='-n/--no-blocks',
                   description="don't show blocked or blocking issues"),
        OptionHelp(spec='-I/--no-icons',
                   description="don't show any special icons "
                               "(also set with ISHU_NO_ICONS envvar)"),
        OptionHelp(spec='-D/--no-dates',
                   description="don't show the date columns"),
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
    show_icons = not bool(os.environ.get('ISHU_NO_ICONS'))
    show_dates = True

    # Parse the arguments
    while args:
        arg = args.pop(0)
        cli.arg_disallow_positional(arg)
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
            tags = cli.arg_tags(args, '--tags')
        elif arg in {'-T', '--without-tags'}:
            without_tags = cli.arg_tags(args, '--without-tags')
        elif arg in {'-b', '--blocked'}:
            blocked = True
        elif arg in {'-B', '--blocking'}:
            blocking = True
        elif arg in {'-n', '--no-blocks'}:
            no_blocks = True
        elif arg in {'-I', '--no-icons'}:
            show_icons = False
        elif arg in {'-D', '--no-dates'}:
            show_dates = False
        else:
            cli.arg_unknown_optional(arg)
    if no_blocks and (blocked or blocking):
        error('--blocked or --blocking can\'t be used with --no-blocks')

    # Run command
    all_issues = load_issues()
    issues: List[Issue] = []
    is_blocking = set()
    for issue in all_issues:
        # Only see issues as blocking if they are open
        if issue.status == IssueStatus.OPEN:
            blocking_issues = [i for i in all_issues
                               if i.id_ != issue.id_ and issue.id_ in i.blocked_by]
        else:
            blocking_issues = []
        if blocking_issues:
            is_blocking.add(issue.id_)
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

    date_fmt = '%Y-%m-%d'
    time_fmt = '%H:%M'
    datetime_fmt = f'{date_fmt} {time_fmt}'
    one_day_ago = datetime.now(timezone.utc) - timedelta(days=1)

    def _date_or_time_fmt(dt: datetime) -> str:
        return dt.strftime(time_fmt if dt > one_day_ago else date_fmt)

    status_icon = {
        IssueStatus.FIXED: GREEN + ('' if show_icons else 'F'),
        IssueStatus.OPEN: CYAN + ('' if show_icons else ' '),
        IssueStatus.CLOSED: GREEN + ('' if show_icons else 'C'),
        IssueStatus.WONTFIX: RED + ('' if show_icons else 'W'),
    }

    tz = gettz()

    def cull_empty(items: Iterable[Optional[str]]) -> Iterable[str]:
        for item in items:
            if item is not None:
                yield item

    def generate_row(i: Issue, short: bool = False) -> Tuple[str, ...]:
        status = status_icon[i.status] + RESET
        blocks = (('b' if i.blocked_by else '')
                  + ('B' if i.id_ in is_blocking else ''))
        comments = str(len(i.comments))
        tags = ', '.join(f'#{tag}' for tag in sorted(i.tags))
        row: List[Optional[str]]
        if short:
            created = _date_or_time_fmt(i.created.astimezone(tz))
            updated = (_date_or_time_fmt(i.updated.astimezone(tz))
                       if i.updated > i.created else '')
            row = [
                i.id_.shorten(None),
                status,
                blocks,
                created if show_dates else None,
                updated if show_dates else None,
                comments,
                tags,
                i.description,
            ]
        else:
            created = i.created.astimezone(tz).strftime(datetime_fmt)
            updated = (i.updated.astimezone(tz).strftime(datetime_fmt)
                       if i.updated > i.created else '')
            row = [
                str(i.id_.num),
                i.id_.user,
                status,
                blocks,
                created if show_dates else None,
                updated if show_dates else None,
                comments,
                tags,
                i.description,
            ]
        return tuple(cull_empty(row))

    titles = tuple(cull_empty([
        'ID', 'User', 'S', (' ' if show_icons else 'Blocks'),
        ('Created' if show_dates else None),
        ('Updated' if show_dates else None),
        (' ' if show_icons else 'Comments'),
        'Tags', 'Description'
    ]))
    table = [generate_row(i) for i in sorted(issues, key=lambda x: x.id_.num)]
    try:
        for line in format_table(table, wrap_columns={-1, -2}, titles=titles,
                                 require_min_widths=frozenset({(-1, 30)})):
            print(line)
    except cli.TooNarrowColumn:
        shorter_titles = tuple(cull_empty([
            'ID', 'S', (' ' if show_icons else 'Blocks'),
            ('Created' if show_dates else None),
            ('Updated' if show_dates else None),
            (' ' if show_icons else 'Cmnt'), 'Tags',
            'Description'
        ]))
        shorter_table = [generate_row(i, short=True) for i in issues]
        for line in format_table(shorter_table, wrap_columns={-1, -2},
                                 titles=shorter_titles):
            print(line)


help_log = CommandHelp(
    description='show a log of the latest actions (open/close/etc)',
    usage='',
    options=[]
)


def cmd_log(config: Config, args: List[str]) -> None:
    print('TODO')


help_tag = CommandHelp(
    description='handle registered tags in this ishu project',
    usage='(-l [-u]| -a <tag>... | -r <tag>... | -e <oldtag> <newtag>)',
    options=[
        OptionHelp(spec='-l/--list',
                   description='list registered tags'),
        OptionHelp(spec='-u/--usage',
                   description='sort tag list by usage'),
        OptionHelp(spec='-a/--add <tag>...',
                   description='register new tags'),
        OptionHelp(spec='-r/--remove <tag>...',
                   description='unregister and remove tags from all issues'),
        OptionHelp(spec='-e/--edit <oldtag> <newtag>',
                   description='rename a tag both in the registry '
                               'and in all issues using it')
    ]
)


def cmd_tag(config: Config, args: List[str]) -> None:
    # Args
    list_tags = False
    sort_by_usage = False
    add_tags: Optional[Set[str]] = None
    remove_tags: Optional[Set[str]] = None
    edit_tag: Optional[Tuple[str, str]] = None

    # Parse args
    if not args:
        list_tags = True
    else:
        arg = args.pop(0)
        cli.arg_disallow_positional(arg)
        if arg == '-lu':
            list_tags = True
            sort_by_usage = True
        elif arg in {'-l', '--list'}:
            list_tags = True
            if args and args[0] in {'-u', '--usage'}:
                args.pop(0)
                sort_by_usage = True
        elif arg in {'-a', '--add'}:
            add_tags = cli.arg_tags(args, '--add')
        elif arg in {'-r', '--remove'}:
            remove_tags = cli.arg_tags(args, '--remove')
        elif arg in {'-e', '--edit'}:
            edit_tag = (cli.arg_positional(args, 'old tag'),
                        cli.arg_positional(args, 'new tag'))
        else:
            cli.arg_unknown_optional(arg)
    cli.arg_disallow_trailing(args)

    # Run command
    tag_registry: Set[str]
    if not TAGS_PATH.exists():
        TAGS_PATH.write_text('[]')
        tag_registry = set()
    else:
        tag_registry = set(json.loads(TAGS_PATH.read_text()))
    old_tag_registry = frozenset(tag_registry)
    issues = load_issues()
    if list_tags:
        issue_tags = Counter(t for issue in issues for t in issue.tags)
        issue_tags.update({t: 0 for t in tag_registry if t not in issue_tags})
        tag_list = [(name, str(count))
                    for name, count in sorted(sorted(issue_tags.most_common()),
                                              key=itemgetter(1), reverse=True)]
        if not sort_by_usage:
            tag_list.sort()
        unregistered_lines = {n: (RED, RESET)
                              for n, (name, _) in enumerate(tag_list)
                              if name not in tag_registry}
        if tag_list:
            print('\n'.join(format_table(tag_list,
                                         titles=('Tag name', 'Use count'),
                                         surround_rows=unregistered_lines)))
        unregistered_tags = set(issue_tags.keys()) - tag_registry
        if unregistered_tags:
            print(f'\n{RED}{len(unregistered_tags)} '
                  f'unregistered tags!{RESET}')
    elif add_tags:
        existing_tags = add_tags.intersection(tag_registry)
        new_tags = add_tags - tag_registry
        if existing_tags:
            print('Existing tags that weren\'t added:',
                  ', '.join(sorted(existing_tags)))
        if new_tags:
            print('Added tags:', ', '.join(sorted(new_tags)))
            tag_registry.update(add_tags)
    elif remove_tags:
        matched_tags = remove_tags.intersection(tag_registry)
        unknown_tags = remove_tags - tag_registry
        # TODO: remove/add unregistered tags?
        if unknown_tags:
            print('Unknown tags that weren\'t removed:',
                  ', '.join(sorted(unknown_tags)))
        if matched_tags:
            print('Tags to remove:', ', '.join(sorted(matched_tags)))
            for tag in matched_tags:
                matched_issues = [i for i in issues if tag in i.tags]
                if matched_issues:
                    response = input(f'Tag {tag!r} is used in '
                                     f'{len(matched_issues)} issues. '
                                     f'Remove it from all of them? [y/N] ')
                    if response.lower() not in {'y', 'yes'}:
                        print('Aborted tag removal, nothing was changed.')
                        break
            else:
                tag_registry.difference_update(matched_tags)
                count = 0
                for issue in issues:
                    if matched_tags.intersection(issue.tags):
                        issue.tags.difference_update(matched_tags)
                        issue.save()
                        count += 1
                print(f'Tags removed, {count} issues were modified.')
    elif edit_tag:
        old_name, new_name = edit_tag
        if old_name == new_name:
            error('old name and new name are identical')
        if old_name not in tag_registry:
            error(f'unknown tag: {old_name}')
        if new_name in tag_registry:
            error(f'new tag already exist: {new_name}')
        matched_issues = [i for i in issues if old_name in i.tags]
        if matched_issues:
            response = input(f'Tag {old_name!r} is used in '
                             f'{len(matched_issues)} issues. '
                             f'Rename it to {new_name!r} '
                             f'in all of them? [y/N] ')
            if response.lower() not in {'y', 'yes'}:
                print('Aborted tag edit, nothing was changed.')
                return
            else:
                for issue in matched_issues:
                    issue.tags.remove(old_name)
                    issue.tags.add(new_name)
                    issue.save()
        tag_registry.remove(old_name)
        tag_registry.add(new_name)
        print(f'Tag {old_name!r} renamed to {new_name!r}.')
        if matched_issues:
            print(f'{len(matched_issues)} issues were modified.')
    # Save changes if needed
    if tag_registry != old_tag_registry:
        TAGS_PATH.write_text(json.dumps(sorted(tag_registry), indent=2))


# == Command line parsing ==

def main() -> None:
    if ROOT_OVERRIDE:
        print(f'{YELLOW}[Using root: {ROOT}]{RESET}\n')
    commands = {
        # Init
        'init': CommandDef([], cmd_init, help_init),
        # Configure
        'conf': CommandDef(['cfg'], cmd_configure, help_configure),
        # Manage aliases
        'alias': CommandDef(['a'], cmd_alias, help_alias),
        # Show info
        'show': CommandDef(['s'], cmd_info, help_info),
        # Open issue
        'open': CommandDef(['o'], cmd_open, help_open),
        # Reopen issue
        'reopen': CommandDef(['r'], cmd_reopen, help_reopen),
        # Edit issue
        'edit': CommandDef(['e'], cmd_edit, help_edit),
        # Close and fix issue
        'fixed': CommandDef(['f'], cmd_fixed, help_fixed),
        # Close and mark an issue as wontfix
        'wontfix': CommandDef(['w'], cmd_wontfix, help_wontfix),
        # Mark an issue as blocked
        'blocked': CommandDef(['b'], cmd_blocked_by, help_blocked_by),
        # Mark an issue as not blocked
        'unblock': CommandDef(['ub'], cmd_unblock, help_unblock),
        # Add comment
        'comment': CommandDef(['c'], cmd_comment, help_comment),
        # List issues
        'list': CommandDef(['ls'], cmd_list, help_list),
        # Show action log
        'log': CommandDef(['l'], cmd_log, help_log),
        # Handle tags
        'tag': CommandDef(['t'], cmd_tag, help_tag),
    }
    config: Optional[Config]
    try:
        config = Config.load()
    except (FileNotFoundError, IncompleteConfigException):
        config = None

    def callback(func: Callable[[Any, List[str]], None],
                 args: List[str]) -> None:
        if config is None:
            if func != cmd_configure:
                error('you need to set your username before using ishu! '
                      'Please use the conf command to set it.')
            else:
                cmd_configure(None, args)
        else:
            if not ROOT.exists() and func != cmd_init:
                error('no .ishu directory found! '
                      'Please run the init command first.')
            else:
                func(config, args)

    aliases = config.aliases if config is not None else {}
    parse_cmds(commands, callback, aliases)


if __name__ == '__main__':
    main()
