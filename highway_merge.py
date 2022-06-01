#!/usr/bin/env python3
# -*- coding: utf8

# highway_merge.py
# Replace OSM highways with NVDB
# Usage: python highway_merge.py [command] [input_osm.osm] [input_nvdb.osm]
#    or: python highway_merge.py [command] [municipality name]
# Commands: - replace: Merge all existing OSM highways with NVDB
#			- offset: Include all NVDB highways above an certain average offset
#			- new: Include only NVDB highways not found in OSM
#			- tagref/taglocal: Update OSM highways with attributes from NVDB (maxspeed, name etc)
# Resulting file will be written to a new version of input file


import sys
import time
import math
import copy
import json
import os.path
import urllib.request, urllib.parse, urllib.error
from xml.etree import ElementTree


version = "3.0.0"

request_header = {"User-Agent": "osmno/highway_merge/" + version}

overpass_api = "https://overpass-api.de/api/interpreter"  # Overpass endpoint

import_folder = "~/Jottacloud/osm/nvdb/"  # Folder containing import highway files (default folder tried first)

nvdb_sweden_site = "https://nvdb-osm-map-data.s3.amazonaws.com/osm/"  # All Sweden .osm NVDB files

progress_filename = "progress/nvdb_tagging_progress.json"

country = "Norway"  # Argument "-swe" for Sweden



# Paramters for matching

debug = False       # True will provide extra keys in output file
debug_gap = False   # True will show gap/distance testing in output file
merge_all = False   # True will delete excess way from OSM if its NVDB match is already merged
save_progress = False  # Save progress report to file in the cloud

margin = 15         # Meters of tolarance for matching nodes
margin_new = 8      # Meters of tolerance for matching nodes, for "new" command
margin_tag = 5 		# Meters of tolerance for matching nodes, for "tagref"/"taglocal" command
margin_offset = 5   # Minimum average distance in meters for matching ways (used with "offset" command to filter large offsets)

match_factor = 0.3  # Minimum percent of length of way matched
new_factor = 0.6    # Ditto for "new" command
min_nodes = 2       # Min number of nodes in a way to be matched



# The following lists are for the replace command:

# Do not merge OSM ways with the folowing highway categories
avoid_highway = ["path", "bus_stop", "rest_area", "platform", "construction", "proposed"]

# Do not merge OSM ways with the following keys
avoid_tags = ["area", "railway", "piste:type", "snowmobile", "turn:lanes", "turn:lanes:forward", "turn:lanes:backward", \
			 "destination", "destination:forward", "destination:backward", "destination:ref", "destination:ref:forward", "destination:ref:backward", \
			 "destination:symbol", "destination:symbol:forward", "destination:symbol:backward", "mtb:scale", "class:bicycle:mtb"]

# Overwrite with the following tags from NVDB when merging ways, including deletion if not present in NVDB (not used by "-tagref" function)
replace_tags = ["ref", "name", "maxspeed", "oneway", "junction", "foot", "bridge", "tunnel", "layer", "source"]

# Do not consider OSM highways of the following types when updating tags
avoid_highway_tags = ["cycleway", "footway", "steps"]

# Pedestrian highways which should not be mixed with other highway classes for cars
pedestrian_highway = ["footway", "cycleway"]

# Only consider the following highway categories when merging (leave empty [] to merge all)
replace_highway = []
#replace_highway = ["motorway", "trunk", "primary", "secondary", "motorway_link", "trunk_link", "primary_link", "secondary_link"]
#replace_highway = ["primary", "secondary", "primary_link", "secondary_link"]

# + state_highway below



# The folloing lists are for the tagref/taglocal commands:

# Include the following tags from NVDB when marking tags in OSM for consideration
core_tags = ["highway", "ref", "oneway", "lanes", "junction", "name", "maxspeed", "maxheight", "maxweight", "maxlength", "motorroad", \
			 "motor_vehicle", "psv", "foot", "bicycle", "agriculatural", "hgv", "cycleway", \
			 "bridge", "tunnel", "layer", "bridge:description", "tunnel:name", "tunnel:description", "turn"]

# Include the following suffixes to the core tags above when reporting tags to consider
tag_suffixes = ["", ":lanes", ":forward", ":backward", ":lanes:forward", ":lanes:backward", ":left", ":right", ":both"]

# Do not update the following tags for the "-tagref" function
avoid_update_tags = ["ref", "highway", "oneway", "lanes", "surface"]

# Store progress report for the following tags
progress_tags = ["highway", "junction", "name", "maxspeed", "maxweight", "maxlength", "motorroad", \
				"motor_vehicle", "psv", "foot", "bicycle", "agricultural", "hgv", "cycleway", "bridge", "tunnel", "layer"]

# The following tags will be deleted
delete_tags = ["int_ref", "nvdb:id", "nvdb:date", "attribution", "maxspeed:type", "postal_code"]  # Also "source" handled in code

# The following tags will be deleted if the value is "no"
delete_negative_tags = ["sidewalk", "cycleway", "cycleway:both", "cycleway:right", "cycleway:left", "oneway", "lit", "island:crossing", "tactile_paving"]

# Public highways (national/county) which should not be mixed with other highway classes
state_highway = ["motorway", "trunk", "primary", "secondary", "motorway_link", "trunk_link", "primary_link", "secondary_link"]  # + "tertiary" included for Sweden

# Municipality highways in OSM to be matched with residential/pedestrian/tertiary/unclassified in NVDB
municipality_highway = ["residential", "unclassified", "tertiary", "tertiary_link", "pedestrian", "busway"]

force_ref = True  # True if ref in NVDB and OSM must match, for "-tagref" function



# Output message

def message (line):

	sys.stdout.write (line)
	sys.stdout.flush()



# Open file/api, try up to 6 times, each time with double sleep time

def open_url (url):

	tries = 0
	while tries < 6:
		try:
			return urllib.request.urlopen(url)
		except urllib.error.HTTPError as e:
			if e.code in [429, 503, 504]:  # Too many requests, Service unavailable or Gateway timed out
				if tries  == 0:
					message ("\n") 
				message ("\rRetry %i... " % (tries + 1))
				time.sleep(5 * (2**tries))
				tries += 1
				error = e
			elif e.code in [401, 403]:
				message ("\nHTTP error %i: %s\n" % (e.code, e.reason))  # Unauthorized or Blocked
				sys.exit()
			elif e.code in [400, 409, 412]:
				message ("\nHTTP error %i: %s\n" % (e.code, e.reason))  # Bad request, Conflict or Failed precondition
				message ("%s\n" % str(e.read()))
				sys.exit()
			else:
				raise
	
	message ("\nHTTP error %i: %s\n" % (error.code, error.reason))
	sys.exit()



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



# Test if line segments s1 and s2 are crossing.
# Segments have two nodes [(start.x, start.y), (end.x, end.y)].
# Source: https://en.wikipedia.org/wiki/Line–line_intersection#Given_two_points_on_each_line_segment

def crossing_lines (s1, s2):

	d1x = s1[1]['lon'] - s1[0]['lon']  # end1.x - start1.x
	d1y = s1[1]['lat'] - s1[0]['lat']  # end1.y - start1.y
	d2x = s2[1]['lon'] - s2[0]['lon']  # end2.x - start2.x
	d2y = s2[1]['lat'] - s2[0]['lat']  # end2.y - start2.y

	D = d1x * d2y - d1y * d2x

	if abs(D) < 0.0000000001:  # s1 and s2 are parallel
		return False

	A = s1[0]['lat'] - s2[0]['lat']  # start1.y - start2.y
	B = s1[0]['lon'] - s2[0]['lon']  # start1.x - start2.x

	r1 = (A * d2x - B * d2y) / D
	r2 = (A * d1x - B * d1y) / D

	if r1 < 0 or r1 > 1 or r2 < 0 or r2 > 1:
		return False
	'''
	# Compute intersection point

	x = s1[0]['lon'] + r1 * d1x
	y = s1[0]['lon'] + r1 * d1y
	intersection = (x, y)
	return (intersection)
	'''
	return True



