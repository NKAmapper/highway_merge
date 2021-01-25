#!/usr/bin/env python3
# -*- coding: utf8

# highway_merge.py
# Replace OSM highways with NVDB (or Elveg)
# Usage: python highway_merge.py [command] [input_osm.osm] [input_nvdb.osm]
# Commands: - replace: Merge all existing OSM highways with NVDB
#			- offset: Include all NVDB highways above an certain average offset
#			- new: Include only NVDB highways not found in OSM
#			- tag: Update OSM highways with attributes from NVDB (maxspeed, name etc)
# Resulting file will be written to a new version of input file


import sys
import time
import math
import json
from xml.etree import ElementTree


version = "2.0.0"

# Paramters for matching

debug = False       # True will provide extra keys in output file
debug_gap = False   # True will show gap/distance testing in output file
merge_all = False   # True will delete excess way from OSM if its NVDB match is already merged

margin = 15         # Meters of tolarance for matching nodes
margin_new = 8      # Meters of tolerance for matching nodes, for "new" command
margin_offset = 5   # Minimum average distance in meters for matching ways (used with "offset" command to filter large offsets)

match_factor = 0.3  # Minimum percent of length of way matched
new_factor = 0.6    # Ditto for "new" command
min_nodes = 2       # Min number of nodes in a way to be matched

# Do not merge OSM ways with the folowing highway categories
avoid_highway = ["path", "bus_stop", "rest_area", "platform", "construction", "proposed"]

# Do not merge OSM ways with the following keys
avoid_tags = ["area", "railway", "piste:type", "snowmobile", "turn:lanes", "turn:lanes:forward", "turn:lanes:backward", \
			 "destination", "destination:forward", "destination:backward", "destination:ref", "destination:ref:forward", "destination:ref:backward", \
			 "destination:symbol", "destination:symbol:forward", "destination:symbol:backward", "mtb:scale", "class:bicycle:mtb"]

# Overwrite with the following tags from NVDB when merging ways
avoid_merge = ["ref", "name", "maxspeed", "oneway", "junction", "foot", "bridge", "tunnel", "layer", "source"]

# Do not consider OSM highways of the following types when updating tags
avoid_highway_tags = ["cycleway", "footway", "steps"]

# Overwrite with the following tags from NVDB when updating tags in OSM
update_tags = ["ref", "name", "maxspeed", "maxheight", "bridge", "tunnel", "layer"]

# Pedestrian highways which should not be mixed with other highway classes for cars
pedestrian_highway = ["footway", "cycleway"]

# Pubklic highways which should not be mixed with other highway classes
public_highway = ["motorway", "trunk", "primary", "secondary", "motorway_link", "trunk_link", "primary_link", "secondary_link"]

# Only consider the following highway categories when merging (leave empty [] to merge all)
replace_highway = []
#replace_highway = ["motorway", "trunk", "primary", "secondary", "motorway_link", "trunk_link", "primary_link", "secondary_link"]
#replace_highway = ["primary", "secondary", "primary_link", "secondary_link"]



# Output message

def message (line):

	sys.stdout.write (line)
	sys.stdout.flush()



# Compute approximation of distance between two coordinates, in meters
# Works for short distances

def distance(n1_lat, n1_lon, n2_lat, n2_lon):

	lon1, lat1, lon2, lat2 = map(math.radians, [n1_lon, n1_lat, n2_lon, n2_lat])
	x = (lon2 - lon1) * math.cos( 0.5*(lat2+lat1) )
	y = lat2 - lat1
	return 6371000 * math.sqrt( x*x + y*y )



# Compute closest distance from point p3 to line segment [s1, s2]
# Works for short distances

def line_distance(s1_lat, s1_lon, s2_lat, s2_lon, p3_lat, p3_lon):

	x1, y1, x2, y2, x3, y3 = map(math.radians, [s1_lon, s1_lat, s2_lon, s2_lat, p3_lon, p3_lat])

	# Simplified reprojection of latitude
	x1 = x1 * math.cos( y1 )
	x2 = x2 * math.cos( y2 )
	x3 = x3 * math.cos( y3 )

	A = x3 - x1
	B = y3 - y1
	dx = x2 - x1
	dy = y2 - y1

	dot = (x3 - x1)*dx + (y3 - y1)*dy
	len_sq = dx*dx + dy*dy

	if len_sq != 0:  # in case of zero length line
		param = dot / len_sq
	else:
		param = -1

	if param < 0:
		x4 = x1
		y4 = y1
	elif param > 1:
		x4 = x2
		y4 = y2
	else:
		x4 = x1 + param * dx
		y4 = y1 + param * dy

	# Also compute distance from p to segment

	x = x4 - x3
	y = y4 - y3
	distance = 6371000 * math.sqrt( x*x + y*y )  # In meters

	# Project back to longitude/latitude

	x4 = x4 / math.cos(y4)

	lon = math.degrees(x4)
	lat = math.degrees(y4)

	return (lat, lon, distance)



