"""Five real-browser candidate scenarios; no HTTP mocking or session injection."""
import base64
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import secrets
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET

from playwright.sync_api import expect, sync_playwright

CONFIG = json.loads(Path('/private/config.json').read_text())
if CONFIG['project'] != 'muni-core-testing-e2e':
    raise RuntimeError('Unexpected project')
BASE = 'http://frontend'
API = BASE + '/api/v1'
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
CONFIG['user_password'] = 'E2e9' + CONFIG['password']
SENSITIVE = [CONFIG['password'], CONFIG['user_password'], CONFIG['rabbit_password']]


def redact(value):
    text = str(value)
    for secret in SENSITIVE:
        if secret:
            text = text.replace(secret, '[REDACTED]')
    return text


def request(method, path, payload=None, token=None, statuses=(200,), broker=False):
    headers = {}
    if broker:
        url = 'http://rabbitmq:15672/api' + path
        basic = base64.b64encode(('core:' + CONFIG['rabbit_password']).encode()).decode()
        headers['Authorization'] = 'Basic ' + basic
    else:
        url = API + path
        if token:
            headers['Authorization'] = 'Bearer ' + token
    raw = None
    if payload is not None:
        raw = json.dumps(payload).encode()
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=raw, method=method, headers=headers)
    try:
        with OPENER.open(req, timeout=15) as response:
            status, body = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, body = error.code, error.read()
    if status not in statuses:
        print(redact(
            f'Unexpected response: {method} {path}: HTTP {status}; '
            + body.decode('utf-8', errors='replace')[:2000]
        ), flush=True)
        if method == 'GET' and path.startswith('/events/') and status == 404:
            time.sleep(0.5)
            try:
                with OPENER.open(req, timeout=15) as later:
                    later_status = later.status
                    later.read()
            except urllib.error.HTTPError as later:
                later_status = later.code
                later.read()
            print(
                f'Diagnostic only: same GET after 0.5s returned HTTP {later_status}. '
                'The original failure is preserved.',
                flush=True,
            )
        raise AssertionError(f'{method} {path}: HTTP {status}, expected {statuses}')
    return json.loads(body) if body else None


def login_token(email):
    result = request('POST', '/auth/login', {
        'email': email, 'password': (CONFIG['password'] if email == 'core@muni.uade.edu.ar'
                                      else CONFIG['user_password']),
    })
    SENSITIVE.append(result['accessToken'])
    return result['accessToken']


class CoreBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = login_token('core@muni.uade.edu.ar')
        suffix = secrets.token_hex(6)
        cls.source = 'e2e-source-' + suffix
        cls.target = 'e2e-target-' + suffix
        cls.emails = {}
        cls.tokens = {}
        cls.machine = {}
        cls.created = []
        cls.types = {n: f'qaE2E{suffix}Case{n}' for n in (3, 4, 5)}
        for module in (cls.source, cls.target):
            result = request('POST', '/modules', {
                'name': module, 'displayName': module, 'team': 'Synthetic E2E',
            }, cls.admin, (201,))
            cls.created.append(module)
            SENSITIVE.append(result['secret'])
            machine = request('POST', '/auth/module-token', {
                'module': module, 'secret': result['secret'],
            })['accessToken']
            cls.machine[module] = machine
            SENSITIVE.append(machine)
            email = module + '@example.com'
            request('POST', '/users', {
                'email': email, 'fullName': 'Synthetic E2E user',
                'password': CONFIG['user_password'], 'module': module,
            }, cls.admin, (201,))
            cls.emails[module] = email
            cls.tokens[module] = login_token(email)
        schema = {
            'type': 'object', 'required': ['marker', 'quantity'],
            'properties': {'marker': {'type': 'string'}, 'quantity': {'type': 'integer'}},
            'additionalProperties': False,
        }
        for name in cls.types.values():
            request('POST', '/event-types', {
                'name': name, 'ownerModule': cls.source, 'jsonSchema': schema,
            }, cls.admin, (201,))
            request('POST', '/publications', {
                'module': cls.source, 'eventType': name,
            }, cls.admin, (200, 201))
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)
        Path('/evidence/fixture-identifiers.json').write_text(json.dumps({
            'source': cls.source, 'target': cls.target, 'types': cls.types,
        }, indent=2))

    @classmethod
    def tearDownClass(cls):
        try:
            if hasattr(cls, 'browser'):
                cls.browser.close()
                cls.playwright.stop()
        finally:
            # Preserve event and delivery audit, but disable only synthetic actors.
            for module in getattr(cls, 'created', []):
                request('PATCH', '/modules/' + module, {'active': False}, cls.admin)

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 1280, 'height': 800})
        self.page = self.context.new_page()
        self.page.set_default_timeout(20000)
        self.page.goto(BASE)
        expect(self.page.get_by_role('heading', name='Iniciar sesión')).to_be_visible()

    def tearDown(self):
        self.context.close()

    def ui_login(self, module):
        self.page.get_by_label('Correo electrónico', exact=True).fill(self.emails[module])
        self.page.get_by_label('Contraseña', exact=True).fill(CONFIG['user_password'])
        self.page.get_by_role('button', name='Iniciar sesión', exact=True).click()
        expect(self.page.get_by_role('heading', name='Historial de eventos', exact=True)).to_be_visible()

    def subscription(self, number):
        return request('POST', '/subscriptions', {
            'eventType': self.types[number], 'maxAttempts': 4,
        }, self.tokens[self.target], (201,))

    def envelope(self, number, valid=True):
        return {
            'eventId': str(uuid.uuid4()), 'eventType': self.types[number],
            'eventVersion': '1.0', 'occurredAt': datetime.now(timezone.utc).isoformat(),
            'sourceModule': self.source,
            'data': {'marker': 'synthetic-' + uuid.uuid4().hex,
                     'quantity': 1 if valid else 'invalid-integer'},
        }

    def broker_queue(self):
        path = '/queues/core/' + urllib.parse.quote('q.' + self.target, safe='')
        return path

    def test_01_login_reload_logout(self):
        self.ui_login(self.target)
        self.page.reload()
        expect(self.page.get_by_role('heading', name='Historial de eventos', exact=True)).to_be_visible()
        self.page.get_by_role('button', name='Ver datos del usuario').click()
        expect(self.page.get_by_role('dialog')).to_contain_text(self.emails[self.target])
        self.page.get_by_role('button', name='Cerrar sesión', exact=True).click()
        expect(self.page.get_by_role('heading', name='Iniciar sesión')).to_be_visible()
        self.assertIsNone(self.page.evaluate("sessionStorage.getItem('core-sesion-v1')"))

    def test_02_invalid_login_remains_unauthenticated(self):
        self.page.get_by_label('Correo electrónico', exact=True).fill(self.emails[self.target])
        self.page.get_by_label('Contraseña', exact=True).fill('InvalidSyntheticPassword9')
        with self.page.expect_response(lambda r: r.url.endswith('/api/v1/auth/login')) as reply:
            self.page.get_by_role('button', name='Iniciar sesión', exact=True).click()
        self.assertEqual(reply.value.status, 401)
        expect(self.page.locator('.auth-status.error')).to_be_visible()
        expect(self.page.get_by_role('heading', name='Iniciar sesión')).to_be_visible()
        self.assertIsNone(self.page.evaluate("sessionStorage.getItem('core-sesion-v1')"))

    def test_03_ui_subscription_persists_and_can_be_removed(self):
        self.ui_login(self.target)
        self.page.get_by_role('link', name='Eventos Suscriptos', exact=True).click()
        checkbox = self.page.get_by_role('checkbox', name=self.types[3], exact=True)
        expect(checkbox).not_to_be_checked()
        label = self.page.locator('label').filter(
            has=self.page.get_by_role('checkbox', name=self.types[3], exact=True)
        )
        label.locator('span').click()
        expect(checkbox).to_be_checked()
        self.page.get_by_role('button', name='Aplicar', exact=True).click()
        expect(self.page.get_by_role('status')).to_contain_text('Listo:')
        rows = request('GET', '/subscriptions', token=self.tokens[self.target])
        matches = [row for row in rows if row['eventType'] == self.types[3]]
        self.assertEqual(len(matches), 1)
        self.assertTrue(matches[0]['active'])
        self.assertEqual(matches[0]['maxAttempts'], 4)
        self.page.reload()
        expect(checkbox).to_be_checked()
        label.locator('span').click()
        expect(checkbox).not_to_be_checked()
        self.page.get_by_role('button', name='Aplicar', exact=True).click()
        expect(self.page.get_by_role('status')).to_contain_text('dada de baja')
        rows = request('GET', '/subscriptions', token=self.tokens[self.target])
        self.assertFalse(any(row['eventType'] == self.types[3] for row in rows))

    def test_04_valid_event_reaches_broker_and_browser_detail(self):
        self.subscription(4)
        body = self.envelope(4)
        result = request('POST', '/events', body, self.machine[self.source], (202,))
        self.assertIn(self.target, result['routedTo'])
        # Real broker inspection, not an in-memory double or mocked network.
        messages = request('POST', self.broker_queue() + '/get', {
            'count': 1, 'ackmode': 'ack_requeue_true', 'encoding': 'auto',
        }, statuses=(200,), broker=True)
        self.assertEqual(len(messages), 1)
        received = json.loads(messages[0]['payload'])
        self.assertEqual(received['eventId'], body['eventId'])
        self.assertEqual(received['data'], body['data'])
        self.ui_login(self.target)
        row = self.page.get_by_role('row').filter(has_text=self.types[4])
        expect(row).to_have_count(1)
        row.get_by_role('button', name='JSON').click()
        expect(self.page.get_by_role('dialog')).to_contain_text(body['eventId'])
        expect(self.page.get_by_role('dialog')).to_contain_text(body['data']['marker'])

    def test_05_schema_error_is_visible_and_dead_lettered(self):
        self.subscription(5)
        body = self.envelope(5, valid=False)
        request('POST', '/events', body, self.machine[self.source], (422,))
        detail = request('GET', '/events/' + body['eventId'], token=self.tokens[self.source])
        self.assertEqual(detail['status'], 'REJECTED')
        self.assertEqual(detail['rejectionCode'], 'SCHEMA_VIOLATION')
        self.assertEqual(detail['deliveries'], [])
        letters = request('GET', '/dlq?size=200', token=self.admin)
        items = letters['items'] if isinstance(letters, dict) else letters
        matches = [row for row in items if row.get('eventId') == body['eventId']]
        self.assertEqual(len(matches), 1)
        self.ui_login(self.source)
        row = self.page.get_by_role('row').filter(has_text=self.types[5])
        expect(row).to_have_count(1)
        expect(row).to_contain_text('SCHEMA_VIOLATION')


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases = []

    def startTest(self, test):
        self.started = time.monotonic()
        super().startTest(test)

    def addSuccess(self, test):
        super().addSuccess(test)
        self.cases.append((str(test), 'passed', '', time.monotonic() - self.started))

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.cases.append((str(test), 'failure', self._exc_info_to_string(err, test),
                           time.monotonic() - self.started))

    def addError(self, test, err):
        super().addError(test, err)
        self.cases.append((str(test), 'error', self._exc_info_to_string(err, test), 0))

    def _exc_info_to_string(self, err, test):
        return redact(super()._exc_info_to_string(err, test))


if __name__ == '__main__':
    capture = io.StringIO()
    result = unittest.TextTestRunner(stream=capture, verbosity=2,
                                     resultclass=EvidenceResult).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(CoreBrowserTests))
    log = redact(capture.getvalue())
    print(log, flush=True)
    Path('/evidence/browser-tests.log').write_text(log)
    xml = ET.Element('testsuite', name='Core real-browser candidates',
                     tests=str(result.testsRun), failures=str(len(result.failures)),
                     errors=str(len(result.errors)), skipped=str(len(result.skipped)))
    for name, status, message, seconds in result.cases:
        case = ET.SubElement(xml, 'testcase', name=name, time=str(round(seconds, 3)))
        if status != 'passed':
            ET.SubElement(case, status).text = redact(message)
    ET.ElementTree(xml).write('/evidence/e2e.xml', encoding='utf-8', xml_declaration=True)
    summary = {'tests': result.testsRun, 'failures': len(result.failures),
               'errors': len(result.errors), 'skipped': len(result.skipped),
               'passed': result.wasSuccessful() and result.testsRun == 5 and not result.skipped}
    Path('/evidence/summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary), flush=True)
    raise SystemExit(0 if summary['passed'] else 1)
