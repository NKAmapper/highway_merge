# highway_merge
Merge NVDB (or Elveg) to highways in OSM.

### Usage

<code>
python highway_merge.py [-replace | -offset | -new | -tag] [OSM file] [NVDB file]
</code>

### Notes

* This program offers 4 ways of merging NVDB (or Elveg):
  * <code>-replace</code>: All NVDB highways are merged.
  * <code>-offset</code>: All NVDB highways with more than a predefined average offset are included (but not merged).
  * <code>-new</code>: All NVDB highways with no match in OSM file are included (but not merged).
  * <code>-tag</code>: Highways in OSM are updated with tags from NVDB, such as maxspeed, name etc. (no new geometry).

* Matching of highways between OSM and NVDB:
  * Matching is based on the average distance between the closest nodes in the two highways from OSM and NVDB.
  * Nodes more than 25 meters away are not considered.
  * The highways with the lowest average distance are matched.
  * Highways with lengths more than 5x different are not matched.
  * Please simplify the NVDB file with a 0.2 factor before running the program.
  
* Manual inspection is necessary in JOSM:
  * The method is not perfect, so manual inspection is necessary.
  * OSM highways which are not automatically merged, and need to be replaced or deleted manually
  * OSM highways with certain tags (*turn:lanes*, *destination*, *piste*, *snowmbile*, *railway*, *area*, *mtb*) need manual merging (to avoid loosing information).
  * Paths need to be reconnected to the new highways from NVDB.
  * Relations need repairing.
  * The *highway=** type is derived from OSM, while the NVDB type (if different) is provided in the *NVDB=** attribute.
  
* Suggestions for improving the program are encoraged!

### Changelog

* 1.1: Rename Elveg to NVDB
* 1.0: Converted to Python 3 code.
* 0.9: "-new" command will only produce new highways (will not include existing highways from OSM).

### References

* [Guide to NVDB import](https://wiki.openstreetmap.org/wiki/No:Veileder_Elveg-import)
* [Progress for NVDB import](https://wiki.openstreetmap.org/wiki/Import/Catalogue/Road_import_(Norway)/Progress)
* [nvdb2osm](https://github.com/NKAmapper/nvdb2osm) on GitHub
* [NVDB files](https://www.jottacloud.com/s/059f4e21889c60d4e4aaa64cc857322b134)