# Compare two ways to determine if they match
# Include only segments of the ways which are closer than margin parameter
# Then check if the average distance between these segments is closer than the earlier best_distance
# Return new best_distance, or None if no match or further appart

def match_ways (way1, way2, best_distance):

	way_distance = 0.0
	count_distance = 0
	match_nodes = []

	# Iterate all nodes in way1 and identify distance from node to way2

	for node1 in way1['nodes']:
		min_node_distance = margin
		prev_node2 = way2['nodes'][0]

		for node2 in way2['nodes'][1:]:
			line_lat, line_lon, node_distance = line_distance(nodes[prev_node2]['lat'], nodes[prev_node2]['lon'], \
													nodes[node2]['lat'], nodes[node2]['lon'], \
													nodes[node1]['lat'], nodes[node1]['lon'])

			if node_distance < min_node_distance:
				min_node_distance = node_distance
				min_node_ref = node1

				gap_test = {
					'lat1': nodes[node1]['lat'],
					'lon1': nodes[node1]['lon'],
					'lat2': line_lat,
					'lon2': line_lon,
					'distance': node_distance
				}

			prev_node2 = node2

		# Include node in matched nodes list if closer distance than margin

		if min_node_distance < margin:
			count_distance += 1
			way_distance += min_node_distance
			if min_node_ref not in match_nodes:
				match_nodes.append(min_node_ref)

				if debug_gap:
					test_lines.append(gap_test)

	# No match if too few matched nodes or if average distance between matched nodes is higher than best so far.
	# Otherwise calculate length of matched segment to check if sufficiently long (proportion of total length of way1)

	if count_distance >= min_nodes and way_distance / count_distance < best_distance:
		match_length = 0

		prev_node = None
		for node in way1['nodes']:
			if node in match_nodes and prev_node in match_nodes:
				match_length += distance(nodes[prev_node]['lat'], nodes[prev_node]['lon'], \
									nodes[node]['lat'], nodes[node]['lon'])
			prev_node = node

		if match_length > match_factor * way1['length']:
			return way_distance / count_distance  # Successful match

	return None



# Load files and build data structure for analysis

