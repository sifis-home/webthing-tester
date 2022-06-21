#!/usr/bin/env python3

import argparse
import json
import re
import socket
import time
import tornado.httpclient
import tornado.websocket
import websocket


_TIME_REGEX = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?([+-]\d{2}:\d{2}|Z)$'
_PROTO = None
_BASE_URL = None
_PATH_PREFIX = None
_AUTHORIZATION_HEADER = None
_DEBUG = False
_SKIP_ACTIONS_EVENTS = False
_SKIP_WEBSOCKET = False


def get_ip():
    """
    Get the default local IP address.

    From: https://stackoverflow.com/a/28950776
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except (socket.error, IndexError):
        ip = '127.0.0.1'
    finally:
        s.close()

    return ip


def http_request(method, path, data=None):
    """
    Send an HTTP request to the server.

    method -- request method, i.e. 'GET'
    path -- request path
    data -- optional data to include
    """
    url = _PROTO + '://' + _BASE_URL + _PATH_PREFIX + path
    url = url.rstrip('/')

    client = tornado.httpclient.HTTPClient()

    fake_host = 'localhost'
    if ':' in _BASE_URL:
        fake_host += ':' + _BASE_URL.split(':')[1]

    headers = {
        'Host': fake_host,
        'Accept': 'application/json',
    }

    if _DEBUG:
        if data is None:
            print('Request:  {} {}'.format(method, url))
        else:
            print('Request:  {} {}\n          {}'.format(method, url, data))

    if _AUTHORIZATION_HEADER is not None:
        headers['Authorization'] = _AUTHORIZATION_HEADER

    if data is None:
        request = tornado.httpclient.HTTPRequest(
            url,
            method=method,
            headers=headers,
        )
    else:
        headers['Content-Type'] = 'application/json'
        request = tornado.httpclient.HTTPRequest(
            url,
            method=method,
            headers=headers,
            body=json.dumps(data),
        )

    response = client.fetch(request, raise_error=False)

    if response.body:
        if _DEBUG:
            print('Response: {} {}\n'
                  .format(response.code, response.body.decode()))

        return response.code, json.loads(response.body.decode())
    else:
        if _DEBUG:
            print('Response: {}\n'.format(response.code))

        return response.code, None


def lists_equal(a, b):
    if len(a) != len(b):
        return False

    intersection = set(a) & set(b)
    return len(intersection) == len(a)


def check_property_value(body, prop, value):
    if _FLAVOR == 'Webthings':
        assert body[prop] == value
    else:
        assert body == value


def run_client():
    """Test the web thing server."""
    # Test thing description
    code, body = http_request('GET', '/')

    links_or_forms = 'links'
    media_type = "mediaType"
    if _FLAVOR == 'WoT':
        links_or_forms = "forms"
        media_type = "type"

    assert code == 200
    assert body['id'] == 'urn:dev:ops:my-lamp-1234'
    assert body['title'] == 'My Lamp'
    assert body['security'] == 'nosec_sc'
    assert body['securityDefinitions']['nosec_sc']['scheme'] == 'nosec'
    # assert body['@context'] == 'https://webthings.io/schemas'
    assert lists_equal(body['@type'], ['OnOffSwitch', 'Light'])
    assert body['description'] == 'A web connected lamp'
    assert body['properties']['on']['@type'] == 'OnOffProperty'
    assert body['properties']['on']['title'] == 'On/Off'
    assert body['properties']['on']['type'] == 'boolean'
    assert body['properties']['on']['description'] == 'Whether the lamp is turned on'
    assert len(body['properties']['on'][links_or_forms]) == 1
    assert body['properties']['on'][links_or_forms][0]['href'] == _PATH_PREFIX + '/properties/on'
    assert body['properties']['brightness']['@type'] == 'BrightnessProperty'
    assert body['properties']['brightness']['title'] == 'Brightness'
    assert body['properties']['brightness']['type'] == 'integer'
    assert body['properties']['brightness']['description'] == 'The level of light from 0-100'
    assert body['properties']['brightness']['minimum'] == 0
    assert body['properties']['brightness']['maximum'] == 100
    assert body['properties']['brightness']['unit'] == 'percent'
    assert len(body['properties']['brightness'][links_or_forms]) == 1
    assert body['properties']['brightness'][links_or_forms][0]['href'] == _PATH_PREFIX + \
        '/properties/brightness'

    if not _SKIP_ACTIONS_EVENTS:
        assert body['actions']['fade']['title'] == 'Fade'
        assert body['actions']['fade']['description'] == 'Fade the lamp to a given level'
        assert body['actions']['fade']['input']['type'] == 'object'
        assert body['actions']['fade']['input']['properties']['brightness']['type'] == 'integer'
        assert body['actions']['fade']['input']['properties']['brightness']['minimum'] == 0
        assert body['actions']['fade']['input']['properties']['brightness']['maximum'] == 100
        assert body['actions']['fade']['input']['properties']['brightness']['unit'] == 'percent'
        assert body['actions']['fade']['input']['properties']['duration']['type'] == 'integer'
        assert body['actions']['fade']['input']['properties']['duration']['minimum'] == 1
        assert body['actions']['fade']['input']['properties']['duration']['unit'] == 'milliseconds'
        assert len(body['actions']['fade'][links_or_forms]) == 1
        assert body['actions']['fade'][links_or_forms][0]['href'] == _PATH_PREFIX + '/actions/fade'
        assert body['events']['overheated']['data']['type'] == 'number'
        assert body['events']['overheated']['data']['unit'] == 'degree celsius'
        assert body['events']['overheated']['description'] == 'The lamp has exceeded its safe operating temperature'
        assert len(body['events']['overheated'][links_or_forms]) == 1
        assert body['events']['overheated'][links_or_forms][0]['href'] == _PATH_PREFIX + \
            '/events/overheated'

    if _SKIP_ACTIONS_EVENTS:
        assert len(body[links_or_forms]) >= 1
        if _FLAVOR == 'Webthings':
            assert body[links_or_forms][0]['rel'] == 'properties'
        assert body[links_or_forms][0]['href'] == _PATH_PREFIX + '/properties'
        remaining_links = body[links_or_forms][1:]
    else:
        if links_or_forms in body:
            remaining_links = body[links_or_forms]
        else:
            remaining_links = []

    if not _SKIP_WEBSOCKET:
        assert len(remaining_links) >= 1

        ws_href = None
        for link in remaining_links:
            if 'rel' in link and link['rel'] != 'alternate':
                continue

            if media_type in link:
                assert link[media_type] == 'text/html'
                assert link['href'] == _PATH_PREFIX
            else:
                proto = 'wss' if _PROTO == 'https' else 'ws'
                assert re.match(
                    proto + r'://[^/]+' + _PATH_PREFIX, link['href'])
                ws_href = link['href']

        assert ws_href is not None

    # Test properties
    code, body = http_request('GET', '/properties')
    assert body['brightness'] == 50
    assert body['on']

    code, body = http_request('GET', '/properties/brightness')
    assert code == 200
    check_property_value(body, "brightness", 50)

    value = 25 if _FLAVOR == "WoT" else {'brightness': 25}

    code, body = http_request('PUT', '/properties/brightness', value)
    assert code == 204
    assert not body

    code, body = http_request('GET', '/properties/brightness')
    assert code == 200
    check_property_value(body, 'brightness', 25)

    if not _SKIP_ACTIONS_EVENTS:
        # Test events
        code, body = http_request('GET', '/events')
        assert code == 200
        assert len(body) == 0

        # Test actions
        code, body = http_request('GET', '/actions')
        assert code == 200
        assert len(body) == 0

        code, body = http_request(
            'POST',
            '/actions/fade',
            {
            })
        assert code == 400

        code, body = http_request(
            'POST',
            '/actions/fade',
            {
                'brightness': 50,
                'duration': 2000,
            })
        assert code == 201
        assert body['output']['brightness'] == 50
        assert body['output']['duration'] == 2000
        assert body['href'].startswith(_PATH_PREFIX + '/actions/fade/')
        assert body['status'] == 'created'
        action_id = body['href'].split('/')[-1]

        # Wait for the action to complete
        time.sleep(2.5)

        code, body = http_request('GET', '/actions')
        assert code == 200
        assert len(body.keys()) == 1
        assert len(body['fade']) == 1
        assert body['fade'][0]['output']['brightness'] == 50
        assert body['fade'][0]['output']['duration'] == 2000
        assert body['fade'][0]['href'] == _PATH_PREFIX + \
            '/actions/fade/' + action_id
        assert re.match(_TIME_REGEX, body['fade'][0]
                        ['timeRequested']) is not None
        assert re.match(_TIME_REGEX, body['fade'][0]
                        ['timeEnded']) is not None
        assert body['fade'][0]['status'] == 'completed'

        code, body = http_request('GET', '/actions/fade/' + action_id)
        assert code == 200
        assert body['output']['brightness'] == 50
        assert body['output']['duration'] == 2000
        assert body['href'] == _PATH_PREFIX + \
            '/actions/fade/' + action_id
        assert re.match(_TIME_REGEX, body
                        ['timeRequested']) is not None
        assert re.match(_TIME_REGEX, body
                        ['timeEnded']) is not None
        assert body['status'] == 'completed'

        code, body = http_request('DELETE', '/actions/fade/' + action_id)
        assert code == 204
        assert body is None

    if _SKIP_WEBSOCKET:
        return

    # Set up a websocket
    ws = websocket.WebSocket()
    if _AUTHORIZATION_HEADER is not None:
        ws_href += '?jwt=' + _AUTHORIZATION_HEADER.split(' ')[1]

    ws.connect(ws_href)

    if _DEBUG:
        orig_send = ws.send
        orig_recv = ws.recv

        def send(msg):
            print('WS Send: {}'.format(msg))
            return orig_send(msg)

        def recv():
            msg = orig_recv()
            print('WS Recv: {}'.format(msg))
            return msg

        ws.send = send
        ws.recv = recv

    # Test setting property through websocket
    ws.send(json.dumps({
        'messageType': 'setProperty',
        'data': {
            'brightness': 10,
        }
    }))
    message = json.loads(ws.recv())
    assert message['messageType'] == 'propertyStatus'
    assert message['data']['brightness'] == 10

    code, body = http_request('GET', '/properties/brightness')
    assert code == 200
    check_property_value(body, 'brightness', 10)

    if _SKIP_ACTIONS_EVENTS:
        return

    # Test requesting action through websocket
    ws.send(json.dumps({
        'messageType': 'requestAction',
        'data': {
            'fade': {
                'brightness': 90,
                'duration': 1000,
            },
        }
    }))

    # Handle any extra propertyStatus message first
    while True:
        message = json.loads(ws.recv())
        if message['messageType'] == 'propertyStatus':
            continue

        break

    assert message['messageType'] == 'actionStatus'
    assert message['data']['fade']['output']['brightness'] == 90
    assert message['data']['fade']['output']['duration'] == 1000
    assert message['data']['fade']['href'].startswith(
        _PATH_PREFIX + '/actions/fade/')
    assert message['data']['fade']['status'] == 'created'
    message = json.loads(ws.recv())
    assert message['messageType'] == 'actionStatus'
    assert message['data']['fade']['output']['brightness'] == 90
    assert message['data']['fade']['output']['duration'] == 1000
    assert message['data']['fade']['href'].startswith(
        _PATH_PREFIX + '/actions/fade/')
    assert message['data']['fade']['status'] == 'pending'

    # These may come out of order
    action_id = None
    received = [False, False]
    for _ in range(0, 2):
        message = json.loads(ws.recv())

        if message['messageType'] == 'propertyStatus':
            assert message['data']['brightness'] == 90
            received[0] = True
        elif message['messageType'] == 'actionStatus':
            assert message['data']['fade']['output']['brightness'] == 90
            assert message['data']['fade']['output']['duration'] == 1000
            assert message['data']['fade']['href'].startswith(
                _PATH_PREFIX + '/actions/fade/')
            assert message['data']['fade']['status'] == 'completed'
            action_id = message['data']['fade']['href'].split('/')[-1]
            received[1] = True
        else:
            raise ValueError('Wrong message: {}'.format(
                message['messageType']))

    for r in received:
        assert r

    code, body = http_request('GET', '/actions')
    assert code == 200
    assert len(body) == 1
    assert len(body[0].keys()) == 1
    assert body[0]['fade']['output']['brightness'] == 90
    assert body[0]['fade']['output']['duration'] == 1000
    assert body[0]['fade']['href'] == _PATH_PREFIX + \
        '/actions/fade/' + action_id
    assert re.match(_TIME_REGEX, body[0]['fade']['timeRequested']) is not None
    assert re.match(_TIME_REGEX, body[0]['fade']['timeEnded']) is not None
    assert body[0]['fade']['status'] == 'completed'

    code, body = http_request('GET', '/actions/fade/' + action_id)
    assert code == 200
    assert len(body.keys()) == 1
    assert body['href'] == _PATH_PREFIX + '/actions/fade/' + action_id
    assert re.match(_TIME_REGEX, body['timeRequested']) is not None
    assert re.match(_TIME_REGEX, body['timeEnded']) is not None
    assert body['status'] == 'completed'

    code, body = http_request('GET', '/events')
    assert code == 200
    assert len(body) == 3
    assert len(body[2].keys()) == 1
    assert body[2]['overheated']['data'] == 102
    assert re.match(_TIME_REGEX, body[2]
                    ['overheated']['timestamp']) is not None

    # Test event subscription through websocket
    ws.send(json.dumps({
        'messageType': 'addEventSubscription',
        'data': {
            'overheated': {},
        }
    }))
    ws.send(json.dumps({
        'messageType': 'requestAction',
        'data': {
            'fade': {
                'brightness': 100,
                'duration': 500,
            },
        }
    }))
    message = json.loads(ws.recv())
    assert message['messageType'] == 'actionStatus'
    assert message['data']['fade']['output']['brightness'] == 100
    assert message['data']['fade']['output']['duration'] == 500
    assert message['data']['fade']['href'].startswith(
        _PATH_PREFIX + '/actions/fade/')
    assert message['data']['fade']['status'] == 'created'
    assert re.match(
        _TIME_REGEX, message['data']['fade']['timeRequested']) is not None
    message = json.loads(ws.recv())
    assert message['messageType'] == 'actionStatus'
    assert message['data']['fade']['output']['brightness'] == 100
    assert message['data']['fade']['output']['duration'] == 500
    assert message['data']['fade']['href'].startswith(
        _PATH_PREFIX + '/actions/fade/')
    assert message['data']['fade']['status'] == 'pending'
    assert re.match(
        _TIME_REGEX, message['data']['fade']['timeRequested']) is not None

    # These may come out of order
    received = [False, False, False]
    for _ in range(0, 3):
        message = json.loads(ws.recv())

        if message['messageType'] == 'propertyStatus':
            assert message['data']['brightness'] == 100
            received[0] = True
        elif message['messageType'] == 'event':
            assert message['data']['overheated']['data'] == 102
            assert re.match(
                _TIME_REGEX, message['data']['overheated']['timestamp']) is not None
            received[1] = True
        elif message['messageType'] == 'actionStatus':
            assert message['data']['fade']['output']['brightness'] == 100
            assert message['data']['fade']['output']['duration'] == 500
            assert message['data']['fade']['href'].startswith(
                _PATH_PREFIX + '/actions/fade/')
            assert message['data']['fade']['status'] == 'completed'
            assert re.match(
                _TIME_REGEX, message['data']['fade']['timeRequested']) is not None
            assert re.match(
                _TIME_REGEX, message['data']['fade']['timeCompleted']) is not None
            received[2] = True

    for r in received:
        assert r

    ws.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Web Thing test client.')
    parser.add_argument('--protocol',
                        help='protocol, either http or https',
                        choices=['http', 'https'],
                        default='http')
    parser.add_argument('--host',
                        help='server hostname or IP address',
                        default=get_ip())
    parser.add_argument('--port',
                        help='server port',
                        type=int,
                        default=8888)
    parser.add_argument('--path-prefix',
                        help='path prefix to get to thing description',
                        default='')
    parser.add_argument('--auth-header',
                        help='authorization header, i.e. "Bearer ..."')
    parser.add_argument('--skip-actions-events',
                        help='skip action and event tests',
                        action='store_true')
    parser.add_argument('--skip-websocket',
                        help='skip WebSocket tests',
                        action='store_true')
    parser.add_argument('--debug',
                        help='log all requests',
                        action='store_true')
    parser.add_argument('--flavor',
                        help='specify the protocol flavor',
                        choices=['WoT', 'Webthings'],
                        default='Webthings')
    args = parser.parse_args()

    if (args.protocol == 'http' and args.port == 80) or \
            (args.protocol == 'https' and args.port == 443):
        _BASE_URL = args.host
    else:
        _BASE_URL = '{}:{}'.format(args.host, args.port)

    if args.debug:
        _DEBUG = True

    if args.skip_actions_events:
        _SKIP_ACTIONS_EVENTS = True

    if args.skip_websocket:
        _SKIP_WEBSOCKET = True

    _PROTO = args.protocol
    _PATH_PREFIX = args.path_prefix
    _AUTHORIZATION_HEADER = args.auth_header
    _FLAVOR = args.flavor

    exit(run_client())
