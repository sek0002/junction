"""Increment the single release version without external dependencies."""
import argparse
from pathlib import Path
import re

VERSION_FILE = Path(__file__).resolve().parents[1] / 'app' / 'version.py'


def bump_version(part, path=VERSION_FILE):
    if part not in ('major', 'minor', 'patch'):
        raise ValueError('Choose major, minor or patch.')
    source = path.read_text(encoding='utf8')
    pattern = r'(?m)^VERSION = "(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"$'
    match = re.search(pattern, source)
    if match is None:
        raise ValueError('Expected one semantic VERSION in app/version.py.')
    numbers = [int(value) for value in match.groups()]
    index = ('major', 'minor', 'patch').index(part)
    numbers[index] += 1
    numbers[index + 1:] = [0] * (2 - index)
    version = '.'.join(map(str, numbers))
    path.write_text(source[:match.start()] + f'VERSION = "{version}"' + source[match.end():], encoding='utf8')
    return version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('part', choices=('patch', 'minor', 'major'))
    args = parser.parse_args()
    print(bump_version(args.part))


if __name__ == '__main__':
    main()