# Identify municipality name, unless more than one hit
# Returns municipality number, or input parameter if not found

def get_municipality (parameter):

	if parameter.isdigit():
		return parameter

	else:
		parameter = parameter
		found_id = ""
		duplicate = False
		for mun_id, mun_name in iter(municipalities.items()):
			if parameter.lower() == mun_name.lower():
				return mun_id
			elif parameter.lower() in mun_name.lower():
				if found_id:
					duplicate = True
				else:
					found_id = mun_id

		if found_id and not duplicate:
			return found_id
		else:
			return parameter



# Load dict of all municipalities

def load_municipalities(country):

	if country == "Sweden":
		url = "https://catalog.skl.se/rowstore/dataset/b80d412c-9a81-4de3-a62c-724192295677?_limit=400"
		file = urllib.request.urlopen(url)
		data = json.load(file)
		file.close()
		for municipality in data['results']:
			municipalities[ municipality['kommunkod'] ] = municipality['kommun']

	else:  # Default Norway
		url = "https://ws.geonorge.no/kommuneinfo/v1/fylkerkommuner?filtrer=fylkesnummer%2Cfylkesnavn%2Ckommuner.kommunenummer%2Ckommuner.kommunenavnNorsk"
		file = urllib.request.urlopen(url)
		data = json.load(file)
		file.close()
		for county in data:
			for municipality in county['kommuner']:
				municipalities[ municipality['kommunenummer'] ] = municipality['kommunenavnNorsk']



# Load OSM or NVDB xml data and build list and dicts for later processing

def load_xml(root, ways):

	# Prepare nodes

	count_nodes = 0

	for node in root.iter("node"):
		if not("action" in node.attrib and node.attrib['action'] == "delete"):
			nodes[ node.attrib['id'] ] = {
				'xml': node,
				'used': 0,  # Will have a value larger than zero at time of output to avoid deletion
				'lat': float(node.attrib['lat']),
				'lon': float(node.attrib['lon'])
			}

			# Remove node tags used by early editors
			for tag in node.iter("tag"):
				if tag.attrib['k'] == "created_by":
					node.remove(tag)
					node.set("action", "modify")

			count_nodes += 1

	# Determine bounding box and length of OSM ways

	count_roads = 0

	for way in root.iter("way"):
		way_id = way.attrib['id']

		length = 0
		way_nodes = []
		tags = {}
		highway = None
		ref = None
		incomplete = False
		avoid_match = False
		min_lat = 0.0
		min_lon = 0.0
		max_lat = 0.0
		max_lon = 0.0

		# Iterate tags to determine if way should be excluded

		for tag in way.iter("tag"):
			key = tag.attrib['k']
			if key in avoid_tags:
				avoid_match = True
			if key == "highway":
				highway = tag.attrib['v']
				if highway not in avoid_highway:
					count_roads += 1
			if key == "ref":
				ref = tag.attrib['v']
			tags[ key ] = tag.attrib['v']

		# Iterate nodes to determine if way is complete

		if ways == osm_ways:
			for node in way.iter("nd"):
				node_id = node.attrib['ref']
				if node_id in nodes:
					nodes[ node_id ]['used'] += 1
				elif not("action" in node.attrib and node.attrib['action'] == "delete"):
					incomplete = True

		if "action" in way.attrib and way.attrib['action'] == "delete" or "area" in tags and tags['area'] == "yes":
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
		ways[ way_id ] = {
			'xml': way,
			'highway': highway,
			'ref': ref,
			'incomplete': incomplete,
			'avoid_tag': avoid_match,  # Not used for NVDB
			'min_lat': min_lat - margin / 111500.0,
			'max_lat': max_lat + margin / 111500.0,
			'min_lon': min_lon - margin / (math.cos(math.radians(min_lat)) * 111320.0),
			'max_lon': max_lon + margin / (math.cos(math.radians(max_lat)) * 111320.0),
			'length': length,
			'nodes': way_nodes,
			'tags': tags,
			'relations': set()  # Not used for NVDB
		}

	# Determine which nodes and ways are used by relation (should be kept)

	if ways == osm_ways:
		for relation in root.iter("relation"):
			for member in relation.iter("member"):
				if member.attrib['type'] == "node" and member.attrib['ref'] in nodes:
					nodes[ member.attrib['ref'] ]['used'] += 1
				elif member.attrib['type'] == "way" and member.attrib['ref'] in ways:
					ways[ member.attrib['ref'] ]['relations'].add( relation.attrib['id'] )

	return count_roads	



# Load files and build data structure for analysis

def load_files (name_osm):

	global tree_osm, root_osm, tree_nvdb, root_nvdb, count_osm_roads, filename_osm, filename_nvdb

	# Load OSM file

	municipality_id = None

	if ".osm" not in name_osm.lower():
		municipality_id = get_municipality(name_osm)

		if municipality_id in municipalities:
			message ("Loading municipality %s %s from OSM ... " % (municipality_id, municipalities[municipality_id]))
			filename_osm = "nvdb_%s_%s" % (municipality_id, municipalities[municipality_id].replace(" ", "_"))

			if country == "Sweden":
				filename_nvdb = municipalities[municipality_id] + ".osm"
				query = '[timeout:90];(area["ref:scb"=%s][admin_level=7];)->.a;(nwr["highway"](area.a););(._;>;<;);out meta;' % municipality_id
			else:  # Norway
				filename_nvdb = filename_osm + ".osm"
				query = '[timeout:90];(area[ref=%s][admin_level=7][place=municipality];)->.a;(nwr["highway"](area.a););(._;>;<;);out meta;' % municipality_id

			if command not in ["new", "offset"]:
				query = query.replace('nwr["highway"](area.a);', 'nwr["highway"](area.a);nwr["railway"](area.a);nwr["man_made"="bridge"](area.a);')	

			filename_osm += ".osm"
			request = urllib.request.Request(overpass_api + "?data=" + urllib.parse.quote(query), headers=request_header)
			file = open_url(request)
			data = file.read()
			file.close()

			root_osm = ElementTree.fromstring(data)
			tree_osm = ElementTree.ElementTree(root_osm)

		else:
			sys.exit("\n*** Municipality '%s' not found\n\n" % name_osm)
	else:
		message ("Loading file '%s' ... " % name_osm)
		if os.path.isfile(name_osm):
			tree_osm = ElementTree.parse(name_osm)
			root_osm = tree_osm.getroot()
		else:
			sys.exit("\n*** File '%s' not found\n\n" % name_osm)

	count_osm_roads = load_xml(root_osm, osm_ways)
	message ("%i highways loaded\n" % count_osm_roads)

	# Load NVDB file

	if country == "Sweden":
		request = urllib.request.Request(nvdb_sweden_site + urllib.parse.quote(filename_nvdb), headers=request_header)
		try:
			file = urllib.request.urlopen(request)
		except urllib.error.HTTPError:
			sys.exit("\n*** File '%s' not available\n\n" % (nvdb_sweden_site + filename_nvdb))
		message ("Loading file '%s' ... " % filename_nvdb)
		data = file.read()
		tree_nvdb = ElementTree.ElementTree(ElementTree.fromstring(data))

	else:  # Norway
		full_filename_nvdb = filename_nvdb
		if not os.path.isfile(full_filename_nvdb):
			test_filename = os.path.expanduser(import_folder + filename_nvdb)
			if os.path.isfile(test_filename):
				full_filename_nvdb = test_filename
			else:
				sys.exit("\n*** File '%s' not found\n\n" % filename_nvdb)

		message ("Loading file '%s' ... " % full_filename_nvdb)
		tree_nvdb = ElementTree.parse(full_filename_nvdb)

	root_nvdb = tree_nvdb.getroot()
	count_nvdb_roads = load_xml(root_nvdb, nvdb_ways)
	message ("%i highways loaded\n" % count_nvdb_roads)

	return municipality_id