def load_files (filename_osm, filename_nvdb):

	global tree_osm, root_osm, tree_nvdb, root_nvdb, count_osm_roads

	tree_osm = ElementTree.parse(filename_osm)
	root_osm = tree_osm.getroot()

	tree_nvdb = ElementTree.parse(filename_nvdb)
	root_nvdb = tree_nvdb.getroot()

	# Prepare nodes

	message ("\nLoad nodes ...")

	count_osm_nodes = 0

	for node in root_osm.iter("node"):
		if not("action" in node.attrib and node.attrib['action'] == "delete"):
			nodes[ node.attrib['id'] ] = {
				'index': node,
				'used': 0,  # Will have a value larger than zero at time of output to avoid deletion
				'lat': float(node.attrib['lat']),
				'lon': float(node.attrib['lon'])
			}

			# Remove node tags used by early editors
			for tag in node.iter("tag"):
				if tag.attrib['k'] == "created_by":
					node.remove(tag)
					node.set("action", "modify")
			count_osm_nodes += 1

	count_nvdb_nodes = 0

	for node in root_nvdb.iter("node"):
		nodes[ node.attrib['id'] ] = {
			'index': node,
			'used': 0,
			'lat': float(node.attrib['lat']),
			'lon': float(node.attrib['lon'])
		}
		count_nvdb_nodes += 1

	message (" %i OSM nodes, %i NVDB nodes" % (count_osm_nodes, count_nvdb_nodes))


	# Determine bounding box and length of OSM ways

	message ("\nLoad ways ...")

	count_osm = 0
	count_osm_roads = 0

	for way in root_osm.iter("way"):
		count_osm += 1
		way_id = way.attrib['id']

		length = 0
		way_nodes = []
		highway = None
		incomplete = False
		avoid_match = False
		min_lat = 0.0
		min_lon = 0.0
		max_lat = 0.0
		max_lon = 0.0

		# Iterate tags to determine if way should be excluded

		for tag in way.iter("tag"):
			osm_tag = tag.attrib['k']
			if osm_tag in avoid_tags:
				avoid_match = True
			if osm_tag == "highway":
				highway = tag.attrib['v']
				if highway not in avoid_highway:
					count_osm_roads += 1

		# Iterate nodes to determine if way is complete

		for node in way.iter("nd"):
			node_id = node.attrib['ref']
			if node_id in nodes:
				nodes[ node_id ]['used'] += 1
			elif not("action" in node.attrib and node.attrib['action'] == "delete"):
				incomplete = True

		if "action" in way.attrib and way.attrib['action'] == "delete":
			incomplete = True

		# Determine bounding box and length of way

		if not incomplete:
			node_tag = way.find("nd")
			node_id = node_tag.attrib['ref']

			min_lat = nodes[ node_id ]['lat']
			min_lon = nodes[ node_id ]['lon']
			max_lat = min_lat
			max_lon = min_lon

			prev_lat = min_lat
			prev_lon = min_lon

			for node in way.iter("nd"):
				if not("action" in node.attrib and node.attrib['action'] == "delete"):

					node_id = node.attrib['ref']
					length += distance(prev_lat, prev_lon, nodes[node_id]['lat'], nodes[node_id]['lon'])

					# Append node and update bbox

					prev_lat = nodes[node_id]['lat']
					prev_lon = nodes[node_id]['lon']

					way_nodes.append(node_id)

					min_lat = min(min_lat, prev_lat)
					min_lon = min(min_lon, prev_lon)
					max_lat = max(max_lat, prev_lat)
					max_lon = max(max_lon, prev_lon)

		# Note: Sinple reprojection of bounding box to meters
		ways_osm[ way_id ] = {
			'index': way,
			'highway': highway,
			'incomplete': incomplete,
			'avoid_tag': avoid_match,
			'min_lat': min_lat - margin / 111500.0,
			'max_lat': max_lat + margin / 111500.0,
			'min_lon': min_lon - margin / (math.cos(math.radians(min_lat)) * 111320.0),
			'max_lon': max_lon + margin / (math.cos(math.radians(max_lat)) * 111320.0),
			'length': length,
			'nodes': way_nodes,
			'tags': {}
		}

	# Determine which nodes are used by relation (should be kept)

	for relation in root_osm.iter("relation"):
		for member in relation.iter("member"):
			if member.attrib['type'] == "node" and member.attrib['ref'] in nodes:
				nodes[ member.attrib['ref'] ]['used'] += 1

	message (" %i OSM ways (%i roads)" % (count_osm, count_osm_roads))

	# Determine bounding box and length of NVDB ways

	count_nvdb = 0

	for way in root_nvdb.iter('way'):
		count_nvdb += 1
		node_tag = way.find("nd")
		node_ref = node_tag.attrib['ref']

		min_lat = nodes[ node_ref ]['lat']
		min_lon = nodes[ node_ref ]['lon']
		max_lat = min_lat
		max_lon = min_lon

		prev_lat = min_lat
		prev_lon = min_lon
		length = 0
		way_nodes = []

		for node in way.iter("nd"):
			node_id = node.attrib['ref']

			length += distance(prev_lat, prev_lon, nodes[node_id]['lat'], nodes[node_id]['lon'])

			# Append node and update bbox

			prev_lat = nodes[node_id]['lat']
			prev_lon = nodes[node_id]['lon']

			way_nodes.append(node_id)

			min_lat = min(min_lat, prev_lat)
			min_lon = min(min_lon, prev_lon)
			max_lat = max(max_lat, prev_lat)
			max_lon = max(max_lon, prev_lon)

		highway_tag = way.find("tag[@k='highway']")
		if highway_tag != None:
			highway = highway_tag.attrib['v']
		else:
			highway = ""

		# Note: Simple reprojection of bounding box to meters
		ways_nvdb[ way.attrib['id'] ] = {
			'index': way,
			'highway': highway,
			'missing': False,
			'min_lat': min_lat - margin / 111500.0,
			'max_lat': max_lat + margin / 111500.0,
			'min_lon': min_lon - margin / (math.cos(math.radians(min_lat)) * 111320.0),
			'max_lon': max_lon + margin / (math.cos(math.radians(max_lat)) * 111320.0),
			'length': length,
			'nodes': way_nodes
		}			

	message (", %i NVDB ways" % count_nvdb)



