# elveg_merge
Merge Elveg to highways in OSM.

### Usage

<code>
python elveg_merge.py [replace | offset | new | tag] [OSM file] [Elveg file]
</code>

### Notes

* This program offers 4 ways of merging Elveg:
  * <code>replace</code>: All Elveg highways are merged.
  * <code>offset</code>: All Elveg highways with more than a predefined average offset are included (but not merged).
  * <code>new</code>: All Elveg highways with no match in OSM file are included (but not merged).
  * <code>tag</code>: Highways in OSM are updated with tags from Elveg, such as maxspeed, name etc. (no new geometry).

* Matching of highways between OSM and Elveg:
  * Matching is based on the average distance between the closest nodes in the two highways from OSM and Elveg.
  * Nodes more than 25 meters away are not considered.
  * The highways with the lowest average distance are matched.
  * Highways with lengths more than 5x different are not matched.
  * Please simplify the Elveg file with a 0.2 factor before running the program.
  
* Manual inspection is necessary in JOSM:
  * The method is not perfect, so manual inspection is necessary.
  * OSM highways which are not automatically merged, and need to be replaced or deleted manually
  * OSM highways with certain tags (*turn:lanes*, *destination*, *piste*, *snowmbile*, *railway*, *area*) need manual merging (to avoid loosing information).
  * Paths need to be reconnected to the new highways from Elveg.
  * Relations need repairing.
  * The *highway=** type is derived from OSM, while the Elveg type (if different) is provided in the *ELVEG=** attribute.
  
* Suggestions for improving the program are encoraged!

### References

* [Guide to Elveg import](https://wiki.openstreetmap.org/wiki/No:Veileder_Elveg-import)
* [Progress for Elveg import](https://wiki.openstreetmap.org/wiki/Import/Catalogue/Road_import_(Norway)/Progress)
* [Elveg files](https://drive.google.com/drive/folders/0BwxPkSBawddGN0hUeUZtLUctUW8)
