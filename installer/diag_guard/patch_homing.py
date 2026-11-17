#!/usr/bin/env python3
# Copyright (C) 2026 Malevich community contributors, GPLv3+
"""Apply tightly anchored, fail-closed DIAG hooks to an unmodified homing.py."""
import ast

MARKER = '# MALEVICH_DIAG_GUARD_V020'


def patch_homing(original):
    if MARKER in original:
        return original
    if 'diag_guard' in original.lower() or 'XL DIAG GUARD' in original:
        raise ValueError('homing.py already has another DIAG Guard patch. '
                         'Remove the existing patch before installing this release.')

    changes = [
        (
            '        self.printer.send_event("homing:homing_move_begin", self)\n',
            '        self.printer.send_event("homing:homing_move_begin", self)\n'
            '        ' + MARKER + '\n'
            '        diag_guard = self.printer.lookup_object(' 
            '"malevich_diag_guard", None)\n'
            '        if diag_guard is not None:\n'
            '            try:\n'
            '                diag_guard.before_homing_move(self)\n'
            '            except self.printer.command_error:\n'
            '                # Restore StallGuard fields on an aborted preflight.\n'
            '                self.printer.send_event("homing:homing_move_end", self)\n'
            '                raise\n'),
        (
            '            wait = mcu_endstop.home_start(print_time, ENDSTOP_SAMPLE_TIME,\n'
            '                                          ENDSTOP_SAMPLE_COUNT, rest_time,\n',
            '            sample_time, sample_count = (ENDSTOP_SAMPLE_TIME,\n'
            '                                         ENDSTOP_SAMPLE_COUNT)\n'
            '            if diag_guard is not None:\n'
            '                sample_time, sample_count = diag_guard.sample_parameters(\n'
            '                    self, sample_time, sample_count)\n'
            '            wait = mcu_endstop.home_start(print_time, sample_time,\n'
            '                                          sample_count, rest_time,\n'),
        (
            '            self.printer.send_event("homing:homing_move_end", self)\n'
            '        except self.printer.command_error as e:\n',
            '            self.printer.send_event("homing:homing_move_end", self)\n'
            '            if diag_guard is not None:\n'
            '                diag_guard.after_homing_move(self)\n'
            '        except self.printer.command_error as e:\n'),
    ]
    output = original
    for old, new in changes:
        count = output.count(old)
        if count != 1:
            raise ValueError('Unrecognized Klipper homing.py structure '
                             '(expected one anchor, found %d). No changes '
                             'were made.' % count)
        output = output.replace(old, new, 1)
    ast.parse(output, filename='homing.py')
    return output
