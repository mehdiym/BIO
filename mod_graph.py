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
import shlex
import subprocess
import time
import math
from xml.sax.saxutils import escape

__all__ = ["ModGraph", "ModGraphError"]


class ModGraphError(Exception):
    def __init__(self, msg):
        self.msg = msg

def str_to_time(_str):
    return int(time.mktime(
        time.strptime(_str, "%Y-%m-%d %H:%M:%S")) / (3600 * 24))

class _FileProps(object):
    """ Properties of a file being shared by 2 module archives.
    """

    # First Morrowind release
    start_time = str_to_time("2002-05-01 12:00:00")

    def __init__(self, sizes, mtimes):
        self.sizes = sizes
        t0 = str_to_time(mtimes[0])
        t1 = str_to_time(mtimes[1])
        t0 = ((self.start_time - 1) if (t0 <= self.start_time)
                else t0 - self.start_time)
        t1 = ((self.start_time - 1) if (t1 <= self.start_time)
                else t1 - self.start_time)
        self.mtimes = (t0, t1)


class _ModProps(object):
    """ Properties of a module as a node in the graph.
    """

    def __init__(self, file_count=None, size=None):
        # Total uncompressed size of the archive
        self.size = size
        # Total number of files (excluding directories)
        self.file_count = file_count
        self.install_index = None


class _ModEdge(object):
    """ Properties of an edge between 2 modules in the graph.
    """

    # Score factors will take value between 0 and max_amplitude
    max_amplitude = 10

    max_size_ratio = 0
    max_mtime_ratio = 0
    max_fc_ratio = 0

    @classmethod
    def set_max_ratios(cls, size, mtime, file_count):
        if size > cls.max_size_ratio:
            cls.max_size_ratio = size
        if mtime > cls.max_mtime_ratio:
            cls.max_mtime_ratio = mtime
        if file_count > cls.max_fc_ratio:
            cls.max_fc_ratio = file_count

    @classmethod
    def get_normalizing_powers(cls):
        num = math.log(cls.max_amplitude)
        return (
                num / math.log(cls.max_size_ratio),
                num / math.log(cls.max_mtime_ratio),
                num / math.log(cls.max_fc_ratio))

    def __init__(self):
        # Archive data files: {filename = (size in mod1, size in mod2)}
        self.datafiles = {}
        # Number of files in mod1 over mod2
        self.norm_fc_ratio = None
        # Normalized size ratio of each overlapping files
        self.norm_size_ratio = None
        # Normalized modification time ratio of each overlapping files
        self.norm_mtime_ratio = None
        # Final score
        self.score = None
        # Does the edge has been removed during the break cycles step?
        self.removed = False


