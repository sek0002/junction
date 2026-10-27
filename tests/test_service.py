"""Service configuration preserves its chosen port and keeps state outside Git."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]

def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

configure=load('configure_service');serve=load('serve')


class ServiceTests(unittest.TestCase):
    def test_random_port_is_selected_once_and_existing_configuration_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'junction.env'
            with patch.object(configure,'choose_port',return_value=48173) as choose:
                self.assertTrue(configure.configure(path));self.assertFalse(configure.configure(path,'0.0.0.0','50000'))
                choose.assert_called_once_with('127.0.0.1')
            self.assertIn('GOLDEN_GATE_PORT=48173',path.read_text())
            self.assertIn('GOLDEN_GATE_HOST=127.0.0.1',path.read_text())
            self.assertIn('/var/lib/junction/golden_gate.sqlite3',path.read_text())
            self.assertEqual(path.stat().st_mode&0o777,0o600)

    def test_manual_and_ephemeral_ports_and_proxy_settings(self):
        self.assertIn('GOLDEN_GATE_PORT=0',configure.environment_text('0.0.0.0',0))
        options=serve.server_options({'GOLDEN_GATE_PORT':'0','GOLDEN_GATE_HOST':'0.0.0.0'})
        self.assertEqual((options['port'],options['host'],options['workers']),(0,'0.0.0.0',1))
        self.assertNotIn('*',options['forwarded_allow_ips'])
        for port in ('-1','65536','not-a-port'):
            with self.assertRaises(ValueError):serve.server_options({'GOLDEN_GATE_PORT':port})
        with self.assertRaises(ValueError):configure.environment_text('host\nBAD=yes',8765)

    def test_service_uses_external_persistent_state_and_environment(self):
        unit=(ROOT/'deploy/junction.service').read_text()
        for expected in ('User=junction','StateDirectory=junction','EnvironmentFile=/etc/junction/junction.env','Restart=on-failure','/opt/junction/scripts/serve.py','ProtectSystem=strict'):
            self.assertIn(expected,unit)
        self.assertNotIn('--reload',unit)


if __name__=='__main__':unittest.main()