# Compute length of way in metres.

def way_length(way_nodes):

	way_distance = 0.0

	if len(way_nodes) > 1:
		prev_node = None
		for node in way_nodes:
			if prev_node:
				way_distance += distance(nodes[prev_node]['lat'], nodes[prev_node]['lon'], \
											nodes[node]['lat'], nodes[node]['lon'])
			prev_node = node

	return way_distance



# Compute length of way part in metres.
# Only compute distance between nodes given by index.

def partial_way_length(way_nodes, match_index):

	match_nodes = [way_nodes[node] for node in match_index]
	way_distance = 0.0

	if len(way_nodes) > 1 and len(match_nodes) > 1:
		prev_node = None

		for node in way_nodes:
			if prev_node in match_nodes and node in match_nodes:
				way_distance += distance(nodes[prev_node]['lat'], nodes[prev_node]['lon'], \
										nodes[node]['lat'], nodes[node]['lon'])
			prev_node = node

	return way_distance



# Compare part of way 1 with way 2 to determine if they match.
# Include only segments of the ways which are closer than margin parameter.
# Return average distance of matched nodes + index of matched nodes.

def match_ways (way1, way2, start_node, end_node, margin, trim_end = False):

	way_distance = 0.0
	count_distance = 0
	match_nodes = []
	match_distances = []

	# Iterate all nodes in way1 and identify distance from node to way2

	for i, node1 in enumerate(way1['nodes'][ start_node : end_node + 1]):
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
			match_nodes.append(i + start_node)
			match_distances.append(min_node_distance)

			if debug_gap:
				test_lines.append(gap_test)

	# Remove runoff nodes at each end

	if trim_end and count_distance > 0:
		for backward in [False, True]:

			test_nodes = match_nodes.copy()
			test_distances = match_distances.copy()
			if backward:
				test_nodes.reverse()
				test_distances.reverse()

			end_length = 0

			while test_distances[0] > 0.5 * margin and len(test_distances) > 1:  # and test_distances[1] < test_distances[0]:
				node = nodes[ way1['nodes'][ test_nodes[1] ]]
				last_node = nodes[ way1['nodes'][ test_nodes[0] ]]
				end_length += distance(last_node['lat'], last_node['lon'], node['lat'], node['lon'])
				if end_length > margin:
					break
				test_distances.pop(0)
				test_nodes.pop(0)

			if backward:
				test_nodes.reverse()
				test_distances.reverse()

		if test_nodes != match_nodes:
			match_nodes = test_nodes
			match_distances = test_distances
			count_distance = len(match_nodes)
			way_distance = sum(match_distances)


	# Return average gap and matched nodes

	if count_distance > 0:
		average_distance = way_distance / count_distance
	else:
		average_distance = None

	return (average_distance, match_nodes)




# Merge NVDB and OSM highways for the commands "replace", "offset" and "tag"

def merge_highways(command):

	message ("Merge highways ...\n")

	count = count_osm_roads
	count_swap = 0
	total_distance = 0

	# Pass 1: Match topology
	# Iterate OSM ways to identify best match with NVDB way

	for osm_id, osm_way in iter(osm_ways.items()):

		if not osm_way['incomplete'] and osm_way['highway'] != None and osm_way['highway'] not in avoid_highway:

			message ("\r%i " % count)
			count -= 1

			best_id = None
			best_distance = 99999.0

			for nvdb_id, nvdb_way in iter(nvdb_ways.items()):

				# Avoid ways with no overlapping bbox or with incompatible relative lengths
				if nvdb_way['min_lat'] <= osm_way['max_lat'] and nvdb_way['max_lat'] >= osm_way['min_lat'] and \
					nvdb_way['min_lon'] <= osm_way['max_lon'] and nvdb_way['max_lon'] >= osm_way['min_lon'] and \
					osm_way['length'] > match_factor * nvdb_way['length'] and nvdb_way['length'] > match_factor * osm_way['length']:

					# Avoid mixing pedestrian and car highways
					if nvdb_way['highway'] in pedestrian_highway and osm_way['highway'] not in pedestrian_highway + ["track"] or \
						nvdb_way['highway'] not in pedestrian_highway and osm_way['highway'] in pedestrian_highway:
						continue

					# Avoid mixing trunk etc with lower highway classes
					if nvdb_way['highway'] in state_highway and osm_way['highway'] not in state_highway + ['tertiary'] or \
						osm_way['highway'] in state_highway and nvdb_way['highway'] not in state_highway + ['road', 'tertiary']:
						continue

					# Check if match between OSM and NVDB way, and determine if closest distance between them

					match_distance, match_nodes = match_ways(nvdb_way, osm_way, 0, len(nvdb_way['nodes']) - 1, margin)
					if len(match_nodes) >= min_nodes and match_distance < best_distance and \
							partial_way_length(nvdb_way['nodes'], match_nodes) > match_factor * nvdb_way['length']:

						# Also check reverse match
						reverse_distance, reverse_nodes = match_ways(osm_way, nvdb_way, 0, len(osm_way['nodes']) - 1, margin)
						if len(reverse_nodes) >= min_nodes and reverse_distance < margin and \
								partial_way_length(osm_way['nodes'], reverse_nodes) > match_factor * osm_way['length']:
							best_id = nvdb_id
							best_distance = match_distance

			# Store match in data structure, if any match

			if best_id is not None:
				if command in ["replace", "offset"]:

					# Replace earlier match if new match is better

					if "osm_id" in nvdb_ways[ best_id ] and nvdb_ways[ best_id ]['distance'] > best_distance:
						count_swap -= 1
						total_distance -= nvdb_ways[ best_id ]['distance']
						del osm_ways[ nvdb_ways[ best_id ]['osm_id'] ]['nvdb_id']
						del nvdb_ways[ best_id ]['osm_id']

					if "osm_id" not in nvdb_ways[ best_id ]:
						count_swap += 1
						total_distance += best_distance
						osm_ways[ osm_id ]['nvdb_id'] = best_id
						nvdb_ways[ best_id ]['osm_id'] = osm_id
						nvdb_ways[ best_id ]['order'] = count_swap  # Debug
						nvdb_ways[ best_id ]['distance'] = best_distance  # Debug

					elif merge_all:
						osm_ways[ osm_id ]['remove'] = True  # Remove redundant way if it got a match

				elif command == "tag":
					count_swap += 1
					total_distance += best_distance
					osm_ways[ osm_id ]['nvdb_id'] = best_id
					osm_ways[ osm_id ]['order'] = count_swap  # Debug
					osm_ways[ osm_id ]['distance'] = best_distance  # Debug

	# Pass 2: Match type highway
	# Remove matches to be avoided before output

	if command == "offset":
		for nvdb_id, nvdb_way in iter(nvdb_ways.items()):
			if "osm_id" in nvdb_way and (nvdb_way['distance'] < margin_offset or osm_ways[ nvdb_way['osm_id'] ]['highway'] in avoid_highway or \
					replace_highway and (osm_way['highway'] not in replace_highway or nvdb_ways[ osm_way['nvdb_id'] ]['highway'] not in replace_highway)):
				count_swap -= 1
				total_distance -= nvdb_way['distance']				
				del nvdb_ways[ nvdb_id ]['osm_id']

	elif command == "replace":
		for osm_id, osm_way in iter(osm_ways.items()):
			if "nvdb_id" in osm_way and (osm_way['avoid_tag'] or \
					replace_highway and (osm_way['highway'] not in replace_highway or nvdb_ways[ osm_way['nvdb_id'] ]['highway'] not in replace_highway)):
				count_swap -= 1
				total_distance -= nvdb_ways[ osm_way['nvdb_id'] ]['distance']
				del nvdb_ways[ osm_way['nvdb_id'] ]['osm_id']
				del osm_ways[ osm_id ]['nvdb_id']

	elif command == "tag":
		for osm_id, osm_way in iter(osm_ways.items()):
			if "nvdb_id" in osm_way and (osm_way['highway'] in avoid_highway or \
					replace_highway and (osm_way['highway'] not in replace_highway or nvdb_ways[ osm_way['nvdb_id'] ]['highway'] not in replace_highway)):
				count_swap -= 1
				total_distance -= osm_way['distance']
				del osm_ways[ osm_id ]['nvdb_id']

	# Report result

	message ("\r  \t%i highways matched, %i not matched\n" % (count_swap, count_osm_roads - count_swap))
	if command == "replace":
		message ("\t%i missing highways added from NVDB\n" % (len(nvdb_ways) - count_swap))
	message ("\tAverage offset: %.1f m\n" % (total_distance / count_swap))



