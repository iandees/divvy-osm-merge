from xml.dom.minidom import parse, Document
import json
import urllib2
from math import radians, cos, sin, asin, sqrt

def haversine(lon1, lat1, lon2, lat2):
    """
    Calculate the great circle distance between two points
    on the earth (specified in decimal degrees)
    """
    # convert decimal degrees to radians
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    # haversine formula
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    m = 6372800 * c
    return m

def hash_my_node(n):
    return hash(n.get('lat')) + \
           hash(n.get('lon')) + \
           hash(n.get('tags', {}).get('divvy:id')) + \
           hash(n.get('tags', {}).get('name')) + \
           hash(n.get('tags', {}).get('capacity')) + \
           hash(n.get('tags', {}).get('operator'))

def get_divvy_osm_nodes():
    nodes = []
    data = urllib2.urlopen('http://www.overpass-api.de/api/xapi?node[amenity=bicycle_rental][bbox=-88.24768,41.45096,-87.2644,42.24479][@meta]')
    doc = parse(data)
    for node in doc.getElementsByTagName('node'):
        nodes.append({
            'lat': float(node.getAttribute('lat')),
            'lon': float(node.getAttribute('lon')),
            'id': int(node.getAttribute('id')),
            'version': int(node.getAttribute('version')),
            'tags': dict([(tag.getAttribute('k'), tag.getAttribute('v')) for tag in node.getElementsByTagName('tag')])
        })
    return nodes

def get_divvy_data():
    return json.load(urllib2.urlopen('http://www.divvybikes.com/stations/json/'))['stationBeanList']

print "Getting divvy data."
divvy_data = get_divvy_data()
print "Getting OSM divvy data"
osm_data = get_divvy_osm_nodes()
osm_output_array = []

divvy_by_id = dict([(str(d['id']), d) for d in divvy_data])

# Find matches by Divvy station ID first. The stations might have moved or changed names,
# so lets move the OSM node to the right spot and change it's data.
def match_by_id(osm_node):
    if 'divvy:id' in osm_node['tags']:
        osm_divvy_id = osm_node['tags']['divvy:id']
        divvy_match = divvy_by_id.get(osm_divvy_id)
        if divvy_match:
            osm_output = osm_node
            osm_output['lat'] = divvy_match['latitude']
            osm_output['lon'] = divvy_match['longitude']
            osm_output['tags']['divvy:id'] = divvy_match['id']
            osm_output['tags']['name'] = divvy_match['stationName']
            osm_output['tags']['capacity'] = divvy_match['totalDocks']
            osm_output['tags']['operator'] = 'Divvy'


            if hash_my_node(osm_node) != hash_my_node(osm_output):
                osm_output['action'] = 'modify'

            osm_output_array.append(osm_output)

            del divvy_by_id[str(divvy_match['id'])]
            divvy_data.remove(divvy_match)
            return False
    return True

print "There are %s OSM nodes and %s Divvy stations." % (len(osm_data), len(divvy_data))
osm_data = filter(match_by_id, osm_data)
print "After matching by ID, there are %s OSM nodes and %s unmatched Divvy stations." % (len(osm_data), len(divvy_data))

# Then check the area around the rest of the Divvy-sourced stations for OSM data and
# merge it together.
def match_by_distance(divvy_station):
    best_distance = 1000
    best_osm_candidate = None
    for osm_node in osm_data:
        dist_m = haversine(divvy_station['longitude'], divvy_station['latitude'], osm_node['lon'], osm_node['lat'])

        if dist_m < best_distance:
            best_osm_candidate = osm_node
            best_distance = dist_m

    if best_distance < 500:
        osm_output = best_osm_candidate
        osm_output['action'] = 'modify'
        osm_output['lat'] = divvy_station['latitude']
        osm_output['lon'] = divvy_station['longitude']
        osm_output['tags']['divvy:id'] = divvy_station['id']
        osm_output['tags']['name'] = divvy_station['stationName']
        osm_output['tags']['capacity'] = divvy_station['totalDocks']
        osm_output['tags']['operator'] = 'Divvy'
        osm_output_array.append(osm_output)

        print "OSM node %s is %0.1f meters away from Divvy station %s, so matching them." % (best_osm_candidate['id'], best_distance, divvy_station['id'])
        osm_data.remove(best_osm_candidate)
        del divvy_by_id[str(divvy_station['id'])]
        return False
    return True

divvy_data = filter(match_by_distance, divvy_data)
print "After matching by distance, there are %s OSM nodes and %s unmatched Divvy stations." % (len(osm_data), len(divvy_data))

# Lastly, add brand new nodes based on Divvy-sourced data that wasn't merged in the two
# steps above.
new_node_id = -1
for divvy_station in divvy_data:
    osm_output_array.append({
        'action': 'create',
        'lat': divvy_station['latitude'],
        'lon': divvy_station['longitude'],
        'id': new_node_id,
        'tags': {
            'amenity': 'bicycle_rental',
            'divvy:id': divvy_station['id'],
            'name': divvy_station['stationName'],
            'capacity': divvy_station['totalDocks'],
            'operator': 'Divvy',
        }
    })
    new_node_id -= 1
divvy_data = []
divvy_by_id = {}
print "After adding new OSM nodes, there are %s OSM nodes and %s unmatched Divvy stations." % (len(osm_data), len(divvy_data))

for osm_node in osm_data:
    osm_node['action'] = 'delete'
    osm_output_array.append(osm_node)
    osm_data.remove(osm_node)
print "After deleting old data, there are %s OSM nodes and %s unmatched Divvy stations." % (len(osm_data), len(divvy_data))

# TODO Don't forget to add/remove stations from the Divvy relation (3019517)

doc = Document()
root = doc.createElement('osm')
root.setAttribute('version', '0.6')
doc.appendChild(root)

for node in osm_output_array:
    node_elem = doc.createElement('node')
    node_elem.setAttribute('id', str(node['id']))
    node_elem.setAttribute('lat', str(round(node['lat'], 7)))
    node_elem.setAttribute('lon', str(round(node['lon'], 7)))
    node_elem.setAttribute('visible', 'true')

    if 'version' in node:
        node_elem.setAttribute('version', str(node['version']))

    if 'action' in node:
        node_elem.setAttribute('action', node['action'])

    for (k, v) in node['tags'].iteritems():
        tag_elem = doc.createElement('tag')
        tag_elem.setAttribute('k', k)
        tag_elem.setAttribute('v', str(v))
        node_elem.appendChild(tag_elem)

    root.appendChild(node_elem)

with open('divvy_stations_modified.osm', 'w') as f:
    f.write(doc.toprettyxml(indent='  '))
