# highway_merge
Merge NVDB (or Elveg) to highways in OSM.

### Usage

<code>
python highway_merge.py [-new | -replace | -offset | -tagref | -taglocal] [OSM file] [NVDB source file]
</code>

or for Norway/Sweden: 
<code>
python highway_merge.py [-new | -replace | -offset | -tagref | -taglocal] [municipality name or ref] [-swe]
</code> 

### Notes

* This program offers 4 ways of merging NVDB (or Elveg):
  * <code>-new</code>: All NVDB highways with no match in OSM file are included (but not merged). This is the primary function.
  * <code>-replace</code>: All NVDB highways are merged.
  * <code>-offset</code>: All NVDB highways with more than a predefined average offset are included (but not merged).
  * <code>-tagref</code>: State and county highways with ref=* in OSM are updated with tags from NVDB, such as maxspeed, name etc. (no new geometry).
  * <code>-taglocal</code>: Local highways in OSM are updated with tags from NVDB, such as maxspeed, name etc. (no new geometry).

* Data files:
  * The [NVDB file](https://www.jottacloud.com/s/059f4e21889c60d4e4aaa64cc857322b134) must be downloaded before you run the program (except for Sweden).
  * Instead of the _OSM file_ and _NVDB file_ parameters, you may provide the name or ref of the municipality (Norway and Sweden only); add <code>-swe</code> to use a Swedish municipality name. "Norge" will produce all municipalities in one go. Existing highways will be loaded from OSM automatically.

* Matching of highways between OSM and NVDB:
  * Matching is based on the average distance between the two highways from OSM and NVDB.
  * Segments more than 25 meters away are not considered.
  * The highways with the lowest average distance are matched.
  * Matched highways must have at least 30% length in common (60% for "new").
  
* Manual inspection is necessary in JOSM:
  * The method is not perfect, so manual inspection is necessary. Please expect a few false positives, in particular for cycleways since the length of these highways may often differ a lot between OSM and NVDB.
  * OSM highways which are not automatically merged, and need to be replaced or deleted manually
  * OSM highways with certain tags (*turn:lanes*, *destination*, *piste*, *snowmbile*, *railway*, *area*, *mtb*) need manual merging (to avoid loosing information).
  * Paths need to be reconnected to the new highways from NVDB.
  * Relations need repairing.
  * The *highway=** type is derived from OSM, while the NVDB type (if different) is provided in the *NVDB=** attribute.
  
* Suggestions for improving the program are encoraged!

### Workflow

#### With `-new` argument

Use the `-new` argument for municipalities which have most highways already mapped in OSM. It can also be used to discover newly built highways in NVDB after an earlier import. The produced file will contain all existing highways from OSM in the municipality plus all the highways from NVDB which did not match OSM.
1. Run (for example) `python highway_merge.py -new Eda -swe` and load the resulting file into JOSM.
2. In JOSM, frist consider to replace all the major highways (motorway, trunk, primary, secondary, tertiary). If so, copy them from the NVDB file and use the _Replace Geometry_ function to replace the existing highways.
3. In JOSM, search for `new type:way` to get alle the new highways, put them into the _To-Do_ plugin, step through each highway and attach all of them to the existing highway network. Some will be false positives and should be deleted. Alternatively, go directly to step 3.
4. Run the _Validation_ function in JOSM and fix the following error messages and warnings:
   i. Double-click on _"Crossing highways"_, search for `selected new`, put them into the _To-Do_ plugin and walk through each highway to fix the crossing.
   ii. Double-click on _"Way end node near other highway"_, search for `selected type:node new`, put them into the _To-Do_ plugin and step through each node to attach it (if needed).
5. Search `type:way -(modified or parent modified)` to check if there are any remaining new highways which have not yet been attached to the highway network, and fix them.
6. Carry out other quality checks and enhancements and upload to OSM.

#### With `-replace` argument

Use the -replace argument for municipalities which are missing the majority of highways in OSM. It will automatically match highways in OSM with NVDB and merge all highways with a close match, while leaving the rest for manual conflation. This may speed up to import process significantly.
1. Run (for example) `python highway_merge.py -replace Dals-Ed -swe` and load the resulting file into JOSM.
2. First search `NVDB:trunk or NVDB:primary or NVDB:secondary or NVDB:teritary` to check if any highways got new highway classes which were unwanted, and fix it.
3. Search `highway -modified -path` to get all existing OSM highways which were not merged. Put them into the _To-Do_ plugin, step through each highway and merge it or delete it. The NVDB tag contains the highway class from the NVDB file.
4. Continue as in step 4-6 in the above section.

#### With `-tagref`/`-taglocal` argument
Use the -tagref and -taglocal arguments for municipalities where most of the highways are already in OSM. It will automaticlly match highways in OSM with NVDB and retag highways with a close match acoording to tags in the NVDB source data. This way, the road network in OSM may be updated with new or missing maxspeed, name, access restrictions etc.
1. Run (for example) `python highway_merge.py -tagref Bodø`and load the resulting file into JOSM.
2. In JOSM, first search `NO_MATCH` to get an overview of which highways were not matched. For -tagref, no matches are often caused by different ref=* in OSM and NVDB.
3. Search `EDIT` to get an overview of which tags have been added or replaced (no tags will be deleted).
5. Search `"bridge:description"` for possible bridge names and `"tunnel:name"`for possible tunnel names.
4. Search `CONSIDER` to check if any additional retagging should be done, for example:
   - Search `CONSIDER:"Add motor_vehicle"` and `CONSIDER:"Add psv"` for possible access restrictions.
   - Search `CONSIDER:"turn:lanes"` for possible lane tagging.
   - Search `CONSIDER:"Add oneway"` for possible one way streets.
5. Search `NEW_SEGMENT waylength:-100` to check if any new highways segments could be merged with a neighbour segment (could be the case at the end of tunnels, bridges and maxspeed sections).
6. Other differences are shown in the `DIFF` tag.
7. Search for `modified` and delete the upper case tags (upper case tags which are not marked as modified will not be uploaded). Then upload to OSM.

### Changelog

* 3.1: Improve suggestions in CONSIDER and DIFF tags.
* 3.0: Add "-tagref" and "-taglocal" commands to retag existing highways in OSM according to NVDB source tags.
  - Also add "-progress" function to update tagging progress status for given municipality.
* 2.3: Add support for automatic loading of data for Swedish municipalities ("-swe" argument).
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
* [Highway update progress for NVDB import](https://wiki.openstreetmap.org/wiki/Import/Catalogue/Road_import_(Norway)/Update)
* [Tag update progress for NVDB import](https://wiki.openstreetmap.org/wiki/Import/Catalogue/Road_import_(Norway)/Tag_Update)
* [nvdb2osm](https://github.com/NKAmapper/nvdb2osm) on GitHub
* [NVDB files](https://www.jottacloud.com/s/059f4e21889c60d4e4aaa64cc857322b134)
