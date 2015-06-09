#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2015 Mehdi Yousfi-Monod <mehdi.yousfi@gmail.com>
#
# This file is part of BIO (Morrowind Objective Module Install Order).
#
#    BIO is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    BIO is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with BIO.  If not, see <http://www.gnu.org/licenses/>.

import os
import re
import ConfigParser

__all__ = ["ModConfig", "ModConfigError"]


class ModConfigError(Exception):
    def __init__(self, msg):
        self.msg = msg


class ModConfig(object):

    """ Configuration of the analysis.
    Extract configuration from an 'ini' file and store
    paths to directories and file names.
    """

    path = {}
    tool = {}
    precedence = {}
    coefficient = {}
    size_coeff = None
    mtime_coeff = None
    fc_coeff = None

    def __init__(self, ini_file):
        cfg = ConfigParser.ConfigParser()
        cfg.readfp(open(ini_file))
        try:
            self.set_paths(cfg)
            self.set_force_precedence(cfg)
            self.set_criterion_coeffs(cfg)
            self.set_mod_coeffs(cfg)
        except ConfigParser.NoOptionError as msg:
            raise ModConfigError(
                    'An entry is missing in the configuration file:\n%s\t' %
                    str(msg))

        self.log_fd = open('%s' % self.path['log'], 'a')
        self.log_fd.write("\n")

    def log(self, msg, display=True):
        self.log_fd.write("%s\n" % msg)
        if display:
            print msg

    def clean_mod_name(self, mod):
        base_name = os.path.basename(mod)
        # If the module already has a prefix, then remove it
        return re.sub("^\d+[ -_]", "", base_name)

    def is_greater(self, mod1, mod2):
        """ Return -1 is mod2 > mod1; 1 if mod1 > mod2; 0 if unknown. """
        mod_name1 = os.path.basename(mod1).lower()
        mod_name2 = os.path.basename(mod2).lower()
        if (mod_name2 in self.precedence and
                mod_name1 in self.precedence[mod_name2]):
            return -1
        elif (mod_name1 in self.precedence and
                mod_name2 in self.precedence[mod_name1]):
            return 1
        else:
            return 0

    def set_force_precedence(self, cfg):
        for mod1, mod2 in cfg.items('mod_precedences'):
            mod1 = mod1.lower()
            mod2 = mod2.lower()
            if mod1 not in self.precedence:
                self.precedence[mod1] = []
            self.precedence[mod1].append(mod2)

    def set_criterion_coeffs(self, cfg):
        try:
            self.size_coeff = float(
                    cfg.get('criterion_coefficients', 'size_coeff'))
            self.mtime_coeff = float(
                    cfg.get('criterion_coefficients', 'mtime_coeff'))
            self.fc_coeff = float(
                    cfg.get('criterion_coefficients', 'file_count_coeff'))
        except ValueError as msg:
            raise ModConfigError(
                    "Invalid criterion coefficient value:\n%s\t" % str(msg))
        if (self.size_coeff < 0.0 or self.mtime_coeff < 0.0 or
                self.fc_coeff < 0.0):
            raise ModConfigError(
                    "Criterion coefficients cannot be lower than '0'.")

    def get_mod_coeff(self, mod):
        mod_name = os.path.basename(mod).lower()
        if mod_name in self.coefficient:
            return self.coefficient[mod_name]
        else:
            return 1

    def set_mod_coeffs(self, cfg):
        for mod, coeff in cfg.items('mod_coefficients'):
            mod = mod.lower()
            try:
                coeff = float(coeff)
            except ValueError:
                raise ModConfigError("Invalid mod coefficient value: '%s'" %
                        coeff)
            if coeff == 0.0:
                raise ModConfigError("Mod coefficients cannot be '0'.")
            self.coefficient[mod] = coeff

    def set_paths(self, cfg):
        def _path(path):
            return os.path.abspath(os.path.expanduser(path))
        def _dir(path):
            return '%s%s' % (_path(path), os.sep)
        def dir_read_test(key):
            if not os.access(self.path[key], os.R_OK):
                raise ModConfigError("'%s' is not readable." % self.path[key])
        def dir_write_test(key, create = False):
            if not os.access(self.path[key], os.W_OK):
                if create:
                    try:
                        os.mkdir(self.path[key])
                    except OSError:
                        raise ModConfigError(
                                "Cannot create directory '%s'." % self.path[key])
                else:
                    raise ModConfigError("'%s' is not writable." % self.path[key])
        def file_write_test(key):
            if (os.access(self.path[key], os.F_OK) and
                not os.access(self.path[key], os.W_OK)):
                raise ModConfigError("'%s' is not writable." % self.path[key])

        def get_list(vals):
            return set([val.lower() for val in re.split('[,\s]+', vals)])

        def set_tools(key, optional=False):
            def which(program):
                def is_exe(fpath):
                    return os.path.exists(fpath) and os.access(fpath, os.X_OK)

                if is_exe(program):
                    return program
                else:
                    for path in os.environ["PATH"].split(os.pathsep):
                        exe_file = os.path.join(path, program)
                        if is_exe(exe_file):
                            return exe_file

                return None

            path = ''
            try:
                path = cfg.get('tools', key)
            except ConfigParser.NoOptionError:
                if not optional:
                    raise
            if not path and optional:
                return
            path_tool = which(path)
            if not path_tool:
                raise ModConfigError("Program %s not found." % path)
            self.path[key] = path_tool

        def set_filename(key):
            self.path[key] = _path(cfg.get('analysis', key))
            file_write_test(key)

        # The installers directory is mandatory.
        self.path['tgt_dir'] = _dir(cfg.get('modules', 'target_directory'))
        dir_write_test('tgt_dir')

        # The external directory is optional.
        src_dir = ""
        try:
            src_dir = cfg.get('modules', 'source_directory')
        except ConfigParser.NoOptionError:
            pass
        if src_dir:
            self.path['src_dir'] = _dir(src_dir)
            dir_read_test('src_dir')
        else:
            self.path['src_dir'] = self.path['tgt_dir']

        self.rename = (self.path['tgt_dir'] == self.path['src_dir'])

        self.path['expected_exts'] = get_list(
            cfg.get('modules','expected_datafiles_extensions'))
        self.path['excluded_dirs'] = get_list(
            cfg.get('modules','excluded_directory_analysis'))
        self.path['excluded_arc_dirs'] = get_list(
            cfg.get('modules','excluded_archive_directory_analysis'))

        set_tools('archive')
        set_tools('dot', True)

        self.path['out_dir'] = _dir(cfg.get('analysis', 'output_dir'))
        dir_write_test('out_dir', True)

        set_filename('disk_operations')
        set_filename('log')

        set_filename('suspicious')
        set_filename('overlaps')