# Merge NVDB and OSM highways for the commands "replace", "offset" and "tag"

def merge_highways(command):

	message ("\nMatch highways ...\n")

	count = count_osm_roads
	count_swap = 0
	total_distance = 0

	# Pass 1: Match topology
	# Iterate OSM ways to identify best match with NVDB way

	for osm_id, osm_way in iter(ways_osm.items()):

		if not osm_way['incomplete'] and osm_way['highway'] != None and osm_way['highway'] not in avoid_highway:

			message ("\r%i " % count)
			count -= 1

			best_id = None
			best_distance = 99999.0

			for nvdb_id, nvdb_way in iter(ways_nvdb.items()):

				# Avoid ways with no overlapping bbox or with incompatible relative lengths
				if nvdb_way['min_lat'] <= osm_way['max_lat'] and nvdb_way['max_lat'] >= osm_way['min_lat'] and \
					nvdb_way['min_lon'] <= osm_way['max_lon'] and nvdb_way['max_lon'] >= osm_way['min_lon'] and \
					osm_way['length'] > match_factor * nvdb_way['length'] and nvdb_way['length'] > match_factor * osm_way['length']:

					# Avoid mixing pedestrian and car highways
					if nvdb_way['highway'] in pedestrian_highway and osm_way['highway'] not in pedestrian_highway + ["track"] or \
						nvdb_way['highway'] not in pedestrian_highway and osm_way['highway'] in pedestrian_highway:
						continue

					# Avoid mixing trunk etc with lower highway classes
					if nvdb_way['highway'] in public_highway and osm_way['highway'] not in public_highway or \
						osm_way['highway'] in public_highway and nvdb_way['highway'] not in public_highway:
						continue

					# Check if match between OSM and NVDB way, and determine if closest distance between them

					match_distance = match_ways(nvdb_way, osm_way, best_distance)
					if match_distance is not None and match_distance < best_distance:

						# Also check reverse match
						if match_ways(osm_way, nvdb_way, 99999.0) is not None:
							best_id = nvdb_id
							best_distance = match_distance

			# Store match in data structure, if any match

			if best_id is not None:
				if command in ["replace", "offset"]:

					# Replace earlier match if new match is better

					if "osm_id" in ways_nvdb[ best_id ] and ways_nvdb[ best_id ]['distance'] > best_distance:
						count_swap -= 1
						total_distance -= ways_nvdb[ best_id ]['distance']
						del ways_osm[ ways_nvdb[ best_id ]['osm_id'] ]['nvdb_id']
						del ways_nvdb[ best_id ]['osm_id']

					if "osm_id" not in ways_nvdb[ best_id ]:
						count_swap += 1
						total_distance += best_distance
						ways_osm[ osm_id ]['nvdb_id'] = best_id
						ways_nvdb[ best_id ]['osm_id'] = osm_id
						ways_nvdb[ best_id ]['swap_no'] = count_swap  # Debug
						ways_nvdb[ best_id ]['distance'] = best_distance  # Debug

					elif merge_all:
						ways_osm[ osm_id ]['remove'] = True  # Remove redundant way if it got a match

				elif command == "tag":
					count_swap += 1
					total_distance += best_distance
					ways_osm[ osm_id ]['nvdb_id'] = best_id
					ways_osm[ osm_id ]['swap_no'] = count_swap  # Debug
					ways_osm[ osm_id ]['distance'] = best_distance  # Debug

	# Pass 2: Match type highway
	# Remove matches to be avoided before output

	if command == "offset":
		for nvdb_id, nvdb_way in iter(ways_nvdb.items()):
			if "osm_id" in nvdb_way and (nvdb_way['distance'] < margin_offset or ways_osm[ nvdb_way['osm_id'] ]['highway'] in avoid_highway or \
					replace_highway and (osm_way['highway'] not in replace_highway or ways_nvdb[ osm_way['nvdb_id'] ]['highway'] not in replace_highway)):
				count_swap -= 1
				total_distance -= nvdb_way['distance']				
				del ways_nvdb[ nvdb_id ]['osm_id']

	elif command == "replace":
		for osm_id, osm_way in iter(ways_osm.items()):
			if "nvdb_id" in osm_way and (osm_way['avoid_tag'] or \
					replace_highway and (osm_way['highway'] not in replace_highway or ways_nvdb[ osm_way['nvdb_id'] ]['highway'] not in replace_highway)):
				count_swap -= 1
				total_distance -= ways_nvdb[ osm_way['nvdb_id'] ]['distance']
				del ways_nvdb[ osm_way['nvdb_id'] ]['osm_id']
				del ways_osm[ osm_id ]['nvdb_id']

	elif command == "tag":
		for osm_id, osm_way in iter(ways_osm.items()):
			if "nvdb_id" in osm_way and (osm_way['highway'] in avoid_highway or \
					replace_highway and (osm_way['highway'] not in replace_highway or ways_nvdb[ osm_way['nvdb_id'] ]['highway'] not in replace_highway)):
				count_swap -= 1
				total_distance -= osm_way['distance']
				del ways_osm[ osm_id ]['nvdb_id']

	# Report result

	message ("\r%i highways matched, %i not matched" % (count_swap, count_osm_roads - count_swap))
	if command == "replace":
		message ("\n%i missing highways added from NVDB" % (len(ways_nvdb) - count_swap))
	message ("\nAverage offset: %.1f m" % (total_distance / count_swap))



