#!/usr/bin/env python
"""Haven 앱 관리 명령 진입점. 작업 디렉터리는 이 파일이 있는 폴더다."""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
