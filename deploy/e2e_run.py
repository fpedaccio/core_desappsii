"""Run five browser candidates only against the dedicated local E2E project."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from testing_up import Bootstrap, read_env

PROJECT = 'muni-core-testing-e2e'
IMAGE = 'mcr.microsoft.com/playwright/python:v1.64.1-noble'
FRONTEND = '4a2fb0b569297a2fe75aef650780d6e9d39dbcaf'


def main():
    deploy = Path(__file__).resolve().parent
    repo = deploy.parent
    bootstrap = Bootstrap(deploy, project=PROJECT, port=18083)
    bootstrap.verify_local_engine()
    state = deploy / '.testing'
    result = json.loads((state / 'bootstrap-result.json').read_text())
    if result['project'] != PROJECT or result['frontend_ref'] != FRONTEND:
        raise RuntimeError('Use the dedicated candidate started with deploy/e2e_up.py')
    if not result['ready'] or not result['worker_consumers']:
        raise RuntimeError('Bootstrap did not confirm readiness')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    # New test/doc commits are allowed only when runtime application code still matches.
    app_diff = subprocess.check_output([
        'git', 'diff', result['backend_ref'], '--', 'backend', 'deploy/compose.yaml',
    ], cwd=repo, text=True)
    if app_diff:
        raise RuntimeError('Application differs from the bootstrapped revision; rebuild before testing')
    frontend = state / 'frontend'
    actual_frontend = subprocess.check_output([
        'git', '-C', str(frontend), 'rev-parse', 'HEAD',
    ], text=True).strip()
    if actual_frontend != FRONTEND:
        raise RuntimeError('Unexpected frontend checkout')
    containers = {}
    for service in ('api', 'worker', 'frontend', 'postgres', 'rabbitmq'):
        name = f'{PROJECT}-{service}-1'
        data = json.loads(subprocess.check_output(['docker', 'inspect', name], text=True))[0]
        if (data['Config']['Labels'].get('com.docker.compose.project') != PROJECT
                or data['State']['Status'] != 'running'):
            raise RuntimeError('Unexpected or stopped E2E container: ' + service)
        containers[service] = {'id': data['Id'], 'image': data['Image'],
                               'started_at': data['State']['StartedAt']}
    values = read_env(state / '.env')
    config = {'project': PROJECT, 'password': values['SEED_INITIAL_PASSWORD'],
              'rabbit_password': values['RABBITMQ_PASSWORD']}
    evidence = state / 'evidence' / ('e2e-' + datetime.now().strftime('%Y%m%d-%H%M%S')
                                    + '-' + uuid.uuid4().hex[:6])
    evidence.mkdir(parents=True, exist_ok=False)
    private = state / 'e2e-private'
    private.mkdir(mode=0o700, exist_ok=True)
    lock = private / 'run.lock'
    with lock.open('x') as handle:
        handle.write(str(os.getpid()))
    config_path = private / 'config.json'
    name = PROJECT + '-browser'
    metadata = {'started_at': datetime.now(timezone.utc).isoformat(), 'project': PROJECT,
                'test_source_revision': revision, 'backend_runtime_ref': result['backend_ref'],
                'frontend_ref': FRONTEND, 'containers': containers, 'image': IMAGE,
                'suite_sha256': hashlib.sha256((deploy / 'e2e/browser_suite.py').read_bytes()).hexdigest()}
    started = False
    try:
        if subprocess.check_output(['docker', 'ps', '-aq', '--filter', 'name=^/' + name + '$'],
                                   text=True).strip():
            raise RuntimeError('An E2E browser container already exists; preserve and inspect it')
        with config_path.open('x', encoding='utf-8') as handle:
            os.chmod(config_path, 0o600)
            json.dump(config, handle)
        setup = (
            "import subprocess,runpy; "
            "log=open('/evidence/tool-install.log','w'); "
            "subprocess.run(['python','-m','pip','install','--disable-pip-version-check',"
            "'playwright==1.64.1'],stdout=log,stderr=subprocess.STDOUT,check=True); "
            "log.close(); runpy.run_path('/suite.py',run_name='__main__')"
        )
        command = [
            'docker', 'run', '--rm', '--init', '--name', name, '--ipc=host',
            '--label', 'core.qa.project=' + PROJECT,
            '--network', PROJECT + '_default', '--entrypoint', 'python',
            '-e', 'PYTHONUNBUFFERED=1',
            '--mount', f'type=bind,source={config_path},target=/private/config.json,readonly',
            '--mount', f'type=bind,source={deploy / "e2e/browser_suite.py"},target=/suite.py,readonly',
            '--mount', f'type=bind,source={evidence},target=/evidence',
            IMAGE, '-c', setup,
        ]
        print('Running five real-browser candidates. Evidence:', evidence, flush=True)
        started = True
        completed = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                   errors='replace', timeout=1100)
        text = completed.stdout + '\n' + completed.stderr
        for value in (config['password'], 'E2e9' + config['password'], config['rabbit_password']):
            text = text.replace(value, '[REDACTED]')
        (evidence / 'execution.log').write_text(text, encoding='utf-8')
        print(text, flush=True)
        metadata['container_exit_code'] = completed.returncode
        passed = False
        if (evidence / 'summary.json').exists():
            summary = json.loads((evidence / 'summary.json').read_text())
            passed = (completed.returncode == 0 and summary.get('passed') is True
                      and summary.get('tests') == 5 and summary.get('errors') == 0
                      and summary.get('failures') == 0 and summary.get('skipped') == 0)
        metadata['passed'] = passed
        return 0 if passed else 1
    finally:
        if started:
            subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=30, check=False)
        config_path.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)
        metadata['completed_at'] = datetime.now(timezone.utc).isoformat()
        (evidence / 'run.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
        print('Reports:', evidence, flush=True)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit('E2E run incomplete: ' + str(error)) from error
