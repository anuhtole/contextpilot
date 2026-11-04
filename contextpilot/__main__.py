"""python -m contextpilot recommend [options]"""
import sys

from contextpilot import recommend

COMMANDS = {"recommend": recommend.main}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit(f"usage: python -m contextpilot {{{','.join(COMMANDS)}}} [options]")
    COMMANDS[sys.argv[1]](sys.argv[2:])
