#!/bin/bash
# Drive a running Flowline (launched with --debug-control): banner | menu | review | approve | withdraw | done | settings | poll | do-it | not-now | stop | redraft | hide-notch
printf '%s' "$1" > "$HOME/Library/Application Support/Flowline/debug-command"
