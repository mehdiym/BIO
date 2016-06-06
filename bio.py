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

""" """

__all__ = ["ModAnalysisError", "start"]

import os
import shutil
import subprocess
import shlex
import time

from mod_graph import ModGraph, ModGraphError
from mod_config import ModConfig, ModConfigError

# Configuration file name
ini_file = "%s.ini" % os.path.splitext(__file__)[0]
# Archive compression types supported by 7z
supported_archive_extensions = ['.7z', '.zip', '.rar']

def start():
    """ """
    mod_a = ModAnalysis()
    mod_a.mod_analysis()


class ModAnalysisError(Exception):
    def __init__(self, msg):
        self.msg = msg


class ModAnalysis(object):

    """ Analyses a list of Morrowind archive modules and
    produces an ordered installation list.
    """

    def __init__(self):
        self.mod_list = []
        self.datafile_list = {}
        self.overlapping_datafiles = {}
        self.free_mod = []
        self.suspicious_files = {}
        self.mod_graph = None
        self.ordered_overlap_mod = []
        self.disk_operations = []
        self.overwritten_mods = []
        self.cfg = None

    def traverse_archives(self, _dir):
        """ Traverses directories and applies f on files. """
        self.walk(_dir, self.process_archive)

    def walk(self, _dir, fun):
        _dir = os.path.abspath(_dir)
        for _file in os.listdir(_dir):
            nfile = os.path.join(_dir, _file)
            root, ext = os.path.splitext(_file)
            if ext.lower() in supported_archive_extensions:
                fun(nfile)
            # Traverse through subdirectories only if there is an
            # external directory for mods, ie. only if in copy mode.
            elif os.path.isdir(nfile) and not self.cfg.rename:
                if _file.lower() not in self.cfg.path['excluded_dirs']:
                    self.walk(nfile, fun)

    def process_archive(self, arcfile):
        """ Extracts path, size and hash properties
        of each file of an archive. """
        def get_next_field(arcout, field, err):
            """ Returns the next field named 'field' from an input stream. """
            while 1:
                line = arcout.readline()
                if not line:
                    if err:
                        raise ModAnalysisError("Field '%s' not found." % field)
                    else:
                        return ''
                if line.startswith('%s = ' % field):
                    return line[len(field) + 3:].rstrip()

        arcfile_node = arcfile[len(self.cfg.path['src_dir']):]
        self.mod_list.append(arcfile_node)

        arccmd = '%s l -slt "%s"' % (self.cfg.path['archive'], arcfile)
        arcargs = shlex.split(arccmd)
        arcproc = subprocess.Popen(arcargs, stdout=subprocess.PIPE)
        arcout = arcproc.stdout
        count = tsize = 0

        for i in range(0, 16):
            headers = arcout.readline()
            if not headers:
                raise ModAnalysisError("Archive headers of file '%s' ended"\
                        " prematurely." % arcfile)
        while 1:
            filename = get_next_field(arcout, "Path", False).lower()
            if not filename:
                self.mod_graph.add_node(arcfile_node, count, tsize)
                return
            if filename.startswith("datafiles" + os.sep):
                filename = filename[10:]
            size = get_next_field(arcout, "Size", True)
            if size == '0':
                continue
            mtime = get_next_field(arcout, "Modified", True)
            tsize += int(size)
            fhash = get_next_field(arcout, "CRC", True)
            if self.add_file(filename, size, mtime, fhash, arcfile_node):
                count +=1

    def add_file(self, datafile, size, mtime, fhash, mod):
        """ Adds a data file to the dictionary.
        Values are dictionaries: hash -> (size, archive file name) """
        first_mod_dir = datafile.partition(os.sep)[0]
        if first_mod_dir in self.cfg.path['excluded_arc_dirs']:
            return False

        if datafile not in self.datafile_list:
            self.datafile_list[datafile] = {}
        versions = self.datafile_list[datafile]
        if fhash not in versions:
            versions[fhash] = (mod, int(size), mtime)

        extension = os.path.splitext(datafile)[1][1:]
        if extension.lower() not in self.cfg.path['expected_exts']:
            if mod not in self.suspicious_files:
                self.suspicious_files[mod] = []
            self.suspicious_files[mod].append(datafile)

        return True

    def overlapping_datafiles_to_graph(self):
        """ Organizes overlapping archive data files into
        a graph of overlapping mods. """
        for datafile in self.overlapping_datafiles:
            file_props = self.overlapping_datafiles[datafile]
            for version in file_props:
                mod1 = file_props[version][0]
                for other_version in file_props:
                    mod2 = file_props[other_version][0]
                    if mod1 != mod2:
                        self.mod_graph.add_edge_datafile(
                                mod1,
                                mod2,
                                datafile,
                                (file_props[version][1],
                                    file_props[other_version][1]),
                                (file_props[version][2],
                                    file_props[other_version][2])
                                )
        self.mod_graph.del_isolated_nodes()

    def set_overlapping_datafiles(self):
        """ Filters data files and keep those
        which overlap with another archive. """
        self.overlapping_datafiles = dict(
            (k,v)
            for k,v in self.datafile_list.items() if len(v) > 1)

    def set_free_mod(self):
        """ Calculates the list of non overlapping archives. """
        self.free_mod = [mod for mod in self.mod_list
                         if mod not in self.ordered_overlap_mod]

    def prepare_disk_operations(self):
        for mod in sorted(self.free_mod):
            clean_name = self.cfg.clean_mod_num_prefix(mod)
            new_name = clean_name
            old_name = mod
            if not self.cfg.rename or old_name != new_name:
                self.disk_operations.append((old_name, new_name))

        for i, mod in enumerate(self.ordered_overlap_mod):
            clean_name = self.cfg.clean_mod_num_prefix(mod)
            new_name = "%03d0-%s" % (
                    i + 1,
                    clean_name)
            old_name = mod
            if self.cfg.rename and old_name == new_name:
                self.cfg.log("No renaming needed for mod: %s" % old_name, False)
            else:
                self.disk_operations.append((old_name, new_name))

        self.cfg.log("Now dealing with non overlapping mods.", False)

        tgt_dir = self.cfg.path['tgt_dir']
        for old_name, new_name in self.disk_operations:
            tgt = "%s%s" % (tgt_dir, new_name)
            if os.path.exists(tgt):
                self.overwritten_mods.append(tgt)

    def write_info_files(self):
        if self.suspicious_files:
            with open('%s' % self.cfg.path['suspicious'],
                    'w') as suspicious:
                for mod in sorted(self.suspicious_files.iterkeys()):
                    buff = ['%s :\n' % mod]
                    for datafile in self.suspicious_files[mod]:
                        buff.append('\t%s\n' % datafile)
                        suspicious.write(''.join(buff))

        with open('%s' % self.cfg.path['disk_operations'],
                'w') as disk_operations:
            buff = ['']
            tgt_dir = self.cfg.path['tgt_dir']
            src_dir = self.cfg.path['src_dir']

            if len(self.overwritten_mods) > 0:
                if self.cfg.rename:
                    buff.append('ERROR: The following mod archives will be '\
                            'lost during the process:\n\n')
                else:
                    buff.append('WARNING: The following mod archives will be '\
                            'overwritten during the process:\n\n')
                for file_path in self.overwritten_mods:
                    buff.append('%s\n' % file_path)
                buff.append("\n")

            buff.append('Your mod archives will be ')
            t = " " * 4
            if self.cfg.rename:
                buff.append('renamed ')
            else:
                buff.append('copied from\n%s%s%s\nto\n%s%s\n'
                        % (t, src_dir, t, t, tgt_dir))
            buff.append('as follow:\n\n')

            for old_name, new_name in self.disk_operations:
                buff.append('%s%s->%s%s\n' % (old_name, t, t, new_name))

            disk_operations.write(''.join(buff))

        self.mod_graph.write_graph_files(self.cfg.path['overlaps'])

    def copy_rename_mods(self):
        """ Rename the mods with a prefix number. If there is a external
        (source) directory for mods, then copy/rename the mods to the
        installers (target) dir. """

        op_count = len(self.disk_operations)
        ow_count = len(self.overwritten_mods)

        if self.cfg.rename:
            if op_count == 0:
                self.cfg.log("Nothing to be done, your mod archives are already"\
                        " named as they should be. Congratulations :-)")
                exit()
            if ow_count > 0:
                self.cfg.log("\nERROR: The renaming step will not be executed"\
                        " as %d archives would be lost (overwritten)."\
                        "\nRefer to the file '%s' to see which files are"\
                        " involved,\nthen you should give them another name"\
                        " and try BIO again." % (
                            len(self.overwritten_mods),
                            self.cfg.path['disk_operations']))
                exit()
            self.cfg.log("\nRENAMING STEP: %d archives located in the '%s'"\
                    " directory will now be renamed" \
                    " with a numerical prefix." %
                    (op_count, self.cfg.path['tgt_dir']))

        else:
            if ow_count > 0:
                self.cfg.log("\nWARNING: %d archives will be overwritten"\
                        " during the copy process." %
                        len(self.overwritten_mods))
                self.cfg.log("\nCOPY STEP: %d archives located in the '%s'"\
                    " directory and its subdirectories will now be copied to"\
                    " the\n'%s' directory and renamed with a numerical prefix." %
                    (op_count, self.cfg.path['src_dir'],
                        self.cfg.path['tgt_dir']))

        self.cfg.log("\nIMPORTANT: You REALLY should consult the file '%s'"\
                " which details the disk operations that are going to be done."
                % self.cfg.path['disk_operations'])
        if 'dot' in self.cfg.path:
            self.cfg.log(
                    "\nYou can get a visual representation of mod precedence"\
                    "by opening the file '%s.pdf'"\
                    % self.cfg.path['overlaps'])

        self.cfg.log("\nType 'yes' + Enter to start disk operations.")
        try:
            answer = raw_input()
        except KeyboardInterrupt:
            self.cfg.log("\nScript stopped.")
            exit()
        if answer.lower() != "yes":
            self.cfg.log("Process cancelled, good bye.")
            exit()

        tgt_dir = self.cfg.path['tgt_dir']
        src_dir = self.cfg.path['src_dir']

        for old_name, new_name in self.disk_operations:
            src = "%s%s" % (src_dir, old_name)
            tgt = "%s%s" % (tgt_dir, new_name)
            if src == tgt:
                self.cfg.log("No renaming needed for mod: %s" % old_name, False)
            else:
                if self.cfg.rename:
                    shutil.move(src, tgt)
                else:
                    shutil.copy(src, tgt)

        self.cfg.log('\nOperations done!')

    def mod_analysis(self):
        tstart = time.time()
        self.cfg = ModConfig(ini_file)

        self.cfg.log("\nObjective Install Order, run on %s" % time.ctime())

        self.mod_graph = ModGraph(self.cfg)

        self.traverse_archives(self.cfg.path['src_dir'])

        if len(self.datafile_list) == 0:
            raise ModAnalysisError("No archives found in the '%s' directory." %
                    self.cfg.path['src_dir'])
        else:
            self.cfg.log("\t- Found %d module archives." %
                    self.mod_graph.node_count())

        self.set_overlapping_datafiles()

        if len(self.overlapping_datafiles) == 0:
            self.cfg.log("There is no overlapping module, nothing to do.")
            exit()

        self.overlapping_datafiles_to_graph()

        self.cfg.log("\t- Found %d overlapping module archives." %
                self.mod_graph.node_count())

        self.mod_graph.set_edge_props()
        self.mod_graph.set_directions()
        self.mod_graph.break_cycles()
        self.mod_graph.count_mod_overlapped_files()
        self.ordered_overlap_mod = self.mod_graph.tsort_graph()
        self.mod_graph.restore_cycles()
        self.set_free_mod()
        self.prepare_disk_operations()
        self.write_info_files()

        self.cfg.log("\t- Process time: %.2fs" % (time.time() - tstart))

        self.copy_rename_mods()

        self.cfg.log_fd.close()


if __name__ == "__main__":
    try:
        start()
    except ModAnalysisError as e:
        print "\nAnalysis Error: " + e.msg
    except ModGraphError as e:
        print "\nGraph Processing Error: " + e.msg
    except ModConfigError as e:
        print "\nConfiguration Error: " + e.msg
    except AssertionError as e:
        print e.args[0]