# Identify missing NVDB highways, for "new" command

def add_new_highways():

	message ("\nMatch highways ...\n")

	count = len(ways_nvdb)
	count_missing = 0

	# Iterate NVDB ways to check if match with any OSM way

	for nvdb_id, nvdb_way in iter(ways_nvdb.items()):
		message ("\r%i " % count)
		count -= 1

		if not nvdb_way['highway']:  # Skip ferries etc
			continue

		best_id = None
		best_distance = 99999.0
		match_nodes = []

		for osm_id, osm_way in iter(ways_osm.items()):

			# Avoid testing ways with no overlapping bbox
			if not osm_way['incomplete'] and osm_way['highway'] != None and osm_way['highway'] not in avoid_highway and \
				osm_way['min_lat'] <= nvdb_way['max_lat'] and osm_way['max_lat'] >= nvdb_way['min_lat'] and \
				osm_way['min_lon'] <= nvdb_way['max_lon'] and osm_way['max_lon'] >= nvdb_way['min_lon']:

				# Iterate all nodes in nvdb_way and identify distance from node to osm_way

				for node_nvdb in nvdb_way['nodes']:
					min_node_distance = margin_new
					prev_node_osm = osm_way['nodes'][0]

					for node_osm in osm_way['nodes'][1:]:
						line_lat, line_lon, node_distance = line_distance(nodes[prev_node_osm]['lat'], nodes[prev_node_osm]['lon'], \
													nodes[node_osm]['lat'], nodes[node_osm]['lon'], \
													nodes[node_nvdb]['lat'], nodes[node_nvdb]['lon'])
						prev_node_osm = node_osm

						if node_distance < min_node_distance:
							min_node_distance = node_distance
							min_node_ref = node_nvdb

							gap_test = {
								'lat1': nodes[node_nvdb]['lat'],
								'lon1': nodes[node_nvdb]['lon'],
								'lat2': line_lat,
								'lon2': line_lon,
								'distance': node_distance
							}

					# Include node in matched nodes list if closer distance than margin_new

					if min_node_distance < margin_new:
						if min_node_ref not in match_nodes:
							match_nodes.append(min_node_ref)

							if debug_gap:
								test_lines.append(gap_test)

		# No match if too few matched nodes
		# Otherwise calculate length of matched segment to check if sufficiently long (proportion of total length of nvdb_way)

		if len(match_nodes) >= min_nodes:
			match_length = 0
			prev_node = None

			for node in nvdb_way['nodes']:
				if prev_node in match_nodes and node in match_nodes:
					match_length += distance(nodes[prev_node]['lat'], nodes[prev_node]['lon'], \
											nodes[node]['lat'], nodes[node]['lon'])
				prev_node = node

			if match_length > new_factor * nvdb_way['length']:
				continue  # Successfull match, so do not include in output

		# No match, so include NVDB way in output

		ways_nvdb[ nvdb_id ]['missing'] = True
		count_missing += 1

	message ("\r%i missing highways" % count_missing)



# Prepare and output file

