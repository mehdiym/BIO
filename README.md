Morrowind Better Install Order
==============================

* Version: 0.1
* Copyright 2015 Mehdi Yousfi-Monod
* License: GPL v3 (see the file: COPYING.txt)

What the tool does
------------------

BIO helps you install your mods. It uses "objective" criteria (as opposed to subjective) to order your mod packages (thx to numerical prefix in filenames) in your Installers directory. Its goal is to help you start from a not-so-bad order and then let you tune your list using a few configuration options. Finally the player can use Wrye Mash to perfect the order.

I know players use their tastes to decide which mod (data files) should override which other, by watching at textures/meshes, listening to sound files, assessing if the mod fits well with others ingame... but I really think we can use some objective information to automatically decide on most cases without doing too much corrections afterwards.

Requirements
------------

If you want to see the precedence graph:

- Graphviz (http://www.graphviz.org/), including the 'dot' binary

Depending on you mod archive format:

- 7-Zip (http://www.7-zip.org/)
- RAR/WinRAR (http://www.rarlab.com/)
- ZIP/WinWIP (http://www.winzip.com/)

How it works
------------

The tool analyses all your archives (7z, rar, zip, but no support for uncompressed "projects" yet) in a given directory, traversing recursively subdirectories if it find some (I like organizing my mods in categories and subcategories).
It looks for conflicting data files, then shows you a graphical view of the conflicts and its suggested order. Finally if you want to, it renames and copies your archives to the Installers directory, adding a numeral prefix to each conflicting archive so their default order will be preserved in Wrye Mash.

Every possible pair of packages are compared according to 3 "objective" criteria in order to decide which one shall override the other.

The 3 "objective" criteria I've found are:
1. Size of data files
2. Data files count
3. Timestamp of data files

The hypotheses behind the tool is we can hope that, in general, statistically:
1. The larger the data files, the better the quality (textures, meshes, sounds...).
2. The less files a mod has the more specialized it should be. I mean, big packs with lots of files like the Visual Pack, Connary's or Darknut's little weapons should have a lower score than smaller graphic replacement mods (eg. Umbra replacement) to allow the latter ones to override the data files of the former ones.
3. The more recent a mod is, the more actual / updated / improved it should be compared to an older mod.

These criteria are computed for each pair of data files for each mod archive and then a final score is given for each pair of mods. The scores are used to build a mod install precedence graph, which is then linearized to get the final ordered list of mods.

The linearization might reverse one or more edges (overrides) if the algorithm produces loops in the graph.
Example: If we've got the overrides A > B > C > A, then the tool will reverse the pair having the smaller override score.
If that pair is (B > C), then the final result is A > B < C > A and the generated ordered list is B A C.

Graph example
-------------

You can find a graph in PDF format, 'overlaps.pdf', in the 'out' directory.

The thicker the edge, the greater the overriding score is.
Mods with no overlaps are not included as they can be installed in any order.
The tool also generates a detailed text report, 'out/overlaps.txt', on which mod overrides which other, for what data files, with what scores...

Tuning
------

The tool offers you several ways to tune your graph (through the bio.ini file):
- Global coefficients, one for each of the 3 criteria, eg. size = 0.8 (instead of 1.0)
- Specific coefficients, applied on a specific mod archive, eg. "Visual Pack.7z" = 0.5
- Specific overrides, let you force an override of a mod over another, eg. "Connary Pack.7z" = "Visual Pack.7z" meaning you force Connary Pack to override Visual Pack.

Examples can be found in the bio.ini file.

Finishing
---------

Once your satisfied with the precedence graph, you can let the tool copy and rename my mods to the Installers directory.