class ModGraph(object):
    """ Graph representation of Morrowind modules
    installation precedence.
    """

    def __init__(self, cfg):
        self.mod_nodes = {}
        self.mod_edges = {}
        self.cfg = cfg

    def copy(self):
        copy = ModGraph(self.cfg)
        copy.mod_nodes = self.mod_nodes.copy()
        for mod in self.mod_edges:
            copy.mod_edges[mod] = self.mod_edges[mod].copy()
        return copy

    def add_node(self, mod, file_count, size):
        self.mod_nodes[mod] = _ModProps(file_count, size)

    def node_count(self):
        return len(self.mod_nodes)

    def get_outgoing_nodes(self):
        return reduce(set.union, self.mod_edges.itervalues(), set())

    def get_connected_nodes(self):
        return set.union(set(self.mod_edges.keys()), self.get_outgoing_nodes())

    def del_isolated_nodes(self):
        # remove unconnected nodes from the graph
        connected_nodes = self.get_connected_nodes()
        for mod in self.mod_nodes.keys():
            if mod not in connected_nodes:
                del(self.mod_nodes[mod])

    def get_roots(self):
        """ Returns the list of all nodes with
        outgoing edges but no incoming edges. """
        roots = [node for node in self.mod_edges
                 if node not in self.get_outgoing_nodes()]
        return roots

    def has_incoming_edge(self, mod):
        for mod1 in self.mod_edges:
            if mod in self.mod_edges[mod1]:
                return True
        return False

    def add_edge(self, mod1, mod2, mod_edge = None):
        if mod_edge is None:
            mod_edge = _ModEdge()
        if mod1 not in self.mod_edges:
            self.mod_edges[mod1] = {}
        if mod2 not in self.mod_edges[mod1]:
            self.mod_edges[mod1][mod2] = mod_edge

    def add_edge_datafile(self, mod1, mod2, datafile, sizes, mtimes):
        self.add_edge(mod1, mod2)
        fileprops = _FileProps(sizes, mtimes)
        self.mod_edges[mod1][mod2].datafiles[datafile] = fileprops

    def del_edge(self, mod1, mod2):
        del(self.mod_edges[mod1][mod2])
        if not self.mod_edges[mod1]:
            del(self.mod_edges[mod1])

    def set_edge_props(self):
        """ Calculates the score factors for each couple of mods (mod1, mod2).
        Such factors are similarity functions used to determine whether the
        overlapping files of mod1 should overwrite those of mod2 or not.
        For calculation and configuration convenience, these factors
        have to satisfy: F(mod1, mod2) = 1/F(mod2, mod1)
         """
        for mod1 in self.mod_edges:
            for mod2 in self.mod_edges[mod1]:
                norm_size_ratio = 1.0
                norm_mtime_ratio = 1.0
                edge = self.mod_edges[mod1][mod2]
                datafiles = edge.datafiles
                # For each overlapping file between mod1 and mod2
                for file_props in datafiles:
                    # Average size ratio
                    sizes = datafiles[file_props].sizes
                    norm_size_ratio *= float(sizes[0]) / sizes[1]
                    # Average modification time ratio
                    mtimes = datafiles[file_props].mtimes
                    norm_mtime_ratio *= float(mtimes[0]) / mtimes[1]

                # The size and mtime factors are now applied a
                # nth root as they have been multiplied n times.

                size_ratio = norm_size_ratio ** (1.0 / len(datafiles))
                edge.norm_size_ratio = size_ratio

                mtime_ratio = norm_mtime_ratio ** (1.0 / len(datafiles))
                edge.norm_mtime_ratio = mtime_ratio

                # File count ratio: Mods with fewer files are
                # supposed to be more specialized and thus should take
                # precedence over more populated ones.
                fc_ratio = (
                        float(self.mod_nodes[mod2].file_count) /
                        self.mod_nodes[mod1].file_count)
                edge.norm_fc_ratio = fc_ratio

                # Update maximum factor values for future normalizing
                _ModEdge.set_max_ratios(
                        size_ratio, mtime_ratio, fc_ratio)

        # Now normalize the factors
        size_power, mtime_power, file_count_power = (
                _ModEdge.get_normalizing_powers())
        for mod1 in self.mod_edges:
            for mod2 in self.mod_edges[mod1]:
                edge = self.mod_edges[mod1][mod2]
                edge.norm_size_ratio = edge.norm_size_ratio ** size_power
                edge.norm_mtime_ratio = edge.norm_mtime_ratio ** mtime_power
                edge.norm_fc_ratio = edge.norm_fc_ratio ** file_count_power

    def set_directions(self):
        """ Removes edges for mod1 < mod2 to produce a directed graph. """
        for mod1 in self.mod_edges.keys():
            for mod2 in self.mod_edges[mod1].keys():

                edge = self.mod_edges[mod1][mod2]
                # Mod individual coefficients
                coeff = (self.cfg.get_mod_coeff(mod1) /
                        self.cfg.get_mod_coeff(mod2))
                # Size coefficient
                size_power = self.cfg.size_coeff
                # Modification Time coefficient
                mtime_power = self.cfg.mtime_coeff
                # File Count (specificity) coefficient
                fc_power = self.cfg.fc_coeff
                # Final score
                score = (edge.norm_size_ratio ** size_power *
                        edge.norm_mtime_ratio ** mtime_power *
                        edge.norm_fc_ratio ** fc_power *
                        coeff)

                # Does the configuration file specify that
                # mod1 takes precedence over mod2?
                force = self.cfg.is_greater(mod1, mod2)

                # If mod2 > mod1 according to the calculated score
                # or forced by the configuration file, then delete
                # mod precedence mod1 -> mod2
                if ((score < 1 or force == -1) and force != 1):
                    self.del_edge(mod1, mod2)
                else:
                    self.mod_edges[mod1][mod2].score = score

    def break_cycles(self):
        """ Breaks precedence cycles (eg. mod1 > mod2 > mod3 > mod1), if there
        is any, by discarding a minimum set of precedences.

        Implements the algorithm described in "Combinatorial Algorithms for
        Feedback Problems in Directed Graphs" by Camil Demetrescu and
        Irene Finocchi: "Given a weighted directed graph G = (V, A),
        the minimum feedback arc set problem consists of finding
        a minimum weight set of arcs A' ⊆ A such that the directed graph
        (V, A\A') is acyclic."

        The weights here are the previously calculated scores for each couple of
        mod, ie. for each edge of the graph.
        """
        def get_cycle():
            unvisited = self.mod_nodes.keys()
            cycle = []
            # Depth first traversal. Build a cycle, or None.
            # Returns True when a cycle is found, False otherwise
            def traverse_graph():
                if len(cycle) == 0:
                    if len(unvisited) == 0:
                        return False
                    cycle.append(unvisited.pop())
                cur_node = cycle[-1]
                if cur_node in self.mod_edges:
                    for n in self.mod_edges[cur_node]:
                        if n in cycle:
                            # Remove the tail before the cycle
                            for j in range(cycle.index(n)):
                                cycle.pop(0)
                            return True
                        elif n in unvisited:
                            cycle.append(n)
                            unvisited.pop(unvisited.index(n))
                            if traverse_graph():
                                return True
                cycle.pop()
                return False
            while len(unvisited) > 0:
                if traverse_graph():
                    return cycle
            return None

        def get_min_edge_value(cycle):
            minval = -1
            for i in range(len(cycle) - 1):
                e = self.mod_edges[cycle[i]][cycle[i + 1]].val
                if e < minval or minval == -1:
                    minval = e
            return minval

        def remove_min_edges(cycle, val):
            # Feedback Arc Set
            FAS = []
            for i in range(len(cycle) - 1):
                n1 = cycle[i]
                n2 = cycle[i + 1]
                self.mod_edges[n1][n2].val -= val
                if self.mod_edges[n1][n2].val == 0:
                    FAS.append((n1, n2, self.mod_edges[n1][n2]))
                    self.del_edge(n1, n2)
            return FAS

        for mod1 in self.mod_edges:
            for mod2 in self.mod_edges[mod1]:
                val = self.mod_edges[mod1][mod2].score
                self.mod_edges[mod1][mod2].val = round(val * 1000)

        FAS = []
        cycle = get_cycle()
        while cycle is not None:
            minval = get_min_edge_value(cycle)
            FAS.extend(remove_min_edges(cycle, minval))
            cycle = get_cycle()

        self.FAS = []
        for edge in FAS:
            self.add_edge(*edge)
            if get_cycle() is not None:
                self.del_edge(edge[0], edge[1])
                edge[2].removed = True
                self.FAS.append(edge)

        if len(self.FAS) > 0:
            self.cfg.log("Discarded %d overlap(s) in order to break cycling "\
                    "overlap precedence." % len(self.FAS))

    def tsort_graph(self):
        """ Constructs a topological sorting of the graph
        processed as a partially ordered set. """
        ordered_overlap_mod = []
        graph = self.copy()
        roots = graph.get_roots()

        while roots:
            # For arbitrary choices between non overlapping mods,
            # archives with less files are popped first and thus
            # will be put later on the installation order list.
            roots = sorted(roots,
                           key=lambda mod: -graph.mod_nodes[mod].file_count)
            mod1 = roots.pop()
            ordered_overlap_mod.append(mod1)
            if mod1 not in graph.mod_edges:
                continue
            for mod2 in list(graph.mod_edges[mod1]):
                graph.del_edge(mod1, mod2)
                if not graph.has_incoming_edge(mod2):
                    roots.append(mod2)
        if len(graph.mod_edges) > 0:
            raise ModGraphError(
                    "Error: The mod graph being processed has one or more "\
                            "cycles and this should not happen.\nPlease "\
                            "contact the author and tell him about this "\
                            "message.\n\n")

        ordered_overlap_mod.reverse()
        for (i, mod) in enumerate(ordered_overlap_mod):
            self.mod_nodes[mod].install_index = i
        return ordered_overlap_mod

    def restore_cycles(self):
        for edge in self.FAS:
            self.add_edge(*edge)

    def __str__(self):

        def str_size(size):
            if size < 10**3:
                return '%3do' % size
            elif size < 10**6:
                return ('%3dK' % (size / 10**3))
            else:
                return ('%3dM' % (size / 10**6))

        col_fs1 = 5 # max: xxxX
        col_fs2 = 5 # max: xxxX
        col_ns = 6 # max: xx.xx
        col_nt = 6 # max: xx.xx
        col_fc_ratio = 8 # max: xxx.xx
        col_score = 9 # max: xxxx.xx
        col_fc = 6 # max: xxxx
        col_size = 6 # max: xxxX
        tab = 4
        stab = " " * tab

        def real_len(mod):
            return len(self.cfg.clean_mod_name(mod))

        max_source_mod = self.cfg.clean_mod_name(
                max(self.mod_edges, key=real_len))
        max_target_mod = self.cfg.clean_mod_name(
                max(self.get_outgoing_nodes(), key=real_len))
        mod_name_max_length = (
                max(len(max_source_mod),
                    tab + len(max_target_mod)))
        col_file = mod_name_max_length
        all_col = (col_file + col_fs1 + col_fs2 + col_ns + col_nt +
                col_fc_ratio + col_score + col_fc + col_size)
        sep = '%s\n' % ('-' * all_col)

        buff = ["*** Graph of Mod Install Precedence ***\n\n",
                "Each mod name is a node.\n",
                "Edge directions are from unindented lines ",
                "to indented ones:\n\n",
                "mod1.7z\n",
                "%smod2.7z\n\n" % stab,
                "means mod1 should overwrite files of mod2.\n\n",
                "Sizes of overlapping files:\n",
                "%sFS1 = File Size from mod1\n" % stab,
                "%sFS2 = File Size from mod2\n" % stab,
                "Values comparing mod1 and mod2:\n",
                "%sNSR = Normalized Size Ratio of overlapping files\n" % stab,
                "%sNTR = Normalized modification Time Ratio of"\
                        " overlapping files\n" % stab,
                "%sFCR = File Count Ratio of all files\n" % stab,
                "%sScore = NS * FCR\n" % stab,
                "Values based on the whole mod:\n",
                "%sFC = File Count\n" % stab,
                "%sSize = Total (uncompressed) Size of the mod\n\n" % stab]
        titles = ''.join([
            sep,
            "Mod Filenames and Overlapping Files".ljust(col_file),
            "FS1".rjust(col_fs1),
            "FS2".rjust(col_fs2),
            "NSR".rjust(col_ns),
            "NTR".rjust(col_nt),
            "FCR".rjust(col_fc_ratio),
            "Score".rjust(col_score),
            "FC".rjust(col_fc),
            "Size".rjust(col_size),
            "\n%s" % sep])
        buff.append(titles)
        lines = 0
        for mod1 in sorted(self.mod_edges.iterkeys()):
            mod1_name = self.cfg.clean_mod_name(mod1)
            if lines > 40:
                buff.append(titles)
                lines = 0
            buff.append('%s%s%s\n' % (
                mod1_name.ljust(col_file + col_fs1 + col_fs2 + col_ns +
                    col_nt + col_fc_ratio + col_score),
                str(self.mod_nodes[mod1].file_count).rjust(col_fc),
                str_size(self.mod_nodes[mod1].size).rjust(col_size)))
            lines += 1
            for mod2 in sorted(self.mod_edges[mod1].iterkeys()):
                mod2_name = self.cfg.clean_mod_name(mod2)
                edge = self.mod_edges[mod1][mod2]
                if edge.removed:
                    buff.append("(discarded overlap:)\n")
                buff.append('%s%s%s%s%s%s%s%s\n' % (
                    stab,
                    mod2_name.ljust(col_file + col_fs1 + col_fs2 - tab),
                    ("%.2f" % round(edge.norm_size_ratio, 2)).rjust(col_ns),
                    ("%.2f" % round(edge.norm_mtime_ratio, 2)).rjust(col_nt),
                    ("%.2f" % round(edge.norm_fc_ratio,
                                    2)).rjust(col_fc_ratio),
                    ("%.2f" % round(edge.score, 2)).rjust(col_score),
                    str(self.mod_nodes[mod2].file_count).rjust(col_fc),
                    str_size(self.mod_nodes[mod2].size).rjust(col_size)))
                lines += 1
                for datafile in sorted(edge.datafiles.iterkeys())[:20]:
                    sizes = edge.datafiles[datafile].sizes
                    buff.append('%s%s%s%s\n' % (
                        stab * 2,
                        datafile.ljust(col_file - 2 * tab),
                        str_size(sizes[0]).rjust(col_fs1),
                        str_size(sizes[1]).rjust(col_fs2)))
                    lines += 1
                if len(edge.datafiles) > 20:
                    buff.append('%s[...]\n' % (stab * 2))
                    lines += 1
        return ''.join(buff)

    def to_graphviz(self):
        def to_node(path):
            return ('_%s' %
                    re.sub(
                        "\W+",
                        "_",
                        os.path.basename(os.path.splitext(path)[0])))
        def to_label(path):
            def split_label(_str, pos, _max):
                look_left = _str.rfind(" ", pos - _max, pos)
                look_right = _str.find(" ", pos, pos + _max)
                if look_left + look_right == -2:
                    return _str
                if look_right == -1 or pos - look_left < look_right - pos:
                    idx = look_left
                else:
                    idx = look_right
                return '%s\n%s' % (_str[:idx], _str[idx + 1:])

            label = os.path.basename(os.path.splitext(path)[0])
            parts = int(round((len(label) / 2) ** 0.5))
            part = len(label) / parts
            for i in range(1, parts):
                label = split_label(label, i * part, part)
            xml_label = escape(label)

            coeff = self.cfg.get_mod_coeff(path)
            coeff_label = ''
            if coeff != 1:
                coeff_label = (
                        '<br/><font color="green">coeff=%s</font>' % str(coeff))
            return ("\t%s [label=<%s%s>];\n" % (
                to_node(path),
                xml_label.replace("\n","<br/>"),
                coeff_label))

        _str = ["digraph G {\n"]
        for mod in self.mod_nodes:
            _str.append(to_label(mod))
        for mod1 in self.mod_edges:
            node1 = to_node(mod1)
            for mod2 in self.mod_edges[mod1]:
                node2 = to_node(mod2)
                _str.append("\t%s -> %s" % (node1, node2))
                _str.append(" [")
                edge = self.mod_edges[mod1][mod2]
                color = ""
                thickness = 3
                if edge.removed:
                    color = ", color=red"
                else:
                    if self.cfg.is_greater(mod1, mod2):
                        color = ", color=green"
                    else :
                        # 0 < score < 25
                        thickness = round(math.log(edge.score) + .5, 2)
                _str.append('style="setlinewidth(%s)"' % str(thickness))
                _str.append(color)
                _str.append("];\n")
        _str.append("}\n")

        return ''.join(_str)

    def write_graph_files(self, filename):
        with open('%s.txt' % filename,'w') as stream:
            stream.write(str(self))
        if 'dot' in self.cfg.path:
            with open('%s.dot' % filename,'w') as stream:
                stream.write(self.to_graphviz())
            dotcmd = ('%s -Tpdf "%s.dot" -o "%s.pdf"' % (
                self.cfg.path['dot'], filename, filename))
            dotargs = shlex.split(dotcmd)
            subprocess.Popen(dotargs, stdout=self.cfg.log_fd,
                    stderr=self.cfg.log_fd)


