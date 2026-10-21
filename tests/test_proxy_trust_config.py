from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_compose_trusts_forwarded_headers_only_from_proxy():
    services = yaml.safe_load((ROOT / 'deploy/compose.full.yaml').read_text(encoding='utf-8'))['services']
    dockerfile = (ROOT / 'backend/Dockerfile').read_text(encoding='utf-8')
    api_command = ' '.join(services['api']['command'])

    assert '--forwarded-allow-ips "*"' not in dockerfile
    assert '--forwarded-allow-ips' in api_command
    assert '${PROXY_API_IP:-172.30.0.2}' in api_command
    assert services['api']['networks']['proxy_api'] == {}
    assert services['proxy']['networks']['proxy_api']['ipv4_address'] == '${PROXY_API_IP:-172.30.0.2}'
    assert 'proxy_api' not in services['frontend']['networks']
