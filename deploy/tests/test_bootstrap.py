"""Bootstrap regressions; no Docker daemon, network, or shared database required."""

import contextlib
import importlib.util
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

DEPLOY = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, DEPLOY / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare = load("prepare_for_test", "prepare_local.py")
startup = load("startup_for_test", "testing_up.py")


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="core-testing-regression-")
        self.addCleanup(self.temporary.cleanup)
        self.deploy = Path(self.temporary.name) / "deploy"
        self.deploy.mkdir()
        self.runner = startup.Bootstrap(self.deploy)
        self.runner.state.mkdir()

    def generate(self, root):
        with contextlib.redirect_stdout(io.StringIO()):
            prepare.prepare(root)

    def fake_container(self, args, **kwargs):
        if args[:2] == ["docker", "run"]:
            self.generate(self.runner.state)
        return ""

    def test_generator_covers_required_compose_variables(self):
        self.generate(self.runner.state)
        values = startup.read_env(self.runner.state / ".env")
        required = set(re.findall(r"\$\{([A-Z_]+):\?", (DEPLOY / "compose.yaml").read_text()))
        self.assertFalse(required - values.keys())
        self.assertNotEqual(values["POSTGRES_PASSWORD"], values["APP_DB_PASSWORD"])
        self.assertGreaterEqual(len(values["APP_DB_PASSWORD"]), 32)

    def test_private_key_loads_and_configuration_is_not_overwritten(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        self.generate(self.runner.state)
        key = self.runner.state / "secrets" / "jwt-private.pem"
        loaded = serialization.load_pem_private_key(key.read_bytes(), password=None)
        self.assertIsInstance(loaded, rsa.RSAPrivateKey)
        self.assertGreaterEqual(loaded.key_size, 2048)
        before = {p: p.read_bytes() for p in [key, self.runner.state / ".env"]}
        with self.assertRaises(SystemExit):
            self.generate(self.runner.state)
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_generation_does_not_print_credentials(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            prepare.prepare(self.runner.state)
        for value in startup.read_env(self.runner.state / ".env").values():
            if len(value) > 20:
                self.assertNotIn(value, output.getvalue())

    def test_testing_configuration_is_complete_and_rerun_preserves_bytes(self):
        with patch.object(self.runner, "run", side_effect=self.fake_container):
            self.runner.prepare_configuration()
        before = (self.runner.state / ".env").read_bytes()
        with patch.object(self.runner, "run") as command:
            self.runner.prepare_configuration()
        command.assert_not_called()
        self.assertEqual(before, (self.runner.state / ".env").read_bytes())
        values = startup.read_env(self.runner.state / ".env")
        self.assertEqual("18080", values["CORE_HTTP_PORT"])
        self.assertEqual(self.runner.frontend.as_posix(), values["CORE_FRONTEND_PATH"])

    def test_partial_credentials_are_preserved_and_rejected(self):
        env = self.runner.state / ".env"
        env.write_text("preserve-me", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "Incomplete"):
            self.runner.prepare_configuration()
        self.assertEqual("preserve-me", env.read_text())

    def test_existing_volumes_without_credentials_are_not_reinitialized(self):
        with patch.object(self.runner, "run", return_value="muni-core-testing_postgres_data\n"):
            with self.assertRaisesRegex(RuntimeError, "volumes already exist"):
                self.runner.prepare_configuration()
        self.assertFalse((self.runner.state / ".env").exists())

    def test_changed_testing_config_is_not_silently_repaired(self):
        with patch.object(self.runner, "run", side_effect=self.fake_container):
            self.runner.prepare_configuration()
        env = self.runner.state / ".env"
        changed = env.read_text().replace("CORE_HTTP_PORT=18080", "CORE_HTTP_PORT=443")
        env.write_text(changed, encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            self.runner.prepare_configuration()
        self.assertEqual(changed, env.read_text())

    def test_compose_project_and_env_file_are_explicit(self):
        with patch.object(self.runner, "run", return_value="") as command:
            self.runner.compose("config", "--quiet")
        args = command.call_args.args[0]
        self.assertEqual(startup.PROJECT, args[args.index("--project-name") + 1])
        self.assertEqual(str(self.runner.state / ".env"), args[args.index("--env-file") + 1])
        self.assertNotIn("--volumes", args)

    def test_clean_trial_uses_its_own_project_and_port(self):
        runner = startup.Bootstrap(self.deploy, project="muni-core-testing-clean", port=18081)
        with patch.object(runner, "run", side_effect=self.fake_container):
            runner.prepare_configuration()
        self.assertEqual("18081", startup.read_env(runner.state / ".env")["CORE_HTTP_PORT"])
        with patch.object(runner, "run", return_value="") as command:
            runner.compose("config", "--quiet")
        args = command.call_args.args[0]
        self.assertEqual("muni-core-testing-clean", args[args.index("--project-name") + 1])

    def test_project_outside_testing_namespace_is_rejected(self):
        with self.assertRaises(ValueError):
            startup.Bootstrap(self.deploy, project="muni-core", port=18081)
        with self.assertRaises(ValueError):
            startup.Bootstrap(self.deploy, project="muni-core-testing-clean", port=443)

    def test_shell_cannot_override_isolated_compose_values(self):
        with patch.dict(os.environ, {"CORE_HTTP_PORT": "443", "APP_DB_PASSWORD": "private-test-value"}):
            with patch.object(startup.subprocess, "run", return_value=SimpleNamespace(stdout="")) as run:
                self.runner.run(["docker", "compose", "version"])
        environment = run.call_args.kwargs["env"]
        self.assertNotIn("CORE_HTTP_PORT", environment)
        self.assertNotIn("APP_DB_PASSWORD", environment)

    def test_remote_docker_context_is_rejected(self):
        with patch.object(self.runner, "run", return_value=json.dumps("ssh://remote-server")):
            with self.assertRaisesRegex(RuntimeError, "remote"):
                self.runner.verify_local_engine()

    def test_remote_docker_host_override_is_rejected(self):
        with patch.dict(os.environ, {"DOCKER_HOST": "tcp://remote-server:2376"}):
            with patch.object(self.runner, "run", return_value=json.dumps("unix:///var/run/docker.sock")):
                with self.assertRaisesRegex(RuntimeError, "remote"):
                    self.runner.verify_local_engine()

    def test_existing_frontend_must_match_pin(self):
        self.runner.frontend.mkdir()
        with patch.object(self.runner, "run", side_effect=["wrong-ref", ""]):
            with self.assertRaisesRegex(RuntimeError, "differs"):
                self.runner.checkout_frontend()

    def test_existing_frontend_changes_are_preserved(self):
        self.runner.frontend.mkdir()
        with patch.object(self.runner, "run", side_effect=[startup.FRONTEND_REF, " M src/App.jsx"]):
            with self.assertRaisesRegex(RuntimeError, "differs"):
                self.runner.checkout_frontend()

    def test_timeout_does_not_report_success(self):
        with patch.object(startup.time, "monotonic", return_value=self.runner.started + 901):
            with self.assertRaisesRegex(RuntimeError, "15 minutes"):
                self.runner.remaining()

    def test_api_ready_without_worker_consumers_is_not_success(self):
        services = "api\nworker\nfrontend\npostgres\nrabbitmq\n"
        with patch.object(startup.urllib.request, "urlopen", return_value=io.BytesIO(b'{"status":"up"}')):
            with patch.object(self.runner, "compose", side_effect=[services, "core.inbox 0\nq.dlq 0\n"]):
                with patch.object(startup.time, "sleep", side_effect=RuntimeError("still waiting")):
                    with self.assertRaisesRegex(RuntimeError, "still waiting"):
                        self.runner.wait_ready()

    def test_api_and_both_worker_consumers_are_ready(self):
        services = "api\nworker\nfrontend\npostgres\nrabbitmq\n"
        with patch.object(startup.urllib.request, "urlopen", return_value=io.BytesIO(b'{"status":"up"}')):
            with patch.object(self.runner, "compose", side_effect=[services, "name consumers\ncore.inbox 1\nq.dlq 1\n"]):
                with patch.object(startup.time, "sleep") as sleep:
                    self.runner.wait_ready()
        sleep.assert_not_called()

    def test_failure_releases_lock(self):
        with patch.object(startup.shutil, "which", return_value="available"):
            with patch.object(self.runner, "verify_local_engine"):
                with patch.object(self.runner, "run", return_value=""):
                    with patch.object(self.runner, "normalize_init_script"):
                        with patch.object(self.runner, "checkout_frontend", side_effect=RuntimeError("checkout failed")):
                            with self.assertRaisesRegex(RuntimeError, "checkout failed"):
                                self.runner.start()
        self.assertFalse((self.runner.state / "bootstrap.lock").exists())

    def test_windows_crlf_init_script_is_normalized_before_execution(self):
        path = self.deploy / "postgres-init" / "10-core-app.sh"
        path.parent.mkdir()
        path.write_bytes(b"#!/bin/sh\r\nset -eu\r\necho ready\r\n")
        self.runner.normalize_init_script()
        self.assertEqual(b"#!/bin/sh\nset -eu\necho ready\n", path.read_bytes())
        self.runner.normalize_init_script()
        self.assertEqual(b"#!/bin/sh\nset -eu\necho ready\n", path.read_bytes())


if __name__ == "__main__":
    unittest.main()