# Identify missing NVDB highways, for "new" command.
# NVDB ways may be matched with any and several OSM ways. If match is long enough, the way will not be included as missing.

def add_new_highways():

	message ("Add missing highways ...\n")

	count = len(nvdb_ways)
	count_missing = 0

	# Iterate NVDB ways to check if match with any OSM way.
	# Does not identify the best match, but checks how many nodes have a match with any highway.

	for nvdb_id, nvdb_way in iter(nvdb_ways.items()):
		message ("\r%i " % count)
		count -= 1

		if not nvdb_way['highway']:  # Skip ferries etc
			continue

		match_nodes = set()

		for osm_id, osm_way in iter(osm_ways.items()):

			# Avoid testing ways with no overlapping bbox
			if not osm_way['incomplete'] and osm_way['highway'] != None and osm_way['highway'] not in avoid_highway and \
				osm_way['min_lat'] <= nvdb_way['max_lat'] and osm_way['max_lat'] >= nvdb_way['min_lat'] and \
				osm_way['min_lon'] <= nvdb_way['max_lon'] and osm_way['max_lon'] >= nvdb_way['min_lon']:

				test_distance, test_match_nodes = match_ways(nvdb_way, osm_way, 0, len(nvdb_way['nodes']) - 1, margin_new)
				match_nodes.update(test_match_nodes)

			if len(match_nodes) == len(nvdb_way['nodes']):  # Break if all nodes already have match
				break

		# Include way as missing if matching partitions are not long enough
		match_length = partial_way_length(nvdb_way['nodes'], match_nodes)
		if match_length < new_factor * nvdb_way['length']:
			nvdb_ways[ nvdb_id ]['missing'] = "%i" % match_length
			count_missing += 1

	message ("\r  \t%i missing highways\n" % count_missing)



# Find which node in a way which is closest to another given node 

def closest_node(way, target_node):

	best_node_gap = margin
	best_node = None

	for i, node in enumerate(way['nodes']):
		test_gap = distance(nodes[ node ]['lat'], nodes[ node ]['lon'], nodes[ target_node ]['lat'], nodes[ target_node ]['lon'])
		if test_gap < best_node_gap:
			best_node_gap = test_gap
			best_node = i

	return best_node



# Get the new tags, given tags1 as old tags and tags2 as new/target tags.
# Several exceptions to avoid undesired deletions or inclusions.

def update_tags(tags1, tags2):

	new_tags = {}  # copy.copy(tags1)

	target_tags = tags2
	if "highway" in tags2 and tags2['highway'] in ["unclassified", "service"]:
		target_tags = {}
		for key, value in iter(tags2.items()):
			if key in ["name", "bridge", "tunnel", "layer", "foot", "bicycle", "motor_vehicle", "psv"]:
				target_tags[key] = value

	for key, value in iter(target_tags.items()):
		if key not in avoid_update_tags and ":lanes" not in key and "|" not in value and \
				":forward" not in key and ":backward" not in key and ":left" not in key and ":right" not in key and \
				not (key == "name" and "name" in tags1 and \
					("bridge" in tags1 and ("bru" in tags1["name"].lower() or "bro" in tags1["name"].lower()) or \
					("tunnel" in tags1 and ("tunnel" in tags1["name"] or "port" in tags1['name'].lower() or "lokk" in tags1['name'].lower())))) and \
				not (key == "bridge:description" and "name" in tags1 and tags1['name'] == value) and \
				not (key == "tunnel:name" and "name" in tags1 and tags1['name'] == value) and \
				not (key == "bridge" and "bridge" in tags1) and \
				not (key == "tunnel" and "tunnel" in tags1) and \
				not (key == "layer" and "layer" in tags1 and ("-" in value) == ("-" in tags1['layer'])) and \
				not (key == "maxspeed" and ("maxspeed:forward" in tags1 or "maxspeed:backward" in tags1)):
#				not (key == "surface" and value == "asphalt"):

			new_tags[ key ] = value

	return new_tags



# Update tagging of public highways containing the ref=* tag, without replacing geometry.
# OSM ways are split to match the NVDB ways, then concatenated if tags are equal.

