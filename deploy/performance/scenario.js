
import http from 'k6/http';
import crypto from 'k6/crypto';
import { sleep } from 'k6';
import { Trend, Rate, Counter } from 'k6/metrics';

const cfg = JSON.parse(open('/private/config.json'));
const smoke = __ENV.PERF_MODE === 'smoke';
const latency = new Trend('operation_latency', true);
const errors = new Rate('operation_errors');
const calls = new Counter('operation_calls');
const endpoints = ['publish', 'history', 'dashboard'];
const thresholds = {};

for (const endpoint of endpoints) {
  thresholds[`operation_errors{endpoint:${endpoint}}`] = [smoke ? 'rate==0' : 'rate<0.01'];
  thresholds[`operation_calls{endpoint:${endpoint}}`] = [smoke ? 'count>0' : 'count>=50'];
  if (!smoke) {
    thresholds[`operation_latency{endpoint:${endpoint}}`] = ['p(95)<500'];
  }
}

export const options = {
  scenarios: {
    load: {
      executor: 'constant-vus',
      vus: smoke ? 1 : 50,
      duration: smoke ? '10s' : '5m',
      gracefulStop: '15s',
    },
  },
  thresholds,
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(95)', 'count'],
};

function uuid() {
  const bytes = new Uint8Array(crypto.randomBytes(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const value = Array.from(bytes, x => x.toString(16).padStart(2, '0')).join('');
  return `${value.slice(0,8)}-${value.slice(8,12)}-${value.slice(12,16)}-${value.slice(16,20)}-${value.slice(20)}`;
}

function operation(endpoint, method, path, body, expected, valid) {
  const response = http.request(method, cfg.base + path, body, {
    headers: {
      Authorization: `Bearer ${cfg.token}`,
      'Content-Type': 'application/json',
    },
    tags: { name: endpoint, endpoint },
    timeout: '10s',
    redirects: 0,
  });
  let ok = response.status === expected;
  if (ok) {
    try {
      ok = valid(response.json());
    } catch (_) {
      ok = false;
    }
  }
  latency.add(response.timings.duration, { endpoint });
  errors.add(!ok, { endpoint });
  calls.add(1, { endpoint });
}

export default function () {
  const event = {
    eventId: uuid(),
    eventType: cfg.event_type,
    eventVersion: '1.0',
    occurredAt: new Date().toISOString(),
    sourceModule: cfg.module,
    data: { marker: `${cfg.run}-${__VU}-${__ITER}` },
  };
  operation('publish', 'POST', '/events', JSON.stringify(event), 202,
    body => body.duplicate === false
      && Array.isArray(body.routedTo)
      && body.routedTo.includes(cfg.module));
  operation('history', 'GET',
    `/events?eventType=${encodeURIComponent(cfg.event_type)}&size=25`,
    null, 200, body => Array.isArray(body.items));
  operation('dashboard', 'GET', '/dashboard?windowHours=24',
    null, 200, body => body.module === cfg.module);
  sleep(1);
}

export function handleSummary(data) {
  return {
    '/evidence/summary.json': JSON.stringify(data, null, 2),
    stdout: 'Execution finished. Detailed metrics saved in summary.json\n',
  };
}