def output_file (osm_filename):

	global root_osm, tree_osm, root_nvdb, tree_nvdb

	message ("\nTransfer elements ...")

	count_modified_tag = 0

	# Empty start for "new" and "offset"

	if command in ["new", "offset"]:
		root_osm = ElementTree.Element("osm", version="0.6")
		tree_osm = ElementTree.ElementTree(root_osm)

	# Merge NVDB ways with OSM

	for way in root_osm.findall("way"):
		osm_id = way.attrib['id']

		# Replace geometry and tags

		if command == "replace" and "nvdb_id" in ways_osm[ osm_id ]:

			nvdb_id = ways_osm[ osm_id ]['nvdb_id'] 
			nvdb_way = ways_nvdb[ nvdb_id ]['index']

			for tag_osm in way.findall("tag"):
				if tag_osm.attrib['k'] in avoid_merge:
					way.remove(tag_osm)

			for tag_nvdb in nvdb_way.iter("tag"):
				tag_osm = way.find("tag[@k='%s']" % tag_nvdb.attrib['k'])
				if tag_nvdb.attrib['k'] == "highway":
					if tag_osm != None and tag_nvdb.attrib['v'] != tag_osm.attrib['v']:
						way.append(ElementTree.Element("tag", k="NVDB", v=tag_nvdb.attrib['v']))
				elif tag_osm != None:
					tag_osm.set("v", tag_nvdb.attrib['v'])
				else:
					way.append(ElementTree.Element("tag", k=tag_nvdb.attrib['k'], v=tag_nvdb.attrib['v']))

			if debug:
				way.append(ElementTree.Element("tag", k="OSMID", v=osm_id))
				way.append(ElementTree.Element("tag", k="SWAP", v=str(ways_nvdb[ nvdb_id ]['swap_no'])))
				way.append(ElementTree.Element("tag", k="DISTANCE", v=str(round(ways_nvdb[ nvdb_id ]['distance']))))

			for node in way.findall('nd'):
				nodes[ node.attrib['ref'] ]['used'] -= 1
				way.remove(node)

			for node in nvdb_way.iter("nd"):
				nodes[ node.attrib['ref'] ]['used'] += 1
				way.append(ElementTree.Element("nd", ref=node.attrib['ref']))

			way.set("action", "modify")

		# Remove way

		elif command == "replace" and "remove" in ways_osm[ osm_id ]:

			for node in way.findall('nd'):
				nodes[ node.attrib['ref'] ]['used'] -= 1
				way.remove(node)

			way.set("action", "delete")

		# Regplace tags only

		elif command == "tag" and "nvdb_id" in ways_osm[osm_id]:

			modified = False
			modified_tags = []
			nvdb_id = ways_osm[osm_id]['nvdb_id']

			for tag_nvdb in ways_nvdb[ nvdb_id ]['index'].findall("tag"):
				if tag_nvdb.attrib['k'] in update_tags:
					tag_osm = way.find("tag[@k='%s']" % tag_nvdb.attrib['k'])
					if tag_osm != None:
						if tag_nvdb.attrib['v'] != tag_osm.attrib['v']:
							modified_tags.append("Modified %s=%s to %s" % (tag_nvdb.attrib['k'], tag_osm.attrib['v'], tag_nvdb.attrib['v']))
							tag_osm.set("v", tag_nvdb.attrib['v'])
							modified = True
					else:
						way.append(ElementTree.Element("tag", k=tag_nvdb.attrib['k'], v=tag_nvdb.attrib['v']))
						modified_tags.append("Added %s=%s" % (tag_nvdb.attrib['k'], tag_nvdb.attrib['v']))
						modified = True

			if modified:
				count_modified_tag += 1
				way.set("action", "modify")
				way.append(ElementTree.Element("tag", k="EDIT", v=";".join(modified_tags)))
				if debug:
					way.append(ElementTree.Element("tag", k="NVDBID", v=nvdb_id))
					way.append(ElementTree.Element("tag", k="SWAP", v=str(ways_osm[ osm_id ]['swap_no'])))
					way.append(ElementTree.Element("tag", k="DISTANCE", v=str(round(ways_osm[ osm_id ]['distance']))))

	if command == "tag":
		message ("\nUpdated tags for %i highways" % count_modified_tag)

	# Transfer new NVDB ways to OSM

	for way in root_nvdb.findall("way"):
		nvdb_id = way.attrib['id']

		if command == "new" and ways_nvdb[ nvdb_id ]['missing'] or \
			command == "replace" and "osm_id" not in ways_nvdb[ nvdb_id ] or \
			command == "offset" and "osm_id" in ways_nvdb[ nvdb_id ]:

			if command == "offset":
				if ways_nvdb[ nvdb_id ]['highway'] != ways_osm[ ways_nvdb[nvdb_id]['osm_id'] ]['highway']:
					tag_highway = way.find("tag[@k='highway']")
					tag_highway.set("v", ways_osm[ ways_nvdb[nvdb_id]['osm_id'] ]['highway'])
					way.append(ElementTree.Element("tag", k="NVDB", v=ways_nvdb[ nvdb_id ]['highway']))
				if debug:
					way.append(ElementTree.Element("tag", k="OSMID", v=ways_nvdb[ nvdb_id ]['osm_id']))
					way.append(ElementTree.Element("tag", k="SWAP", v=str(ways_nvdb[ nvdb_id ]['swap_no'])))
					way.append(ElementTree.Element("tag", k="DISTANCE", v=str(round(ways_nvdb[ nvdb_id ]['distance']))))

			root_osm.append(way)
			for node in ways_nvdb[ nvdb_id ]['nodes']:
				nodes[ node ]['used'] += 1

	# Remove OSM nodes which are not used anymore

	for node in root_osm.iter("node"):
		node_id = node.attrib['id']
		tag = node.find("tag")

		if tag == None and nodes[ node_id ]['used'] == 0:
			node.set("action", "delete")

	# Add new NVDB nodes

	for node in root_nvdb.iter("node"):
		node_id = node.attrib['id']
		if node_id in nodes and nodes[ node_id ]['used'] > 0:
			root_osm.append(node)	

	# Remove possible historic NVDB tags from OSM

	for way in root_osm.findall("way"):
		tag = way.find("tag[@k='nvdb:id']")
		if tag != None:
			way.remove(tag)
		tag = way.find("tag[@k='nvdb:date']")
		if tag != None:
			way.remove(tag)	

	# Add distance markers for debugging

	if debug_gap:
		i = -1000000  # Try to avoid osm id conflicts
		for line in test_lines:
			way = ElementTree.Element("way", id=str(i), action="modify")
			root_osm.append(way)
			root_osm.append(ElementTree.Element("node", id=str(i-1), action="modify", lat=str(line['lat1']), lon=str(line['lon1'])))
			root_osm.append(ElementTree.Element("node", id=str(i-2), action="modify", lat=str(line['lat2']), lon=str(line['lon2'])))
			way.append(ElementTree.Element("nd", ref=str(i-1)))
			way.append(ElementTree.Element("nd", ref=str(i-2)))
			way.append(ElementTree.Element("tag", k="GAP", v=str(line['distance'])))
			i -= 3

	# Output file

	message ("\nSaving file ...")

	root_osm.set("generator", "highway_merge v"+version)
	root_osm.set("upload", "false")

	if filename_osm.find(".osm") >= 0:
		filename_out = filename_osm.replace(".osm", "_%s.osm" % command)
	else:
		filename_out = filename_osm + "_%s.osm" % command

	tree_osm.write(filename_out, encoding='utf-8', method='xml', xml_declaration=True)

	message ("\nSaved to file '%s'\n" % filename_out)


# Main program

if __name__ == '__main__':

	start_time = time.time()
	message ("\n*** highway_merge v%s ***\n" % version)

	if len(sys.argv) == 4 and sys.argv[1].lower() in ["-new", "-offset", "-replace", "-tag"]:
		command = sys.argv[1].lower().strip("-")
		filename_osm = sys.argv[2]
		filename_nvdb = sys.argv[3]
	else:
		message ("Please include 1) '-new'/'-offset'/'-replace'/'-tag' 2) OSM file and 3) NVDB file as parameters\n")
		sys.exit()

	message ("Loading files '%s' and '%s' ..." % (filename_osm, filename_nvdb))

	ways_osm = {}
	ways_nvdb = {}
	nodes = {}
	test_lines = []  # For debug

	load_files (filename_osm, filename_nvdb)

	if command == "new":
		add_new_highways()

	else:
		merge_highways (command)

	output_file (filename_osm)

	time_lapsed = time.time() - start_time
	message ("Time: %i seconds (%i ways per second)\n\n" % (time_lapsed, count_osm_roads / time_lapsed))