def tag_highways():

	global new_id

	message ("Match and retag highways ...\n")

	# Prepare segments to be matched

	for osm_id, osm_way in iter(osm_ways.items()):
		if osm_way['highway'] != None and osm_way['highway'] in public_highway and not osm_way['incomplete']:
			if osm_way['ref']:
				ref = osm_way['ref'].split(";")  # May have multiple ref=*
			else:
				ref = []
			segment = {
				'id': osm_id,
				'highway': osm_way['highway'],
				'ref': ref,
				'length': osm_way['length'],
				'nodes': copy.copy(osm_way['nodes']),
				'tags': copy.copy(osm_way['tags']),
				'new_tags': copy.copy(osm_way['tags']),
				'relations': copy.copy(osm_way['relations'])
			}
			segments.append(segment)
			segment_groups[ osm_id ] = [ segment ]  # Will contain split segments in order

	# Identify start/end nodes of public highways

	osm_public_end_nodes = {}  # Used later when combining segments
	for osm_id, osm_way in iter(osm_ways.items()):
		if osm_way['highway'] != None and osm_way['highway'] in public_highway + state_highway and not osm_way['incomplete']:
			for node_id in [ osm_way['nodes'][0], osm_way['nodes'][-1] ]:
				if node_id not in osm_public_end_nodes:
					osm_public_end_nodes[ node_id ] = 1
				else:
					osm_public_end_nodes[ node_id ] += 1

	nvdb_public_end_nodes = set()
	for nvdb_id, nvdb_way in iter(nvdb_ways.items()):
		if nvdb_way['highway'] in public_highway and nvdb_way['highway'] != "service":  # and nvdb_way['ref'] is not None:
			nvdb_public_end_nodes.add(nvdb_way['nodes'][0])
			nvdb_public_end_nodes.add(nvdb_way['nodes'][-1])

	# Insert end nodes from NVDB to simplify later matching

	for end_node in nvdb_public_end_nodes:
		for segment in segments:
			osm_way = osm_ways[ segment['id'] ]

			if 	osm_way['min_lat'] <= nodes[ end_node ]['lat'] <= osm_way['max_lat']  and \
				osm_way['min_lon'] <= nodes[ end_node ]['lon'] <= osm_way['max_lon']:

				# Identify position of closest node in OSM segment

				best_distance = margin

				prev_node = segment['nodes'][0]
				for i, node in enumerate(segment['nodes'][1:]):
					line_lat, line_lon, node_distance = line_distance(nodes[prev_node]['lat'], nodes[prev_node]['lon'], \
															nodes[node]['lat'], nodes[node]['lon'], \
															nodes[end_node]['lat'], nodes[end_node]['lon'])
					if node_distance < best_distance:
						best_distance = node_distance
						best_node = i + 1
						best_lat = line_lat
						best_lon = line_lon

					prev_node = node

				# Insert node if gap to next existing node is big enough

				if best_distance < margin:
					node1 = nodes[ segment['nodes'][ best_node - 1 ] ]
					node2 = nodes[ segment['nodes'][ best_node ] ]
					dist1 = distance(node1['lat'], node1['lon'], best_lat, best_lon)
					dist2 = distance(node2['lat'], node2['lon'], best_lat, best_lon)

					if dist1 > margin_tag and dist2 > margin_tag:
						new_id -= 1
						best_lat = round(best_lat, 7)
						best_lon = round(best_lon, 7)

						nodes[ str(new_id) ] = {
							'xml': None,  # To be created at the end of this function
							'used': 1,      # Note: Not maintained for these nodes
							'lat': best_lat,
							'lon': best_lon
						}
						segment['nodes'].insert(best_node, str(new_id))

	# Remove from NVDB short bridges which crosses a tunnel, or vice versa for tunnels

	count = 0
	for nvdb_id, nvdb_way in iter(nvdb_ways.items()):
		if "tunnel" in nvdb_way['tags'] or "bridge" in nvdb_way['tags'] and nvdb_way['nodes'] and nvdb_way['length'] < 50:
			for osm_id, osm_way in iter(osm_ways.items()):
				if ("tunnel" in nvdb_way['tags'] and "bridge" in osm_way['tags'] or \
						"bridge" in nvdb_way['tags'] and "tunnel" in osm_way['tags']) and \
						osm_way['nodes']:  # and osm_way['length'] < 50:
					if crossing_lines([ nodes[ nvdb_way['nodes'][0] ], nodes[ nvdb_way['nodes'][-1] ]], \
										[ nodes[ osm_way['nodes'][0] ], nodes[ osm_way['nodes'][-1] ]]):

						osm_way['bridge_tunnel'] = nvdb_id  # Mark for later tests
						for key in list(nvdb_way['tags']):
							if "tunnel" in key or "bridge" in key or "layer" in key:
								del nvdb_way['tags'][ key ]
						count += 1

	message ("\tSwapped %i intersecting bridges/tunnels\n" % count)

	# Match segments

	count_first_match = 0

	segment_index = 0
	while segment_index < len(segments):
		segment = segments[ segment_index ]
		osm_way = osm_ways[ segment['id'] ]
		segment_index += 1
		message ("\r%i " % (len(segments) - segment_index))

		best_distance = 9999
		match_nodes = []
		match_nvdb = None
		nvdb_ref = None

		# First identify the closest match, disregarding ref=*

		for nvdb_id, nvdb_way in iter(nvdb_ways.items()):
			if nvdb_way['highway'] in public_highway and nvdb_way['highway'] != "service" and \
					(nvdb_way['length'] > margin_tag or segment['length'] < margin_tag) and \
					osm_way['min_lat'] <= nvdb_way['max_lat'] and osm_way['max_lat'] >= nvdb_way['min_lat'] and \
					osm_way['min_lon'] <= nvdb_way['max_lon'] and osm_way['max_lon'] >= nvdb_way['min_lon']:

				# Match start and end node of NVDB way to limit matching area

				node1 = closest_node(segment, nvdb_way['nodes'][0])
				node2 = closest_node(segment, nvdb_way['nodes'][-1])

				if node1 != None and node2 != None and nvdb_way['nodes'][0] != nvdb_way['nodes'][-1]:
					start_node = min(node1, node2)
					end_node = max(node1, node2)
				else:
					start_node = 0
					end_node = len(nvdb_way['nodes']) - 1

				# Iterate all nodes in nvdb_way and identify average distance from node to osm_way
				test_distance, test_nodes = match_ways(segment, nvdb_way, start_node, end_node, 2 * margin_tag, trim_end=True)

				if len(test_nodes) >= min_nodes and test_distance < best_distance:
					test_length = way_length(segment['nodes'][ test_nodes[0] : test_nodes[-1] + 1 ])

					# Avoid very short segments + avoid matching to almost perpendicular highway
					if test_length > margin_tag or segment['length'] <= margin_tag:
						best_distance = test_distance
						match_nodes = test_nodes
						match_nvdb = nvdb_id

		if match_nvdb and nvdb_ways[match_nvdb]['ref']:
			nvdb_ref = nvdb_ways[match_nvdb]['ref'].split(";")[0]  # Avoid "Ring" ref

		# No match if too few matched nodes, if wrong ref or across roundabout.
		# Otherwise calculate length of matched segment to check if sufficiently long.

		if best_distance < margin_tag and (nvdb_ref in segment['ref'] or not force_ref) and \
 				("junction" in segment['tags'] and segment['tags']['junction'] == "roundabout") == \
				("junction" in nvdb_ways[match_nvdb]['tags'] and nvdb_ways[match_nvdb]['tags']['junction'] == "roundabout"):

			start_length = way_length(segment['nodes'][ : match_nodes[0] + 1])
			match_length = way_length(segment['nodes'][ match_nodes[0] : match_nodes[-1] + 1 ])
			end_length = way_length(segment['nodes'][ match_nodes[-1] : ])

			if match_length > margin_tag or segment['length'] <= margin_tag:

				segment_group = segment_groups[ segment['id'] ]
				segment_group_index = segment_group.index(segment)
				segment_nodes = copy.copy(segment['nodes'])

				# Split segment at the start
				if start_length > margin_tag:
					new_segment = copy.deepcopy(segment)
					new_segment['nodes'] = segment_nodes[ : match_nodes[0] + 1]
					new_segment['length'] = start_length
					segments.insert(segment_index, new_segment)
					segment['nodes'] = segment['nodes'][ match_nodes[0] : ]
					segment['length'] -= start_length
					if start_length > match_length and start_length > end_length:
						segment['new'] = True
					else:
						new_segment['new'] = True

					segment_group.insert(segment_group_index, new_segment)  # Insert before
					segment_group_index += 1

				# Split segment at the end
				if end_length > margin_tag:
					new_segment = copy.deepcopy(segment)
					new_segment['nodes'] = segment_nodes[ match_nodes[-1] : ]
					new_segment['length'] = end_length
					segments.insert(segment_index, new_segment)
					segment['nodes'] = segment['nodes'][ : 1 - len(new_segment['nodes']) ]
					segment['length'] -= end_length
					if end_length > match_length:
						segment['new'] = True
					else:
						new_segment['new'] = True

					segment_group.insert(segment_group_index + 1, new_segment)  # Insert after

				segment['nvdb_id'] = match_nvdb
				segment['new_tags'] = segment['tags']
				segment['new_tags'].update(update_tags(segment['tags'], nvdb_ways[ match_nvdb ]['tags']))
				count_first_match += 1

		segment['distance'] = best_distance
		segment['order'] = segment_index


	# Try to combine segments with identical tags

	for osm_id, segment_group in iter(segment_groups.items()):

		# Restore/merge segments within same group which have same tags

		last_segment = segment_group[0]
		for segment in segment_group[1:]:
			if not debug and (segment['new_tags'] == last_segment['new_tags'] or \
					(("nvdb_id" not in segment or "new" in segment) and segment['length'] < margin or \
					("nvdb_id" not in last_segment or "new" in last_segment) and last_segment['length'] < margin) and \
						all((key in segment['new_tags']) == (key in last_segment['new_tags']) for key in ["tunnel", "bridge", "maxheight"])):

				last_segment['nodes'] += segment['nodes'][1:]
				if not "new" in segment and "new" in last_segment:
					del last_segment['new']
				if "nvdb_id" in segment and ("nvdb_id" not in last_segment or segment['length'] > last_segment['length']):
					last_segment['nvdb_id'] = segment['nvdb_id']
					last_segment['distance'] = segment['distance']
					last_segment['new_tags'] = segment['new_tags']

				last_segment['length'] += segment['length']
				segments.remove(segment)
				segment_group.remove(segment)
			else:
				last_segment = segment

		# Check if new segment could be merge with segment from neighbour group.
		# If the new segment is shorter than a margin, then it will get the tags of its neighbour.

		for position in [0, -1]:
			segment1 = segment_group[ position ]
			if "new" in segment1 and (segment1['nodes'][ position ] not in osm_public_end_nodes or \
					osm_public_end_nodes[ segment1['nodes'][ position ] ] == 2) and not debug:

				for segment2 in segments:
					if segment1['relations'] == segment2['relations'] and \
							segment1['new_tags'] == segment2['new_tags'] and segment1 != segment2:
							# Note: Old tags might be different. Might be different roles in restriction relations.

						found = False

						if position == 0:  # First segment
							if segment2['nodes'][-1] == segment1['nodes'][0]:
								segment2['nodes'] += segment1['nodes'][1:]
								found = True
							elif segment2['nodes'][0] == segment1['nodes'][0] and "oneway" not in segment1['new_tags']:
								segment2['nodes'] = segment1['nodes'][::-1] + segment2['nodes'][1:]
								found = True

						else:  # Last segment
							if segment2['nodes'][0] == segment1['nodes'][-1]:
								segment2['nodes'] = segment1['nodes'] + segment2['nodes'][1:]
								found = True
							elif segment2['nodes'][-1] == segment1['nodes'][-1] and "oneway" not in segment1['new_tags']:
								segment2['nodes'] += segment1['nodes'][::-1][1:]
								found = True							

						if found:
							segment2['length'] += segment['length']
							segment_group.remove(segment1)
							segments.remove(segment1)
							break

	# Check if new intersection nodes have been used

	count_match = 0
	count_new_segments = 0
	count_new_nodes = 0

	for segment in segments:

		# Remove unused nodes from NVDB intersections
		if not debug:
			new_nodes = [ segment['nodes'][0] ]
			for node in segment['nodes'][1:-1]:
				if node[0] == "-":
					del nodes[ node ]
				else:
					new_nodes.append(node)
			new_nodes.append(segment['nodes'][-1])
			segment['nodes'] = new_nodes

			check_nodes = [0, -1]
		else:
			check_nodes = range(len(segment['nodes']) - 1)

		# Create new intersections nodes in XML
		for end_node in check_nodes:
			node = segment['nodes'][end_node]
			if nodes[node]['xml'] is None:
				new_node = root_osm.append(ElementTree.Element("node", id=node, action="modify", \
											lat=str(nodes[node]['lat']), lon=str(nodes[node]['lon'])))
				nodes[node]['xml'] = new_node	
				count_new_nodes += 1

		if "new" in segment:
			count_new_segments += 1
		if "nvdb_id" in segment:
			count_match += 1			

	message ("\r  \tMatched %i highway segments, %i not matched\n" % (count_match, len(segments) - count_match))
	message ("\tAdded %i new highway segments\n" % count_new_segments)
	message ("\tInserted %i new intersection nodes from NVDB\n" % count_new_nodes)



