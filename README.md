# highway_merge
Merge NVDB (or Elveg) to highways in OSM.

### Usage

<code>
python highway_merge.py [-new | -replace | -offset | -tag] [OSM file] [NVDB file]
</code>

or for Norway/Sweden: <code>
python highway_merge.py [-new | -replace | -offset | -tag] [municipality name or ref]
</code> 

### Notes

* This program offers 4 ways of merging NVDB (or Elveg):
  * <code>-new</code>: All NVDB highways with no match in OSM file are included (but not merged). This is the primary function.
  * <code>-replace</code>: All NVDB highways are merged.
  * <code>-offset</code>: All NVDB highways with more than a predefined average offset are included (but not merged).
  * <code>-tag</code>: Highways in OSM are updated with tags from NVDB, such as maxspeed, name etc. (no new geometry).

* Data files:
  * The [NVDB file](https://www.jottacloud.com/s/059f4e21889c60d4e4aaa64cc857322b134) must be downloaded before you run the program.
  * Instead of the _OSM file_ and _NVDB file_ parameters, you may provide the name of the municipality (Norway and Sweden only); add <code>-swe</code> to use a Swedish municipality name. "Norge" will produce all municipalities in one go. Existing highways will be loaded from OSM automatically.

* Matching of highways between OSM and NVDB:
  * Matching is based on the average distance between the two highways from OSM and NVDB.
  * Segments more than 25 meters away are not considered.
  * The highways with the lowest average distance are matched.
  * Matched highways must have at least 30% length in common (60% for "new").
  * Please simplify the NVDB file with a 0.2 factor before running the program.
  
* Manual inspection is necessary in JOSM:
  * The method is not perfect, so manual inspection is necessary. Please expect a few false positives for "offset".
  * OSM highways which are not automatically merged, and need to be replaced or deleted manually
  * OSM highways with certain tags (*turn:lanes*, *destination*, *piste*, *snowmbile*, *railway*, *area*, *mtb*) need manual merging (to avoid loosing information).
  * Paths need to be reconnected to the new highways from NVDB.
  * Relations need repairing.
  * The *highway=** type is derived from OSM, while the NVDB type (if different) is provided in the *NVDB=** attribute.
  
* Suggestions for improving the program are encoraged!

### Changelog

* 2.2: Support generating files for all municipalities in Norway in one go ("Norge" parameter).
* 2.1: Automatic loading of data for municipality:
  - Provide municipality name instead of file names.
  - Will fetch OSM data via Overpass.
* 2.0: Major update of the matching algorithm:
  - Distance to line now used instead of distance to node.
  - Reverse matching before accepting a match between two ways.
  - "-new" command is matching with combination of several ways to avoid false positives.
  - "-replace" command will only produce highways with big offset in ouput (will exclude existing highways from OSM).
  - Many other improvements.
* 1.1: Rename Elveg to NVDB.
* 1.0: Converted to Python 3 code.
* 0.9: "-new" command will only produce new highways (will not include existing highways from OSM).

### References

* [Guide to NVDB import](https://wiki.openstreetmap.org/wiki/No:Veileder_Elveg-import)
* [Progress for NVDB import](https://wiki.openstreetmap.org/wiki/Import/Catalogue/Road_import_(Norway)/Progress)
* [nvdb2osm](https://github.com/NKAmapper/nvdb2osm) on GitHub
* [NVDB files](https://www.jottacloud.com/s/059f4e21889c60d4e4aaa64cc857322b134)