# Indent XML output

def indent_tree(elem, level=0):
    i = "\n" + level*"  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for elem in elem:
            indent_tree(elem, level+1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i



# Fix relations.
# Run this function after id's for new elemenets has been assigned.
# Segments in segment_groups must already be ordered, but direction is not important.

def update_relations():

	updated_relations = set()

	for osm_id, segment_group in iter(segment_groups.items()):

		if len(segment_group) < 2:
			continue

		for relation_id in segment_group[0]['relations']:
			relation = root_osm.find("relation[@id='%s']" % relation_id)
			if relation is None:
				continue

			# Get relation members and position of original way

			members = []
			group_members = [segment['id'] for segment in segment_group]
			position = None
			via = None

			for member in relation.findall("member"):
				members.append(member.attrib['ref'])
				if "role" in member.attrib and member.attrib['role'] == "via":
					via = member.attrib['ref']

			# Keep looking for multiple cases of same ref in relation

			position = 0
			while position < len(members):
				if members[ position ] == osm_id:

					# Prepare sets for determining order of segments in group

					segment_start = set({ segment_group[0]['nodes'][0], segment_group[0]['nodes'][-1] })
					segment_end = set({ segment_group[-1]['nodes'][0], segment_group[-1]['nodes'][-1] })

					if position == 0 or members[position-1] not in osm_ways or \
							"nodes" not in osm_ways[members[position-1]] or not osm_ways[members[position-1]]['nodes']:
						member_before = set()
					else:
						member_before = set({ osm_ways[members[position-1]]['nodes'][0], osm_ways[members[position-1]]['nodes'][-1] })
				
					if position == len(members) - 1 or members[position+1] not in osm_ways or \
							"nodes" not in osm_ways[members[position+1]] or not osm_ways[members[position+1]]['nodes']:
						member_after = set()
					else:
						member_after = set({ osm_ways[members[position+1]]['nodes'][0], osm_ways[members[position+1]]['nodes'][-1] })

					if segment_start.intersection(member_before) and segment_end.intersection(member_after):
						new_members = group_members
					elif segment_end.intersection(member_before) and segment_start.intersection(member_after):
						new_members = group_members[::-1]
					elif segment_start.intersection(member_before) or segment_end.intersection(member_after):
						new_members = group_members
					elif segment_end.intersection(member_before) or segment_start.intersection(member_after):
						new_members = group_members[::-1]
					else:
						new_members = group_members

					# For restriction relations, only members connected to "via" are needed

					if via:
						for member in new_members[:]:
							if member in osm_ways and "nodes" in osm_ways[ member ] and via in osm_ways[ member ]['nodes']:
								new_members = [ member ]
								break

					# Insert into relation member list (may have been modified during while loop)

					for i, member in enumerate(relation.findall("member")):
						if i == position:
							if "role" in member.attrib:
								role = member.attrib['role']  # All group members will inherit role
							else:
								role = None
							relation.remove(member)
							for new_member in reversed(new_members):
								if role:
									relation.insert(i, ElementTree.Element("member", type="way", ref=str(new_member), role=role))
								else:
									relation.insert(i, ElementTree.Element("member", type="way", ref=str(new_member)))
								updated_relations.add(relation_id)
							break							

					relation.set("action", "modify")
					members = members[ : position ] + new_members + members[ position + 1 : ]
					position += len(new_members) - 1

				position += 1

	message ("\tUpdated %i relations\n" % len(updated_relations))



# Count tags which are updated

def count_updated_tags(key):

	global tags_updated

	if key not in tags_updated:
		tags_updated[ key ] = 0

	tags_updated[ key ] += 1



# Update tagging in XML

def update_xlm_tags(way, osm_id):

	global count_modified_tag

	# True if tag should be removed
	def remove_tags(key, value, tags):

		return (key in delete_tags or key in delete_negative_tags and value in ["no", "none"] or 
			"source" in key or key == "maxheight" and value == "default" or 
			key == "lanes" and 
			 	("oneway" not in tags and value in ["1", "2"] and "turn:lanes:forward" not in tags and "turn:lanes:backward" not in tags or 
			 	"oneway" in tags and tags['oneway'] == "yes" and value == "1" and "turn:lanes" not in tags))

	# Main function
	if "nvdb_id" in osm_ways[ osm_id ]:
		modified_tags = []
		consider_tags = []
		diff_tags = []
		nvdb_id = osm_ways[osm_id]['nvdb_id']

		nvdb_tags = nvdb_ways[ nvdb_id ]['tags']
		osm_tags = osm_ways[ osm_id ]['tags']
		new_tags = update_tags(osm_tags, nvdb_tags)  # Note: Does not contain tags which are prevented from updating (highway, ref etc.)

		# Existing tags in OSM
		for tag_osm in way.findall("tag"):
			key = tag_osm.attrib['k']
			value = tag_osm.attrib['v']

			if key in new_tags:
				if value != new_tags[key]:
					modified_tags.append("Modified %s=%s to %s" % (key, value, new_tags[key]))
					tag_osm.set("v", new_tags[key])
					count_updated_tags(key)

			elif remove_tags(key, value, osm_tags):
				modified_tags.append("Removed %s=%s" % (key, value))
				way.remove(tag_osm)
				count_updated_tags(key)

			elif key not in nvdb_tags:
				if any(key.replace(suffix, "") in core_tags for suffix in tag_suffixes) and \
						not (key == "name" and \
							("tunnel:name" in nvdb_tags and value == nvdb_tags['tunnel:name'] or \
							"bridge:description" in nvdb_tags and value == nvdb_tags['bridge:description'])):
					consider_tags.append("Remove %s=%s" % (key, value))
				elif key != key.upper():
					diff_tags.append("Remove %s=%s" % (key, value))

		# New tags added to OSM
		for key, value in iter(new_tags.items()):
			if key not in osm_tags:
				way.append(ElementTree.Element("tag", k=key, v=value))
				modified_tags.append("Added %s=%s" % (key, value))
				count_updated_tags(key)

		# Tags in NVDB but not in OSM (and not added)
		for key, value in iter(nvdb_tags.items()):
			if key in core_tags and key not in new_tags and key in osm_tags and value != osm_tags[key]:
				consider_tags.append("Modify %s=%s to %s" % (key, osm_tags[key], value))
			elif key not in new_tags and key not in osm_tags:
				if any(key.replace(suffix, "") in core_tags for suffix in tag_suffixes) and \
						not (key in ["tunnel:name", "bridge:description"] and "name" in osm_tags and value == osm_tags['name']):
					consider_tags.append("Add %s=%s" % (key, value))
				else:
					diff_tags.append("Add %s=%s" % (key, value))

		if "bridge_tunnel" in osm_ways[osm_id]:
			consider_tags.append("Swap bridge/tunnel")

		if modified_tags or consider_tags or diff_tags:
			count_modified_tag += 1
			if modified_tags:
				way.set("action", "modify")
				way.append(ElementTree.Element("tag", k="EDIT", v="; ".join(sorted(modified_tags))))
			if consider_tags:
				way.append(ElementTree.Element("tag", k="CONSIDER", v="; ".join(sorted(consider_tags))))
			if diff_tags:
				way.append(ElementTree.Element("tag", k="DIFF", v="; ".join(sorted(diff_tags))))

	# Only test for tags to remove for non-matched ways
	else:
		tags = osm_ways[ osm_id ]['tags']
		modified_tags = []
		
		for tag_osm in way.findall("tag"):
			key = tag_osm.attrib['k']
			value = tag_osm.attrib['v']
			if remove_tags(key, value, tags):
				modified_tags.append("Removed %s=%s" % (key, value))
				way.remove(tag_osm)
				count_updated_tags(key)

		if modified_tags:
			count_modified_tag += 1
			way.set("action", "modify")
			way.append(ElementTree.Element("tag", k="EDIT", v="; ".join(sorted(modified_tags))))



# Prepare and output file

def output_file (osm_filename):

	global root_osm, tree_osm, root_nvdb, tree_nvdb, new_id, tags_updated, count_modified_tag

	count_modified_tag = 0
	tags_updated = {}

	# Empty start for "new" and "offset"
	if command in ["new", "offset"]:
		root_osm = ElementTree.Element("osm", version="0.6")
		tree_osm = ElementTree.ElementTree(root_osm)

	# Transfer segments to osm_ways

	if command in ["tagref", "taglocal"]:

		for segment in segments:
			if "new" in segment:
				new_id -= 1
				way = ElementTree.Element("way", id=str(new_id), action="modify")
				root_osm.append(way)
				for tag in osm_ways[ segment['id'] ]['xml'].findall("tag"):
					way.append(copy.deepcopy(tag))
				way.append(ElementTree.Element("tag", k="NEW_SEGMENT", v=segment['id']))

				osm_way = copy.deepcopy(osm_ways[ segment['id'] ])
				osm_way['xml'] = way
				osm_ways[ str(new_id) ] = osm_way

				segment['id'] = str(new_id)

		for segment in segments:
			osm_way = osm_ways[ segment['id'] ]
			way = osm_way['xml']

			if segment['nodes'] != osm_way['nodes']:  # osm_ways[ segment['id'] ]['nodes']:
				way.set("action", "modify")
				for node in way.findall("nd"):
					way.remove(node)
				for node in segment['nodes']:
					way.append(ElementTree.Element("nd", ref=node))
				osm_way['nodes'] = segment['nodes']

			if "nvdb_id" in segment:
				osm_way['nvdb_id'] = segment['nvdb_id']
			else:
				way.append(ElementTree.Element("tag", k="NO_MATCH", v="yes"))

			if debug:
				way.append(ElementTree.Element("tag", k="DISTANCE", v="%.1f" % segment['distance']))
				way.append(ElementTree.Element("tag", k="ORDER", v=str(segment['order'])))
				if "nvdb_id" in segment:
					way.append(ElementTree.Element("tag", k="NVDBID", v=segment['nvdb_id']))

	# Merge NVDB ways with OSM

	for way in root_osm.findall("way"):
		osm_id = way.attrib['id']

		# Replace geometry and tags

		if command == "replace" and "nvdb_id" in osm_ways[ osm_id ]:

			nvdb_id = osm_ways[ osm_id ]['nvdb_id'] 
			nvdb_way = nvdb_ways[ nvdb_id ]['xml']

			for tag_osm in way.findall("tag"):
				if tag_osm.attrib['k'] in replace_tags:
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
				way.append(ElementTree.Element("tag", k="ORDER", v=str(nvdb_ways[ nvdb_id ]['order'])))
				way.append(ElementTree.Element("tag", k="DISTANCE", v=str(round(nvdb_ways[ nvdb_id ]['distance']))))

			for node in way.findall('nd'):
				nodes[ node.attrib['ref'] ]['used'] -= 1
				way.remove(node)

			for node in nvdb_way.iter("nd"):
				nodes[ node.attrib['ref'] ]['used'] += 1
				way.append(ElementTree.Element("nd", ref=node.attrib['ref']))

			way.set("action", "modify")

		# Remove way

		elif command == "replace" and "remove" in osm_ways[ osm_id ]:

			for node in way.findall('nd'):
				nodes[ node.attrib['ref'] ]['used'] -= 1
				way.remove(node)

			way.set("action", "delete")

		# Replace tags only

		elif command in ["tag", "tagref", "taglocal"] and "nvdb_id" in osm_ways[osm_id]:
			update_xlm_tags(way, osm_id)

		# Remove certain unwanted tags even for segments not matched

		elif command in ["tagref", "taglocal"] and osm_ways[osm_id]['highway'] in public_highway and \
				(not force_ref or "ref" in osm_ways[osm_id]['tags']) and not osm_ways[osm_id]['incomplete']:
			update_xlm_tags(way, osm_id)

	# Report tagging results

	if command in ["tag", "tagref", "taglocal"]:
		message ("\tUpdated tags for %i highways\n" % count_modified_tag)
		message ("\tTags updated:\n")
		for key, count in sorted(tags_updated.items(), key=lambda x: x[1], reverse=True):
			message ("\t\t%s (%i)\n" % (key, count))

		if command in ["tagref", "taglocal"]:
			update_relations()

	# Transfer new NVDB ways to OSM

	for way in root_nvdb.findall("way"):
		nvdb_id = way.attrib['id']

		if command == "new" and "missing" in nvdb_ways[ nvdb_id ] or \
				command == "replace" and "osm_id" not in nvdb_ways[ nvdb_id ] or \
				command == "offset" and "osm_id" in nvdb_ways[ nvdb_id ]:

			if command == "offset":
				if nvdb_ways[ nvdb_id ]['highway'] != osm_ways[ nvdb_ways[nvdb_id]['osm_id'] ]['highway']:
					tag_highway = way.find("tag[@k='highway']")
					tag_highway.set("v", osm_ways[ nvdb_ways[nvdb_id]['osm_id'] ]['highway'])
					way.append(ElementTree.Element("tag", k="NVDB", v=nvdb_ways[ nvdb_id ]['highway']))
				if debug:
					way.append(ElementTree.Element("tag", k="OSMID", v=nvdb_ways[ nvdb_id ]['osm_id']))
					way.append(ElementTree.Element("tag", k="ORDER", v=str(nvdb_ways[ nvdb_id ]['order'])))
					way.append(ElementTree.Element("tag", k="DISTANCE", v=str(round(nvdb_ways[ nvdb_id ]['distance']))))

			root_osm.append(way)
			for node in nvdb_ways[ nvdb_id ]['nodes']:
				nodes[ node ]['used'] += 1

			if debug and "missing" in nvdb_ways[ nvdb_id ]:
				way.append(ElementTree.Element("tag", k="MISSING", v=nvdb_ways[ nvdb_id ]['missing']))

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
			way.set("action", "modify")
		tag = way.find("tag[@k='nvdb:date']")
		if tag != None:
			way.remove(tag)
			way.set("action", "modify")

	# Add distance markers for debugging

	if debug_gap:
		i = new_id  # Try to avoid osm id conflicts
		for line in test_lines:
			way = ElementTree.Element("way", id=str(i), action="modify")
			root_osm.append(way)
			root_osm.append(ElementTree.Element("node", id=str(i-1), action="modify", lat=str(line['lat1']), lon=str(line['lon1'])))
			root_osm.append(ElementTree.Element("node", id=str(i-2), action="modify", lat=str(line['lat2']), lon=str(line['lon2'])))
			way.append(ElementTree.Element("nd", ref=str(i-1)))
			way.append(ElementTree.Element("nd", ref=str(i-2)))
			way.append(ElementTree.Element("tag", k="GAP", v=str(line['distance'])))
			i -= 3

	# Generate list of top contributors for modified highways

	users = {}
	for way in root_osm.iter("way"):
		if "action" in way.attrib and way.attrib['action'] == "modify" and "user" in way.attrib:
			if way.attrib['user'] not in users:
				users[ way.attrib['user'] ] = 0
			users[ way.attrib['user'] ] += 1

	sorted_users = sorted(users.items(), key=lambda x: x[1], reverse=True)

	if users:
		message ("Top contributors for modified highways:\n")
		for i, user in enumerate(sorted_users):
			if user[1] > 10 and i < 10 or user[1] >= 100:
				message ("\t%s (%i)\n" % (user[0], user[1]))

	# Output file

	message ("Saving file ... ")

	root_osm.set("generator", "highway_merge v"+version)
	root_osm.set("upload", "false")
	indent_tree(root_osm)
	filename_out = filename_osm.replace(" ", "_").replace(".osm", "") + "_%s.osm" % command
	tree_osm.write(filename_out, encoding='utf-8', method='xml', xml_declaration=True)

	message ("'%s' saved\n" % filename_out)



# Output progress stats

def output_progress(municipality_id):

	full_filename = os.path.expanduser(import_folder + progress_filename)
	if not os.path.isfile(full_filename):
		return

	file = open(full_filename)
	progress = json.load(file)
	file.close()

	if not municipality_id in progress:
		message ("Municipality not found in progress file\n")
		return

	count_tags = 0
	count_highways = 0

	for segment in segments:
		if "nvdb_id" in segment:
			osm_tags = osm_ways[ segment['id'] ]['tags']
			nvdb_tags = nvdb_ways[ segment['nvdb_id'] ]['tags']
			new_tags = update_tags(osm_tags, nvdb_tags)
			found = False
			for key, value in iter(new_tags.items()):
				if (key not in osm_tags or osm_tags[key] != value) and \
						any(key.replace(suffix, "") in progress_tags for suffix in tag_suffixes):
					count_tags += 1
					found = True

			if found:
				count_highways += 1

	if command == "tagref":
		group = "ref"
	else:
		group = "local"
	progress[ municipality_id ][ group + '_tags'] = count_tags
	progress[ municipality_id ][ group + '_progress'] = count_highways
	progress[ municipality_id ][ group + '_highways'] = len(segments)
	progress[ municipality_id ][ 'highways'] = count_osm_roads

	file = open(full_filename, "w")
	json.dump(progress, file, indent=2, ensure_ascii=False)
	file.close()

	message ("Saved progress: %i tags, %i highways\n" % (count_tags, count_highways))



# Main program

if __name__ == '__main__':

	message ("\n*** highway_merge v%s ***\n\n" % version)

	if len(sys.argv) == 4 and sys.argv[1].lower() in ["-new", "-offset", "-replace", "-tagref", "-taglocal"]:
		command = sys.argv[1].lower().strip("-")
		filename_osm = sys.argv[2]
		filename_nvdb = sys.argv[3]

	elif len(sys.argv) == 3 and ".osm" not in sys.argv[2].lower() and sys.argv[1].lower() in ["-new", "-offset", "-replace", "-tagref", "-taglocal"]:
		command = sys.argv[1].lower().strip("-")
		filename_osm = sys.argv[2]
		filename_nvdb = filename_osm

	else:
		message ("Please include 1) -new/-offset/-replace/-tagref/-taglocal /2) OSM file and 3) NVDB file as parameters\n")
		sys.exit()

	if "-debug" in sys.argv:
		debug = True

	if "-progress" in sys.argv:
		save_progress = True

	municipalities = {}
	if "-swe" in sys.argv:
		country = "Sweden"
		state_highway += ["tertiary", "tertiary_link"]
	load_municipalities(country)

	if command == "tagref":
		public_highway = state_highway
	elif command == "taglocal":
		public_highway = municipality_highway  # Different matching highway=* tags for residential highways
		force_ref = False

	if filename_osm.lower() in ["norge", "norway", "sverige", "sweden"]:
		iterate_municipalities = sorted(municipalities.keys())
	else:
		iterate_municipalities = [ filename_osm ]

	# Iterate all municipalities, or the one selected municipality

	for municipality in iterate_municipalities:

		if municipality < "":  # Insert starting municipality number, if needed
			continue

		start_time = time.time()
		osm_ways = {}
		nvdb_ways = {}
		nodes = {}
		segments = []
		segment_groups = {}
		test_lines = []  # For debug
		new_id = -1000000

		municipality_id = load_files (municipality)

		if command == "new":
			add_new_highways()
		elif command in ["tagref", "taglocal"]:
			tag_highways()
		else:
			merge_highways (command)

		if save_progress and municipality_id and country == "Norway":
			output_progress (municipality_id)
		else:
			output_file (filename_osm)

		time_lapsed = time.time() - start_time
		message ("Time: %i seconds (%i ways per second)\n\n\n" % (time_lapsed, count_osm_roads / time_lapsed))

	message ("Done\n\n")
